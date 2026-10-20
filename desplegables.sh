#!/usr/bin/env bash
# Arrenca l'app Desplegables i obre el navegador.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

if [ ! -x .venv/bin/streamlit ]; then
    echo "Creant entorn virtual..."
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || {
        read -rp "Error d'instal·lació. Prem Intro per tancar."; exit 1; }
fi

.venv/bin/streamlit run app.py --server.address localhost --server.port 8501
read -rp "App aturada. Prem Intro per tancar."
