"""Crea el token de pujada: el mòbil porta el token, el servidor només el seu hash.

    python3 captura/genera_token.py

Imprimeix (1) el contingut de config.php per al servidor i (2) el pujada.json per al mòbil.
El token també es desa a ~/.config/3d2real-captura/token (permisos 600). No és una clau SFTP.
"""
import hashlib
import os
import secrets
from pathlib import Path

D = Path.home() / ".config" / "3d2real-captura"
D.mkdir(parents=True, exist_ok=True)
T = D / "token"
if T.exists():
    token = T.read_text().strip()
    print("(es reutilitza el token existent)")
else:
    token = secrets.token_urlsafe(32)
    fd = os.open(T, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
print("== servidor: captura/servidor/config.php")
print("<?php return ['token_sha256' => '%s'];" % hashlib.sha256(token.encode()).hexdigest())
print("\n== mòbil: Android/data/cat.escena.captura3d/files/pujada.json (canvia la URL)")
print('{"url": "https://EL-TEU-DOMINI/captura/pujada.php", "token": "%s"}' % token)
