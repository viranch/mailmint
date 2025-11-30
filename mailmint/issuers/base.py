import re

class BaseIssuerParser:
    def __init__(self, issuer_config):
        self.config = issuer_config
        self.name = issuer_config.get("name", "Unknown Issuer")

        self.patterns = []
        for pattern_entry in self.config.get("patterns", []):
            self.patterns.append({
                "pattern": re.compile(pattern_entry["pattern"]),
                "direction": pattern_entry["direction"],
            })

    def parse_email_body(self, email_body_html, email_metadata):
        """
        Parse the email body and return a dict with keys:
        - amount
        - merchant
        - account name
        """
        if not self.patterns:
            raise NotImplementedError

        for pattern_entry in self.patterns:
            pattern = pattern_entry["pattern"]
            direction = pattern_entry["direction"]
            data = pattern.search(email_body_html)
            if data:
                return {
                    "amount": direction * float(data.group("amount").replace(",", "")),
                    "merchant": data.group("merchant").strip(),
                    "account": self.name + " xx" + data.group("account"),
                }

        return {}
