import base64

def get_html_body(payload):
    # mime = payload.get("mimeType")
    data = payload.get("body", {}).get("data")
    return base64.urlsafe_b64decode(data).decode("utf-8") if data else ""
    # if mime == "text/html" and data:
    #     return base64.urlsafe_b64decode(data).decode("utf-8")

    # return ""

def get_email_html(msg):
    payload = msg.get("payload", {})

    html_body = get_html_body(payload)
    # Some messages put HTML in body->data directly when no parts
    if html_body:
        return html_body

    for part in payload.get("parts", []):
        html_body = get_html_body(part)
        if html_body:
            return html_body

        # fallback: sometimes nested parts
        if mime == "multipart/alternative":
            for sub in part.get("parts", []):
                html_body = get_html_body(sub)
                if html_body:
                    return html_body

    return ""
