from googleapiclient.errors import HttpError
from urllib.parse import quote

from mailmint.google.base import BaseGoogle, register_scope

register_scope("https://www.googleapis.com/auth/gmail.readonly")


class GMail(BaseGoogle):
    def __init__(self, creds="credentials.json", token="token_gmail.pickle"):
        super().__init__("gmail", "v1", creds, token)

    def get_emails(self, query, after):
        full_query = f'{query} after:{after} in:anywhere'

        # first, list message ids (handle pagination)
        message_ids = []
        req = self.client.users().messages().list(userId="me", q=full_query, maxResults=500)
        while req:
            res = req.execute()
            message_ids.extend(m["id"] for m in res.get("messages", []))
            token = res.get("nextPageToken")
            req = self.client.users().messages().list(userId="me", q=full_query, pageToken=token, maxResults=500) if token else None

        if not message_ids:
            return {}

        # fetch messages in bulk (request payload headers, parts and internalDate)
        fields = "id,threadId,internalDate,payload(headers(name,value),parts(mimeType,body/data),body/data)"
        fetched = self.bulk_fetch_messages(message_ids, batch_size=80, fmt="full", fields=fields)

        # fetched is a mapping id -> message dict; add `message_link` for each without extra API calls
        for msg in fetched:
            try:
                msg["message_link"] = self.message_link_from_msg(msg)
            except Exception:
                msg["message_link"] = None

        return fetched

    def bulk_fetch_messages(self, message_ids, batch_size=100, fmt="full", fields=None):
        """
        Fetch many Gmail messages using batch requests.
        - message_ids: list of message ids (strings)
        - batch_size: number of messages per batch (50-100 recommended)
        - fmt: 'full' | 'metadata' | 'raw' etc.
        - fields: optional fields string to reduce payload size

        Returns dict mapping message_id -> response dict (only successful ones included).
        """
        results = {}

        def batch_callback(request_id, response, exception):
            if exception:
                results[request_id] = {"error": exception}
            else:
                results[request_id] = response

        for i in range(0, len(message_ids), batch_size):
            batch = self.client.new_batch_http_request(callback=batch_callback)
            slice_ids = message_ids[i:i + batch_size]
            for mid in slice_ids:
                # Build request with optional fields param
                if fields:
                    request = self.client.users().messages().get(userId="me", id=mid, format=fmt, fields=fields)
                else:
                    request = self.client.users().messages().get(userId="me", id=mid, format=fmt)
                batch.add(request, request_id=mid)
            try:
                batch.execute()
            except HttpError as e:
                # log/print as appropriate; keep going with whatever responses we have
                print("Batch execute error:", e)

        # Convert results to mapping mid -> actual response (skip errors)
        emails = []
        for entry in results.values():
            if isinstance(entry, dict) and "error" in entry:
                # skip or log
                continue
            emails.append(entry)

        return emails

    def message_link_from_msg(self, msg):
        """
        Build a Gmail web link for the exact message without an extra API call.
        Prefers the RFC822 Message-ID header (rfc822msgid:...), falls back to threadId or messageId.
        """
        # Extract headers (list of dicts with 'name' and 'value')
        headers = []
        payload = msg.get("payload", {})
        # headers may exist on payload (top-level) or inside parts in some formats; check both
        if payload.get("headers"):
            headers = payload.get("headers", [])
        else:
            # try to find headers in multipart/alternative nested payloads (rare for metadata requested)
            parts = payload.get("parts", []) or []
            for part in parts:
                ph = part.get("headers")
                if ph:
                    headers = ph
                    break

        msgid_header = None
        for h in headers:
            if h.get("name", "").lower() == "message-id":
                msgid_header = h.get("value")
                break

        if msgid_header:
            # Build search URL using rfc822msgid:<message-id>
            query = f"rfc822msgid:{msgid_header}"
            encoded = quote(query, safe="")
            return f"https://mail.google.com/mail/u/0/#search/{encoded}"

        # Fallbacks:
        thread_id = msg.get("threadId")
        if thread_id:
            return f"https://mail.google.com/mail/u/0/#all/{thread_id}"

        mid = msg.get("id")
        if mid:
            return f"https://mail.google.com/mail/u/0/#all/{mid}"

        return None
