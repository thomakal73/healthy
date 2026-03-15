import garth
from getpass import getpass

email    = input("Garmin E-Mail: ")
password = getpass("Passwort: ")

garth.login(email, password)
garth.save("~/.garth")
print("Token gespeichert!")