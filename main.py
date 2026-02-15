import yaml
import pandas as pd
import os
import glob
import logging
from datetime import datetime, timedelta
import importlib
from collections import defaultdict
import requests

from mailmint.google.gmail import GMail
from mailmint.google.gsheet import GSheet
from mailmint.helpers import get_email_html

def load_config():
    with open("config.yml", "r") as f:
        return yaml.safe_load(f)

config = load_config()

# set up basic logging for discovery helper
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_script_dir():
    """Return the absolute directory containing this script, independent of CWD."""
    return os.path.dirname(os.path.abspath(__file__))

def discover_token_pickles(script_dir=None, pattern="*.pickle"):
    """Return list of absolute paths to token pickle files found in script directory.

    Args:
        script_dir: directory to search; defaults to directory of this script.
        pattern: glob pattern to match files (defaults to "*.pickle").
    """
    if script_dir is None:
        script_dir = get_script_dir()
    search_path = os.path.join(script_dir, pattern)
    picks = glob.glob(search_path)
    # sort for deterministic order
    picks.sort()
    return picks

def build_gmail_clients_from_pickles(script_dir=None, pattern="*.pickle"):
    """Discover pickle token files and instantiate a GMail client for each.

    Returns a list of dicts: {"token": path, "client": GMail instance, "email": account email or None}
    Invalid or un-authorisable token files are skipped with a warning.
    """
    clients = []
    picks = discover_token_pickles(script_dir=script_dir, pattern=pattern)
    if not picks:
        logger.info("No token pickles found in %s", script_dir or get_script_dir())
        return clients

    for p in picks:
        try:
            g = GMail(creds="credentials.json", token=p)
            # try to fetch profile email to verify token works
            try:
                profile = g.client.users().getProfile(userId="me").execute()
                email = profile.get("emailAddress")
            except Exception:
                # token might be invalid/expired but client constructed; record None
                email = None
            clients.append({"token": p, "client": g, "email": email})
            logger.info("Loaded token: %s (email=%s)", os.path.basename(p), email)
        except Exception as e:
            logger.warning("Skipping token %s: %s", p, str(e))
            continue

    return clients

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
            logger.debug("Email written to (debug mode): %s", fname)

        required_keywords = ["inr", "rs."]
        if not any(kw.lower() in html_body.lower() for kw in required_keywords):
            skipped += 1
            continue

        details = parser.parse_email_body(html_body, msg)
        if not details:
            fname = dump_email(msg, html_body)
            logger.warning("No transaction details found in: %s", fname)
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
        logger.info("Parsed transaction: %s", transaction)
        transactions.append(transaction)

    logger.info("%s: Skipped %d emails without required keywords.", parser.name, skipped)

    return transactions

def prepare_transaction_sheets(transactions):
    if not transactions:
        logger.info("No transactions found.")
        return []

    df = pd.DataFrame(transactions)
    df["month"] = df["date"].str[:7]  # YYYY-MM

    sheets_data = []
    for month, group in df.groupby("month"):
        group = group.sort_values("date")
        values = group[["date", "amount", "merchant", "account", "category"]].values.tolist()
        yield month, values

def pushover(account_balances):
    if not account_balances:
        logger.info("No account balances to send.")
        return

    total = sum(account_balances.values())
    message = f"<b>Total: ₹{total:,.2f}</b>" + "\n" + "\n".join(f"{acc}: ₹{bal:,.2f}" for acc, bal in account_balances.items())
    logger.info("Sending Pushover notification:\n%s", message)

    po = config.get("pushover", {})
    user, token = po.get("user_key"), po.get("api_token")

    if not user or not token:
        logger.warning("Pushover credentials not configured. Skipping notification.")
        return

    requests.post("https://api.pushover.net/1/messages.json", params={'html': 1}, data={
        "token": token,
        "user": user,
        "message": message,
    })

def main():
    sheets_client = GSheet()
    gmail_clients = build_gmail_clients_from_pickles()

    now = datetime.now()
    # last 2 calendar months
    after = (now.replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y/%m/%d")

    all_transactions = []
    account_balances = defaultdict(float)
    for issuer in config["issuers"]:
        parser = get_parser_for_issuer(issuer)

        messages = []
        for client_data in gmail_clients:
            gmail_client = client_data["client"]
            messages.extend(gmail_client.get_emails(issuer["email_query"], after))

        logger.info("%s: Parsing %d emails.", issuer.get("name"), len(messages))

        transactions = extract_transactions(messages, parser)
        all_transactions.extend(transactions)
        logger.info("%s: Extracted %d transactions.", issuer.get("name"), len(transactions))

        if issuer.get("notify_balance", False) and transactions:
            # report balances for all accounts and transactions uptil yesterday
            # to handle edge case of when the new month starts
            yesterday_month = (now - timedelta(days=1)).strftime("%Y-%m")
            for trx in transactions:
                if trx["date"][:7] == yesterday_month:
                    if any(excl in trx["merchant"].lower() for excl in issuer.get("notify_exclude_merchants", [])):
                        logger.info("Excluding merchant '%s' from balance calculation for account %s.", trx["merchant"], trx["account"])
                        continue
                    account_balances[trx["account"]] += trx["amount"]

    for month, transactions in prepare_transaction_sheets(all_transactions):
        logger.info("Prepared sheet data for month %s with %d transactions.", month, len(transactions))
        sheets_client.write_to_spreadsheet(config["spreadsheet_id"], month, transactions)

    for acc, bal in account_balances.items():
        account_balances[acc] = -bal  # negate to show positive balance if net debits exceed credits
        logger.info("Account balance for %s: %.2f", acc, account_balances[acc])

    pushover(account_balances)

if __name__ == "__main__":
    main()
