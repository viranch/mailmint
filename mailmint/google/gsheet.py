from mailmint.google.base import BaseGoogle, register_scope

register_scope("https://www.googleapis.com/auth/spreadsheets")


class GSheet(BaseGoogle):
    def __init__(self, creds="credentials.json", token="token_gmail.pickle"):
        super().__init__("sheets", "v4", creds, token)

    def ensure_sheet(self, spreadsheet_id, sheet_name, template_sheet="Template"):
        # create sheet_name if not exists
        existing_sheets = self.client.spreadsheets().get(spreadsheetId=spreadsheet_id).execute().get("sheets", [])

        # Duplicate an existing 'Template' sheet unless existing sheet_name is found.
        template = None
        for s in existing_sheets:
            props = s.get("properties", {})
            title = props.get("title")
            if title == sheet_name:
                return
            elif title == template_sheet:
                template = props

        if not template:
            raise("Template sheet '{teamplate_sheet}' not found")

        template_id = template["sheetId"]
        self.client.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [{
                    "duplicateSheet": {
                        "sourceSheetId": template_id,
                        "newSheetName": sheet_name
                    }
                }]
            }
        ).execute()

    def write_to_spreadsheet(self, spreadsheet_id, sheet_name, sheet_data, template_sheet="Template"):
        if not sheet_data:
            return

        self.ensure_sheet(spreadsheet_id, sheet_name, template_sheet)

        # clear 1000 rows of the sheet before writing new data (adjust as needed)
        self.client.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A2:{chr(64 + len(sheet_data[0]))}1000"
        ).execute()

        self.client.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A2",
            valueInputOption="RAW",
            body={"values": sheet_data}
        ).execute()

        print(f"Written {len(sheet_data)} rows to sheet {sheet_name}.")
