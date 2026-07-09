#!/usr/bin/env bash
# ── Gera o executável desktop do DarkStudio para Linux/macOS (dist/DarkStudio/) ──
# Rode NO sistema alvo: PyInstaller não faz build cruzado entre sistemas.
cd "$(dirname "$0")/.."
".venv/bin/python" -m pip install --disable-pip-version-check -q pyinstaller
".venv/bin/python" -m PyInstaller --noconfirm --clean --windowed --onedir --name DarkStudio \
  --collect-all nicegui --collect-all webview --collect-all ctranslate2 \
  --collect-all faster_whisper --collect-all onnxruntime --collect-all av \
  --collect-all edge_tts --collect-all imageio_ffmpeg --collect-all tokenizers \
  --collect-all dotenv --hidden-import google.genai \
  app.py
echo
echo "Pronto: dist/DarkStudio/DarkStudio  (no macOS use também: dist/DarkStudio.app)"
