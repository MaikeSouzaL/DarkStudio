@echo off
rem ── Gera o executavel desktop do DarkStudio para Windows (dist\DarkStudio\) ──
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pyinstaller
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name DarkStudio ^
  --collect-all nicegui --collect-all webview --collect-all ctranslate2 ^
  --collect-all faster_whisper --collect-all onnxruntime --collect-all av ^
  --collect-all edge_tts --collect-all imageio_ffmpeg --collect-all tokenizers ^
  --collect-all dotenv --hidden-import google.genai ^
  app.py
echo.
echo Pronto: dist\DarkStudio\DarkStudio.exe  (distribua a pasta inteira ou gere um instalador com Inno Setup)
