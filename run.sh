#!/usr/bin/env bash
# ── DarkStudio — cria o .venv na primeira execução e abre o app (Linux/macOS) ──
# Requer Python 3.11+ (3.10.0 tem bug que impede o empacotamento)
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "[DarkStudio] criando ambiente virtual..."
    PY=$(command -v python3.12 || command -v python3.11 || command -v python3.13 || command -v python3)
    "$PY" -m venv .venv
    echo "[DarkStudio] instalando dependências no .venv (demora na 1ª vez)..."
    ".venv/bin/python" -m pip install --disable-pip-version-check -q -r requirements.txt
    ".venv/bin/python" -m pip install --disable-pip-version-check -q --no-deps chatterbox-tts
    ".venv/bin/python" -m pip uninstall -y -q gradio hf-gradio 2>/dev/null || true
    # Linux: a janela nativa usa GTK/WebKit → sudo apt install gir1.2-webkit2-4.1 python3-gi
fi
exec ".venv/bin/python" app.py "$@"
