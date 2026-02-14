import sys
from mailmint.google.gmail import GMail


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <credentials.json> <token.pickle>")
        sys.exit(1)
    credentials_file = sys.argv[1]
    token_file = sys.argv[2]
    GMail(creds=credentials_file, token=token_file)
    print(f"Token saved to {token_file}")
