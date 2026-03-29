import garth
import os
from getpass import getpass
from dotenv import load_dotenv
from pathlib import Path

# .env aus dem Benutzer-Ordner laden (wird als Argument übergeben)
import sys
env_file = sys.argv[1] if len(sys.argv) > 1 else ".env"
load_dotenv(env_file)

token_path = os.getenv("GARTH_HOME", os.path.expanduser("~/.garth"))
Path(token_path).mkdir(parents=True, exist_ok=True)

email    = input("Garmin E-Mail: ")
password = getpass("Passwort: ")

garth.login(email, password)
garth.save(token_path)
print(f"Token gespeichert in: {token_path}")