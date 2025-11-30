import re
from mailmint.issuers.base import BaseIssuerParser


class HDFCBankParser(BaseIssuerParser):
    def parse_email_body(self, email_body_html, email_metadata):
        line_patterns = [
            r"Rs\.\s*(INR\s*)?(?P<rs>[0-9,]+)(?P<ps>\.\d{1,2})?.*(?P<dir>[Ff]rom|to) .*(XX|\*\*)(?P<acc>\d{4})(<br>)?"
        ]
        data = None
        for l in email_body_html.splitlines():
            l = l.strip()
            for lp in line_patterns:
                data = re.search(lp, l)
                if data:
                    break
            if data:
                break

        if not data:
            for lp in line_patterns:
                data = re.search(lp, email_body_html, re.DOTALL)
                if data:
                    break

        if not data:
            return {}

        amount = data.group("rs").replace(",", "")
        paise = data.group("ps")
        if paise:
            amount += paise
        amount = float(amount)
        if data.group("dir").lower() in ["from"]:
            amount = -amount
        account = "HDFC Bank account xx" + data.group("acc")

        meta = data.string[data.end():].strip()
        meta = re.split(r"(\. )|<", meta)[0].strip()
        meta = re.split(r" on \d{2}-", meta)[0].strip()
        drop_phrases = [
            r"^(from|by) ",
            r"^(for|to|on account of)( a)? ",
        ]
        for dp in drop_phrases:
            meta = re.sub(dp, "", meta, flags=re.IGNORECASE).strip()

        return {
            "amount": amount,
            "merchant": meta,
            "account": account,
        }
