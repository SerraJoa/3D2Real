"""Prova de fum de pujada.php un cop desplegat: puja una sessió mínima i comprova les protecció bàsiques.

    python3 captura/prova_servidor.py https://EL-TEU-DOMINI/captura/pujada.php

Fa servir el token de ~/.config/3d2real-captura/token. La sessió de prova es diu 20000101_000000 i es pot esborrar després.
"""
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

url = sys.argv[1]
token = (Path.home() / ".config" / "3d2real-captura" / "token").read_text().strip()


def post(q, cos=b"", t=token, tipus="application/octet-stream"):
    r = urllib.request.Request(f"{url}?{q}", data=cos, method="POST", headers={"X-Token": t, "Content-Type": tipus})
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


dades = b"escena,prova\n1,2\n"
man = {"sessio": "20000101_000000", "fitxers": [{"nom": "prova.csv", "mida": len(dades), "sha256": hashlib.sha256(dades).hexdigest()}]}
ok = True
def comprova(text, cond):
    global ok
    print(("OK   " if cond else "FALLA"), text); ok &= bool(cond)

c, _ = post("a=inici", json.dumps(man).encode(), t="token-equivocat", tipus="application/json")
comprova("rebutja un token equivocat (403)", c == 403)
c, r = post("a=inici", json.dumps(man).encode(), tipus="application/json")
comprova("inici accepta la sessió", c == 200 and r.get("ok"))
c, r = post("a=tros&sessio=20000101_000000&nom=prova.csv&offset=5", dades)
comprova("rebutja un offset que no toca (409)", c == 409)
c, r = post("a=tros&sessio=20000101_000000&nom=prova.csv&offset=0", dades)
comprova("accepta el tros i en comprova el sha256", c == 200 and r.get("offset") == len(dades))
c, r = post("a=fi&sessio=20000101_000000")
comprova("fi marca la sessió com a completa", c == 200 and r.get("ok"))
c, _ = post("a=inici", json.dumps({**man, "sessio": "../../etc"}).encode(), tipus="application/json")
comprova("rebutja una sessió amb ruta (400)", c == 400)
man2 = {**man, "fitxers": [{**man["fitxers"][0], "nom": "x.php"}]}
c, _ = post("a=inici", json.dumps(man2).encode(), tipus="application/json")
comprova("rebutja una extensió no permesa (400)", c == 400)
try:
    urllib.request.urlopen(url.rsplit("/", 1)[0] + "/dades/20000101_000000/prova.csv", timeout=20)
    comprova("dades/ NO es serveix per HTTP", False)
except urllib.error.HTTPError as e:
    comprova(f"dades/ NO es serveix per HTTP (codi {e.code})", e.code in (401, 403, 404))
sys.exit(0 if ok else 1)
