"""Servidor HTTP de prova que fa el mateix que servidor/pujada.php (mateixes comprovacions i codis).
Serveix per provar el client de l'app sense PHP; no s'ha de desplegar enlloc."""
import hashlib, json, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MAX_TROS = 8 * 1024 * 1024
SESSIO = re.compile(r"^[0-9]{8}_[0-9]{6}$")
NOM = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")


def nom_ok(n):
    return bool(NOM.match(n)) and ".." not in n and n.rsplit(".", 1)[-1].lower() in ("mp4", "csv", "json")


def crea(carpeta: Path, token: str):
    carpeta.mkdir(parents=True, exist_ok=True)
    token_sha = hashlib.sha256(token.encode()).hexdigest()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def sortida(self, codi, cos):
            b = json.dumps(cos).encode()
            self.send_response(codi); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b)

        def do_POST(self):
            q = urlparse(self.path); p = {k: v[0] for k, v in parse_qs(q.query).items()}
            n = int(self.headers.get("Content-Length", 0)); cos = self.rfile.read(n)
            if hashlib.sha256(self.headers.get("X-Token", "").encode()).hexdigest() != token_sha:
                return self.sortida(403, {"ok": False, "error": "token"})
            a = p.get("a", "")
            if a == "inici":
                d = json.loads(cos or b"{}")
                if not SESSIO.match(str(d.get("sessio", ""))) or not isinstance(d.get("fitxers"), list) or not 1 <= len(d["fitxers"]) <= 12:
                    return self.sortida(400, {"ok": False, "error": "cos"})
                dir_ = carpeta / d["sessio"]; dir_.mkdir(exist_ok=True)
                mf = dir_ / "manifest.json"; man = json.loads(mf.read_text()) if mf.exists() else {}
                rebut = {}
                for f in d["fitxers"]:
                    nom, mida, sha = str(f.get("nom", "")), f.get("mida", -1), str(f.get("sha256", "")).lower()
                    if not nom_ok(nom) or not isinstance(mida, int) or mida < 0 or not re.match(r"^[0-9a-f]{64}$", sha):
                        return self.sortida(400, {"ok": False, "error": "fitxer", "nom": nom})
                    if nom in man and (man[nom]["sha256"] != sha or man[nom]["mida"] != mida):
                        (dir_ / (nom + ".part")).unlink(missing_ok=True); (dir_ / nom).unlink(missing_ok=True)
                    man[nom] = {"mida": mida, "sha256": sha}
                    fp, pp = dir_ / nom, dir_ / (nom + ".part")
                    rebut[nom] = fp.stat().st_size if fp.exists() else (pp.stat().st_size if pp.exists() else 0)
                mf.write_text(json.dumps(man)); (dir_ / ".complet").unlink(missing_ok=True)
                return self.sortida(200, {"ok": True, "rebut": rebut})
            if a == "tros":
                s, nom = p.get("sessio", ""), p.get("nom", "")
                try: off = int(p.get("offset", ""))
                except ValueError: off = -1
                if not SESSIO.match(s) or not nom_ok(nom) or off < 0:
                    return self.sortida(400, {"ok": False, "error": "paràmetres"})
                dir_ = carpeta / s; mf = dir_ / "manifest.json"; man = json.loads(mf.read_text()) if mf.exists() else {}
                if nom not in man: return self.sortida(404, {"ok": False, "error": "fitxer no declarat"})
                if (dir_ / nom).exists(): return self.sortida(409, {"ok": False, "esperat": (dir_ / nom).stat().st_size, "complet": True})
                part = dir_ / (nom + ".part"); tinc = part.stat().st_size if part.exists() else 0
                if off != tinc: return self.sortida(409, {"ok": False, "esperat": tinc})
                if not 1 <= len(cos) <= MAX_TROS or tinc + len(cos) > man[nom]["mida"]:
                    return self.sortida(400, {"ok": False, "error": "mida del tros"})
                with open(part, "ab") as fh: fh.write(cos)
                nou = tinc + len(cos)
                if nou == man[nom]["mida"]:
                    if hashlib.sha256(part.read_bytes()).hexdigest() != man[nom]["sha256"]:
                        part.unlink(); return self.sortida(422, {"ok": False, "error": "sha256 no coincideix", "esperat": 0})
                    part.rename(dir_ / nom)
                return self.sortida(200, {"ok": True, "offset": nou})
            if a == "fi":
                s = p.get("sessio", "")
                if not SESSIO.match(s): return self.sortida(400, {"ok": False, "error": "sessio"})
                dir_ = carpeta / s; mf = dir_ / "manifest.json"
                if not mf.exists(): return self.sortida(404, {"ok": False, "error": "sessió desconeguda"})
                man = json.loads(mf.read_text())
                falten = [k for k, v in man.items() if not (dir_ / k).exists() or (dir_ / k).stat().st_size != v["mida"]]
                if falten: return self.sortida(409, {"ok": False, "error": "incompleta", "falten": falten})
                (dir_ / ".complet").write_text("1"); return self.sortida(200, {"ok": True})
            return self.sortida(400, {"ok": False, "error": "acció"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
