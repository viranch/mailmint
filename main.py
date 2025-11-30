import yaml
import pandas as pd
from datetime import datetime, timedelta
import importlib

from mailmint.google.gmail import GMail
from mailmint.google.gsheet import GSheet
from mailmint.helpers import get_email_html

def load_config():
    with open("config.yml", "r") as f:
        return yaml.safe_load(f)

config = load_config()

def import_class(full_class_path):
    """
    Import a class from a full path string like:
      'issuers.bank_of_example.BankOfExampleParser'
    """
    module_path, class_name = full_class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)

def get_parser_for_issuer(issuer_config):
    parser_path = issuer_config.pop("parser_class", "mailmint.issuers.base.BaseIssuerParser")
    if not parser_path:
        raise ValueError(f"No 'parser_class' provided in config for issuer: {issuer_config.get('name')}")
    parser_cls = import_class(parser_path)
    return parser_cls(issuer_config)

def dump_email(msg, body):
    mid = msg.get("id", "unknown")
    fname = f"/tmp/email_{mid}.html"
    open(fname, "w").write(body)
    return fname

def extract_transactions(messages, parser):
    transactions = []

    skipped = 0

    for msg in messages:
        html_body = get_email_html(msg)
        if config.get("debug", False):
            fname = dump_email(msg, html_body)
            print(f"Email written to (debug mode): {fname}")

        required_keywords = ["inr", "rs."]
        if not any(kw.lower() in html_body.lower() for kw in required_keywords):
            skipped += 1
            continue

        details = parser.parse_email_body(html_body, msg)
        if not details:
            fname = dump_email(msg, html_body)
            print(f"No transaction details found in: {fname}")
            continue

        email_date = datetime.fromtimestamp(int(msg["internalDate"]) / 1000)
        category = "Uncategorized"
        transaction = {
            "date": email_date.strftime("%Y-%m-%d"),
            "account": details.get("account"),
            "merchant": details.get("merchant"),
            "amount": details.get("amount"),
            "category": category
        }
        print(transaction)
        transactions.append(transaction)

    print(f"{parser.name}: Skipped {skipped} emails without required keywords.")

    return transactions

def prepare_transaction_sheets(transactions):
    if not transactions:
        print("No transactions found.")
        return []

    df = pd.DataFrame(transactions)
    df["month"] = df["date"].str[:7]  # YYYY-MM

    sheets_data = []
    for month, group in df.groupby("month"):
        group = group.sort_values("date")
        values = group[["date", "amount", "merchant", "account", "category"]].values.tolist()
        sheets_data.append((month, values))

    return sheets_data

def main():
    gmail_service = GMail()
    sheets_service = GSheet()

    now = datetime.now()
    after = (now - timedelta(days=150)).strftime("%Y/%m/%d")

    all_transactions = []
    for issuer in config["issuers"]:
        parser = get_parser_for_issuer(issuer)
        messages = gmail_service.get_emails(issuer["email_query"], after)
        print(f"{issuer['name']}: Parsing {len(messages)} emails.")

        transactions = extract_transactions(messages, parser)
        all_transactions.extend(transactions)
        print(f"{issuer['name']}: Extracted {len(transactions)} transactions.")

    sheets_data = prepare_transaction_sheets(all_transactions)
    sheets_service.write_to_spreadsheet(config["spreadsheet_id"], sheets_data)

if __name__ == "__main__":
    main()
