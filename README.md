# Gmail Transactions to Google Sheets

## Setup

1. **Setup environment:**
   ```bash
   ./scripts/setup-env
   ```

2. **Google API Credentials:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/).
   - Enable Gmail API and Google Sheets API.
   - Download `credentials.json` and place it in this folder.

3. **Configure:**
   - Create `config.yaml` with your issuer details and Google Sheets ID.
   - The `spreadsheet_id` must contain the ID of an existing Google spreadsheet that _your_ Google account has access to _and_ contains a sheet titled "Template". See [this spreadsheet](https://docs.google.com/spreadsheets/d/1q6Hi7OIl-hmbdJCR36JjpqeYDye4ud8hD7Tg9qPsiTA/) as an example. Feel free to clone it.
   - Example config:
      ```yaml
      spreadsheet_id: "32TmpST7k_FBupEtGBt3pkrGSmyrkhRlNe-9CVlb-lJqI"
      issuers:
      - name: Lender Bank Credit Card
        email_query: 'from:alerts@abcbank.com subject:"ABC Bank Credit Card Transaction Alert"'
        patterns:
          - pattern: 'INR (?P<amount>[0-9,]+\.\d{2}) were spent on your .* xx(?P<account>\d{4}) at (?P<merchant>.*) on '
            direction: -1
      - name: WallStreet Bank Account
        email_query: 'from:online@wsbank.com subject:"Transaction Alert from WS Bank"'
        patterns:
          - pattern: 'Rs\.\s*(?P<amount>[0-9,]+\.\d{2}) deducted from .*XX(?P<acc>\d{4}) by (?P<merchant>.*) on '
            direction: -1
          - pattern: 'Rs\.\s*(?P<amount>[0-9,]+\.\d{2}) credited to .*XX(?P<acc>\d{4}) for (?P<merchant>.*) on '
            direction: 1
      ```
      Every `issuers` entry must include:
      - A `name`
      - An `email_query` that is a GMail search query to identify the issuer's transaction emails
      - A list of `patterns` entries, each containing a `pattern` regex -- that captures `amount`, `account` and `merchant`. `account` is usually the last 4 digits of a credit card or a bank account -- and a `direction` value that indicates a negative or a positive ledger entry.
      - Alternative to `patterns` is the ability to pass a custom `parser_class` that subclasses `mailmint.issuers.base.BaseIssuerParser` and its `parse_email_body` method for a more complex email parsing solution. Example:
      ```yaml
      issuers:
      - name: Lender Bank Credit Card
        email_query: 'from:alerts@abcbank.com subject:"ABC Bank Credit Card Transaction Alert"'
        parser_class: mailmint.issuers.hdfc.HDFCBankParser
      ```

4. **Run:**
   ```bash
   source env/bin/activate
   python main.py
   ```

5. **Automate:**
   - Use `cron` to schedule the script as needed.

## Notes

- The script will prompt for Google authentication on first run.
- Each calendar month gets its own sheet in the spreadsheet.
