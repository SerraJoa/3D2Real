"""Desplega el servidor de pujada (pujada.php + config.php) a la carpeta del hosting per SFTP.

    python3 captura/genera_token.py          # un cop: crea ~/.config/3d2real-captura/token
    python3 captura/desplega.py              # puja a la carpeta «3d2real» (--sec: només mostra què faria)

Config, que crees tu (secret, permisos 600): ~/.config/3d2real-captura/sftp.json
    {"host": "...", "port": 22, "user": "...", "password": "...", "carpeta": "3d2real"}
    (en lloc de "password" pots posar "clau": "/ruta/id_ed25519").
`carpeta` és relativa a l'arrel SFTP; si la web penja de, p. ex., `htdocs`, posa "htdocs/3d2real".
No sobreescriu un config.php existent (sense --forca) ni toca res fora de la carpeta.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

D = Path.home() / ".config" / "3d2real-captura"
ARREL = Path(__file__).resolve().parent


def config_php(token: str) -> str:
    return "<?php return ['token_sha256' => '%s'];\n" % hashlib.sha256(token.encode()).hexdigest()


def connecta(cfg):
    import paramiko
    c = paramiko.SSHClient()
    c.load_system_host_keys()
    c.set_missing_host_key_policy(paramiko.RejectPolicy())     # primera vegada: ssh-keyscan -H HOST >> ~/.ssh/known_hosts
    kw = dict(hostname=cfg["host"], port=int(cfg.get("port", 22)), username=cfg["user"], timeout=20, allow_agent=False, look_for_keys=False)
    if cfg.get("clau"):
        kw["key_filename"] = cfg["clau"]
    else:
        kw["password"] = cfg["password"]
    c.connect(**kw)
    return c, c.open_sftp()


def mkdirs(s, ruta, sec):
    cur = ""
    for p in [x for x in ruta.split("/") if x]:
        cur = f"{cur}/{p}" if cur else p
        try:
            s.stat(cur)
        except IOError:
            print(f"crea carpeta {cur}")
            if not sec:
                s.mkdir(cur)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sec", action="store_true", help="no escriu res al servidor")
    ap.add_argument("--forca", action="store_true", help="sobreescriu config.php (canvia el token)")
    a = ap.parse_args()
    if not (D / "token").exists():
        sys.exit("Primer: python3 captura/genera_token.py")
    if not (D / "sftp.json").exists():
        sys.exit(f"Falta {D / 'sftp.json'} (vegeu la capçalera d'aquest fitxer).")
    token = (D / "token").read_text().strip()
    cfg = json.loads((D / "sftp.json").read_text())
    carpeta = cfg.get("carpeta", "3d2real").strip("/")
    if not carpeta or ".." in carpeta.split("/"):
        sys.exit("«carpeta» no és vàlida.")
    c, s = connecta(cfg)
    mkdirs(s, carpeta, a.sec)
    mkdirs(s, carpeta + "/dades", a.sec)
    print(f"puja {carpeta}/pujada.php")
    if not a.sec:
        s.put(str(ARREL / "servidor" / "pujada.php"), f"{carpeta}/pujada.php")
    try:
        s.stat(f"{carpeta}/config.php")
        existeix = True
    except IOError:
        existeix = False
    if existeix and not a.forca:
        print(f"{carpeta}/config.php ja hi és: no es toca (--forca per canviar el token)")
    else:
        print(f"puja {carpeta}/config.php")
        if not a.sec:
            with s.open(f"{carpeta}/config.php", "w") as f:
                f.write(config_php(token))
            s.chmod(f"{carpeta}/config.php", 0o640)
    c.close()
    print("\nFet. Ara: python3 captura/prova_servidor.py https://EL-TEU-DOMINI/<carpeta web>/pujada.php")


if __name__ == "__main__":
    main()
