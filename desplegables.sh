#!/usr/bin/env bash
# Comprova entorn i codi, i arrenca l'app Desplegables.
# Opcions: --tests  executa també la suite de proves (~90 s).
cd "$(dirname "$(readlink -f "$0")")" || exit 1

atura() { echo "$1"; read -rp "Prem Intro per tancar."; exit 1; }

# 1. Entorn virtual i dependències (només si requirements.txt ha canviat)
[ -x .venv/bin/python ] || { echo "Creant entorn virtual..."; python3 -m venv .venv || atura "Error creant l'entorn."; }
segell=.venv/.requirements.sha
if [ "$(sha256sum requirements.txt | cut -d' ' -f1)" != "$(cat "$segell" 2>/dev/null)" ] || [ ! -x .venv/bin/streamlit ]; then
    echo "Instal·lant dependències..."
    .venv/bin/pip install -q -r requirements.txt || atura "Error d'instal·lació."
    sha256sum requirements.txt | cut -d' ' -f1 > "$segell"
fi

# 2. Sintaxi de tot el codi
echo "Comprovant codi..."
.venv/bin/python -m compileall -q . -x '\.venv|__pycache__' >/dev/null || atura "Error de sintaxi al codi."

# 3. Executa l'app sense navegador (detecta imports trencats i errors a la portada)
.venv/bin/python - <<'PY' 2>&1 | grep -v "ScriptRunContext" | grep . && atura "Error executant app.py."
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=120).run()
for e in at.exception:
    print("Error:", e.value)
PY

# 4. Proves (opcional)
if [ "$1" = "--tests" ]; then
    .venv/bin/python -m pytest -q -x || atura "Les proves han fallat."
fi

# 5. Port ocupat per una instància anterior d'aquesta app: la reinicia (carrega el codi nou)
pid=$(ss -ltnp 2>/dev/null | sed -n 's/.*127\.0\.0\.1:8501 .*pid=\([0-9]*\).*/\1/p' | head -1)
if [ -n "$pid" ]; then
    if tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "$PWD/.venv/bin/python.*streamlit"; then
        echo "Reiniciant instància anterior (pid $pid)..."
        kill "$pid"; sleep 1
    else
        atura "El port 8501 l'usa un altre programa (pid $pid)."
    fi
fi

.venv/bin/streamlit run app.py --server.address localhost --server.port 8501
read -rp "App aturada. Prem Intro per tancar."
