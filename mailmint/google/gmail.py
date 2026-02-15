from googleapiclient.errors import HttpError
from urllib.parse import quote
import logging
import time
import random

from mailmint.google.base import BaseGoogle, register_scope

register_scope("https://www.googleapis.com/auth/gmail.readonly")


class GMail(BaseGoogle):
    def __init__(self, creds="credentials.json", token="token_gmail.pickle"):
        super().__init__("gmail", "v1", creds, token)
        # instance logger
        self.logger = logging.getLogger(__name__)

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

    def bulk_fetch_messages(self, message_ids, batch_size=100, fmt="full", fields=None,
                            attempt=0, max_retries=5, initial_delay=1.0):
        """
        Fetch many Gmail messages using batch requests.
        - message_ids: list of message ids (strings)
        - batch_size: number of messages per batch (50-100 recommended)
        - fmt: 'full' | 'metadata' | 'raw' etc.
        - fields: optional fields string to reduce payload size
        - max_retries: max number of retries per batch on rate limit errors
        - initial_delay: initial delay in seconds for exponential backoff

        Returns list of response dicts (only successful ones included).
        """
        results = {}
        rate_limited_ids = []

        def batch_callback(request_id, response, exception):
            if exception:
                is_rate_limit = (
                    isinstance(exception, HttpError)
                    and exception.resp.status in (429, 403)
                    and ('rateLimitExceeded' in str(exception) or 'userRateLimitExceeded' in str(exception))
                )
                if is_rate_limit:
                    rate_limited_ids.append(request_id)
                else:
                    self.logger.warning("Error fetching message %s: exception=%s, response=%s", request_id, exception, response)
                    results[request_id] = {"error": exception}
            else:
                results[request_id] = response

        def _build_request(mid):
            if fields:
                return self.client.users().messages().get(userId="me", id=mid, format=fmt, fields=fields)
            else:
                return self.client.users().messages().get(userId="me", id=mid, format=fmt)

        for i in range(0, len(message_ids), batch_size):
            slice_ids = message_ids[i:i + batch_size]

            batch = self.client.new_batch_http_request(callback=batch_callback)
            for mid in slice_ids:
                batch.add(_build_request(mid), request_id=mid)
            try:
                batch.execute()
            except HttpError as e:
                self.logger.warning("Batch execute error: %s", e)

        # Retry any rate-limited IDs from this batch with exponential backoff
        if rate_limited_ids and attempt < max_retries:
            delay = initial_delay * (2 ** attempt) + random.uniform(0, 1)
            self.logger.warning(
                "Rate limit hit for %d message(s) in batch %d/%d. Retry %d/%d in %.1fs...",
                len(rate_limited_ids),
                i // batch_size + 1,
                (len(message_ids) + batch_size - 1) // batch_size,
                attempt + 1,
                max_retries,
                delay,
            )
            time.sleep(delay)

            # Recursive retry for rate-limited messages
            retried = self.bulk_fetch_messages(rate_limited_ids, batch_size=batch_size, fmt=fmt, fields=fields, attempt=attempt + 1)
            for msg in retried:
                results[msg["id"]] = msg
        elif rate_limited_ids:
            # If still rate-limited after all retries, log them as errors
            for mid in rate_limited_ids:
                self.logger.error("Failed to fetch message %s after %d retries (rate limited)", mid, max_retries)
                results[mid] = {"error": "rateLimitExceeded after retries"}

        # Convert results to list (skip errors)
        emails = []
        for entry in results.values():
            if isinstance(entry, dict) and "error" in entry:
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
