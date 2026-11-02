"""El client Java de l'app (captura/app/.../Pujada.java) contra el servidor de referència (mateix protocol que pujada.php)."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "captura"))
import servidor_referencia as ref  # noqa: E402

ARREL = Path(__file__).resolve().parent.parent / "captura" / "app" / "src"
JAVAC = shutil.which("javac") or "/snap/android-studio/current/jbr/bin/javac"
JAVA = str(Path(shutil.which("javac") or JAVAC).parent / "java")
pytestmark = pytest.mark.skipif(not (Path(JAVAC).exists() or shutil.which("javac")), reason="sense JDK")


@pytest.fixture(scope="module")
def classes(tmp_path_factory):
    out = tmp_path_factory.mktemp("cls")
    subprocess.run([JAVAC, "--release", "11", "-d", str(out), str(ARREL / "cat/escena/captura/Pujada.java")], check=True)
    return out


def _sessio(base: Path, mida_video: int):
    d = base / "sessions" / "20261102_101530"
    d.mkdir(parents=True)
    (d / "video.mp4").write_bytes(os.urandom(mida_video))
    (d / "imu.csv").write_text("timestamp_ns,tipus,v0\n1,1,0.5\n")
    (d / "meta.json").write_text("{}")
    (d / "notes.txt").write_text("no s'ha de pujar")
    return d


def _puja(classes, srv, token, d):
    url = f"http://127.0.0.1:{srv.server_address[1]}/pujada.php"
    return subprocess.run([JAVA, "-cp", str(classes), "cat.escena.captura.Pujada", url, token, str(d)], capture_output=True, text=True)


def test_puja_una_sessio_sencera_amb_diversos_trossos(classes, tmp_path):
    srv = ref.crea(tmp_path / "dades", "secret")
    d = _sessio(tmp_path / "mobil", 9 * 1024 * 1024 + 123)          # 3 trossos de 4 MB
    r = _puja(classes, srv, "secret", d)
    srv.shutdown()
    assert r.returncode == 0, r.stdout + r.stderr
    dest = tmp_path / "dades" / d.name
    assert hashlib.sha256((dest / "video.mp4").read_bytes()).hexdigest() == hashlib.sha256((d / "video.mp4").read_bytes()).hexdigest()
    assert (dest / ".complet").exists() and not (dest / "notes.txt").exists()
    assert not list(dest.glob("*.part"))


def test_reprèn_on_s_havia_quedat(classes, tmp_path):
    srv = ref.crea(tmp_path / "dades", "secret")
    d = _sessio(tmp_path / "mobil", 9 * 1024 * 1024)
    video = (d / "video.mp4").read_bytes()
    primer = _puja(classes, srv, "secret", d)                          # puja tot i després simulem una pujada tallada
    assert primer.returncode == 0, primer.stdout + primer.stderr
    dest = tmp_path / "dades" / d.name
    (dest / "video.mp4").unlink(); (dest / ".complet").unlink()
    (dest / "video.mp4.part").write_bytes(video[: 4 * 1024 * 1024])    # el servidor només en té el primer tros
    r = _puja(classes, srv, "secret", d)
    srv.shutdown()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "enviats " + str(len(video) - 4 * 1024 * 1024) in r.stdout.replace("\n", " ") or "enviats" in r.stdout
    assert (dest / "video.mp4").read_bytes() == video


def test_token_incorrecte_es_rebutja(classes, tmp_path):
    srv = ref.crea(tmp_path / "dades", "secret")
    d = _sessio(tmp_path / "mobil", 1000)
    r = _puja(classes, srv, "equivocat", d)
    srv.shutdown()
    assert r.returncode != 0 and "403" in (r.stdout + r.stderr)
    assert not (tmp_path / "dades" / d.name / "video.mp4").exists()


def test_contingut_modificat_sense_canviar_el_nom_es_torna_a_pujar(classes, tmp_path):
    srv = ref.crea(tmp_path / "dades", "secret")
    d = _sessio(tmp_path / "mobil", 5000)
    assert _puja(classes, srv, "secret", d).returncode == 0
    (d / "video.mp4").write_bytes(os.urandom(5000))
    r = _puja(classes, srv, "secret", d)
    srv.shutdown()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "dades" / d.name / "video.mp4").read_bytes() == (d / "video.mp4").read_bytes()
