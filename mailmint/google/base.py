import os
import pickle
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = []

def register_scope(scope):
    if scope not in SCOPES:
        SCOPES.append(scope)


class BaseGoogle:
    def __init__(self, service, version, creds="credentials.json", token="token_gmail.pickle"):
        self.authenticate(creds, token)
        self.build_client(service, version)

    def authenticate(self, creds_file, token_file):
        creds = None
        if os.path.exists(token_file):
            with open(token_file, "rb") as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    creds_file, SCOPES)
                creds = flow.run_local_server(port=4999)
            with open(token_file, "wb") as token:
                pickle.dump(creds, token)

        self.credentials = creds

    def build_client(self, service, version):
        self.client = build(service, version, credentials=self.credentials)
