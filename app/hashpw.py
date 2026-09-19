"""Erzeugt einen pbkdf2_sha256-Hash fuer ZE_USERS.  Aufruf: python3 hashpw.py <passwort>"""
import hashlib, os, sys

ITER = 240_000
pw = sys.argv[1] if len(sys.argv) > 1 else sys.exit("Aufruf: hashpw.py <passwort>")
salt = os.urandom(16)
digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER).hex()
print(f"pbkdf2_sha256${ITER}${salt.hex()}${digest}")
