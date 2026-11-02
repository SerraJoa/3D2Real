"""Baixa per SFTP les sessions completes que el mòbil ha pujat i en comprova el sha256.

    python3 captura/baixa_sessions.py [--esborra-remot]

Config (la crees tu; secret, permisos 600): ~/.config/3d2real-captura/sftp.json
    {"host": "...", "port": 22, "user": "...", "password": "...", "remot": "ruta/captura/dades"}
    (en lloc de "password" pots posar "clau": "/ruta/id_ed25519")
Destí: dades/captures/<sessió>/. Una sessió és completa si té el fitxer `.complet` al servidor.
Per defecte no s'esborra res del servidor.
"""
import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path

CONFIG = Path.home() / ".config" / "3d2real-captura" / "sftp.json"
DESTI = Path(__file__).resolve().parent.parent / "dades" / "captures"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def verifica(carpeta: Path, manifest: dict) -> list[str]:
    """Noms dels fitxers del manifest que falten, tenen una altra mida o un altre sha256."""
    dolents = []
    for nom, info in manifest.items():
        p = carpeta / nom
        if not p.is_file() or p.stat().st_size != info["mida"] or sha256(p) != info["sha256"]:
            dolents.append(nom)
    return dolents


def connecta():
    import paramiko
    if not CONFIG.exists():
        sys.exit(f"Falta {CONFIG} (vegeu la capçalera d'aquest fitxer).")
    d = json.loads(CONFIG.read_text())
    c = paramiko.SSHClient()
    c.load_system_host_keys()
    c.set_missing_host_key_policy(paramiko.RejectPolicy())     # la primera vegada: ssh-keyscan o connecta amb sftp a mà
    kw = dict(hostname=d["host"], port=int(d.get("port", 22)), username=d["user"], timeout=20, allow_agent=False, look_for_keys=False)
    if d.get("clau"):
        kw["key_filename"] = d["clau"]
    else:
        kw["password"] = d["password"]
    c.connect(**kw)
    return c, c.open_sftp(), d["remot"].rstrip("/")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--esborra-remot", action="store_true", help="esborra la sessió del servidor un cop baixada i verificada")
    a = ap.parse_args()
    c, s, remot = connecta()
    DESTI.mkdir(parents=True, exist_ok=True)
    noves = 0
    for e in sorted(s.listdir_attr(remot), key=lambda x: x.filename):
        if not stat.S_ISDIR(e.st_mode):
            continue
        nom = e.filename
        try:
            s.stat(f"{remot}/{nom}/.complet")
        except IOError:
            print(f"{nom}: encara incompleta al servidor, s'omet")
            continue
        with s.open(f"{remot}/{nom}/manifest.json") as f:
            man = json.loads(f.read())
        loc = DESTI / nom
        loc.mkdir(exist_ok=True)
        if not verifica(loc, man):
            print(f"{nom}: ja la tens")
        else:
            for fitxer in man:
                if not verifica(loc, {fitxer: man[fitxer]}):
                    continue
                print(f"{nom}/{fitxer}: baixant {man[fitxer]['mida'] >> 20} MB…")
                s.get(f"{remot}/{nom}/{fitxer}", str(loc / fitxer))
            dolents = verifica(loc, man)
            if dolents:
                print(f"{nom}: NO coincideix {dolents}; no s'esborra res")
                continue
            (loc / "manifest.json").write_text(json.dumps(man, indent=1))
            noves += 1
            print(f"{nom}: baixada i verificada → {loc}")
        if a.esborra_remot:
            for x in s.listdir(f"{remot}/{nom}"):
                s.remove(f"{remot}/{nom}/{x}")
            s.rmdir(f"{remot}/{nom}")
            print(f"{nom}: esborrada del servidor")
    c.close()
    print(f"{noves} sessions noves a {DESTI}")


if __name__ == "__main__":
    main()
