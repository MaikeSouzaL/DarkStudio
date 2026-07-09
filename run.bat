@echo off
rem ── DarkStudio — cria o .venv na primeira execução e abre o app ──
rem Requer Python 3.11+ (3.10.0 tem bug que impede o empacotamento)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [DarkStudio] criando ambiente virtual...
    py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || py -3.13 -m venv .venv 2>nul || python -m venv .venv
    echo [DarkStudio] instalando dependencias no .venv (demora na 1a vez)...
    where nvidia-smi >nul 2>nul && (
        echo [DarkStudio] GPU NVIDIA detectada - instalando torch CUDA...
        ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q "torch==2.6.0+cu124" "torchaudio==2.6.0+cu124" "torchvision==0.21.0+cu124" --index-url https://download.pytorch.org/whl/cu124
    )
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --no-deps chatterbox-tts
    ".venv\Scripts\python.exe" -m pip uninstall -y -q gradio hf-gradio 2>nul
    ".venv\Scripts\python.exe" -m playwright install chromium 2>nul
)
".venv\Scripts\python.exe" app.py %*
