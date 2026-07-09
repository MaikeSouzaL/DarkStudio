"""Configuração global do DarkStudio.

Chaves de API ficam no .env (GEMINI_API_KEY); o resto em config.json.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT_DIR / "projects"
CONFIG_FILE = ROOT_DIR / "config.json"
ENV_FILE = ROOT_DIR / ".env"

# Onde obter cada chave/token (mostrado como link na tela de Configurações)
PROVIDER_LINKS = {
    "GEMINI_API_KEY": "https://aistudio.google.com/apikey",
    "DEEPSEEK_API_KEY": "https://platform.deepseek.com/api_keys",
    "HF_TOKEN": "https://huggingface.co/settings/tokens",
    "TOGETHER_API_KEY": "https://api.together.ai/settings/api-keys",
    "ELEVENLABS_API_KEY": "https://elevenlabs.io/app/settings/api-keys",
    "OPENAI_API_KEY": "https://platform.openai.com/api-keys",
    "HIGGSFIELD_API_KEY": "https://cloud.higgsfield.ai/",
    "VERTEX": "https://console.cloud.google.com/",
}

# Formatos de vídeo suportados — atravessam todo o pipeline
FORMATS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),   # YouTube padrão
    "9:16": (1080, 1920),   # Shorts / TikTok / Reels
    "1:1": (1080, 1080),    # feed quadrado
}

load_dotenv(ENV_FILE)


@dataclass
class Settings:
    # Modelos Google (ids atuais em jul/2026; ajuste em Configurações se mudarem)
    text_model: str = "gemini-2.5-flash"
    image_model: str = "gemini-3.1-flash-image"
    veo_model: str = "veo-3.1-fast-generate-preview"
    tts_model: str = "gemini-2.5-flash-preview-tts"
    elevenlabs_model: str = "eleven_multilingual_v2"
    # LLM reserva quando o Gemini esgota créditos/cota (OpenAI-compatível)
    deepseek_model: str = "deepseek-chat"
    # provedores de imagem grátis (com token/chave gratuitos)
    hf_image_model: str = "black-forest-labs/FLUX.1-schnell"
    together_image_model: str = "black-forest-labs/FLUX.1-schnell-Free"
    # Higgsfield (pago) — agrega Sora/Kling/Veo/Seedance; endpoint configurável
    higgsfield_base: str = "https://platform.higgsfield.ai"
    higgsfield_image_model: str = "higgsfield-soul"
    higgsfield_video_model: str = "veo-3.1"
    # Geração local na GPU (diffusers) e SD WebUI (A1111/Forge)
    local_image_model: str = "sdxl"      # sdxl | zimage | sd15 | flux-schnell
    sdwebui_url: str = "http://127.0.0.1:7860"
    ltx_model: str = "Lightricks/LTX-Video"
    # image-to-video por API (grátis/limitado)
    hf_video_model: str = "Wan-AI/Wan2.2-I2V-A14B"   # HuggingFace i2v (token grátis)
    pollinations_video_model: str = "wan"            # wan | seedance | veo (Pollen credits)   # repo em formato diffusers
    # Vertex AI (OAuth via gcloud ADC) — alternativa à chave de API
    use_vertex: bool = False
    vertex_project: str = ""
    vertex_location: str = "us-central1"
    # Whisper
    whisper_model: str = "small"          # tiny | base | small | medium | large-v3
    whisper_compute: str = "int8"         # int8 roda bem em CPU
    # Render
    fps: int = 30
    video_width: int = 1920
    video_height: int = 1080
    # Estimativas de custo (US$) usadas nos avisos antes de gerar em lote
    image_cost_usd: float = 0.04   # por imagem Nano Banana
    veo_cost_usd: float = 1.20     # por clipe Veo (~8s fast)
    # Fallbacks tentados quando o modelo configurado não existe na conta
    image_model_fallbacks: list = field(default_factory=lambda: [
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    ])
    text_model_fallbacks: list = field(default_factory=lambda: [
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
        "gemini-2.0-flash",
    ])
    tts_model_fallbacks: list = field(default_factory=lambda: [
        "gemini-2.5-flash-preview-tts",
        "gemini-3.1-flash-tts-preview",
        "gemini-2.5-pro-preview-tts",
    ])

    @property
    def gemini_api_key(self) -> str:
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""

    @property
    def elevenlabs_api_key(self) -> str:
        return os.environ.get("ELEVENLABS_API_KEY") or ""

    @property
    def openai_api_key(self) -> str:
        return os.environ.get("OPENAI_API_KEY") or ""

    @property
    def deepseek_api_key(self) -> str:
        return os.environ.get("DEEPSEEK_API_KEY") or ""

    @property
    def hf_token(self) -> str:
        return os.environ.get("HF_TOKEN") or ""

    @property
    def together_api_key(self) -> str:
        return os.environ.get("TOGETHER_API_KEY") or ""

    @property
    def higgsfield_api_key(self) -> str:
        return os.environ.get("HIGGSFIELD_API_KEY") or ""

    @property
    def higgsfield_secret(self) -> str:
        return os.environ.get("HIGGSFIELD_SECRET") or ""

    @property
    def gemini_ready(self) -> bool:
        """Gemini disponível por chave OU por Vertex (OAuth/gcloud)."""
        return bool(self.gemini_api_key) or bool(self.use_vertex and self.vertex_project)

    @property
    def ffmpeg(self) -> str:
        found = shutil.which("ffmpeg")
        if found:
            return found
        try:  # binário embutido — permite instalar o app sem ffmpeg no sistema
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return "ffmpeg"

    @property
    def ffprobe(self) -> str:
        return shutil.which("ffprobe") or ""

    # ------------------------------------------------------------------
    def save(self) -> None:
        data = asdict(self)
        CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(s, k) and not isinstance(getattr(type(s), k, None), property):
                        setattr(s, k, v)
            except Exception:
                pass
        return s

    def set_env_key(self, name: str, value: str) -> None:
        """Grava uma chave no .env (e no processo atual)."""
        value = (value or "").strip()
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)
        lines = []
        if ENV_FILE.exists():
            lines = [l for l in ENV_FILE.read_text(encoding="utf-8").splitlines()
                     if not l.startswith(f"{name}=")]
        if value:
            lines.append(f"{name}={value}")
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def set_api_key(self, key: str) -> None:
        self.set_env_key("GEMINI_API_KEY", key)


def genai_client(s: "Settings"):
    """Cliente Gemini: chave de API ou Vertex AI (OAuth via `gcloud auth
    application-default login`). Vertex dá acesso a Gemini/Imagen/Veo cobrando
    no projeto Google Cloud."""
    from google import genai
    if s.use_vertex and s.vertex_project:
        return genai.Client(vertexai=True, project=s.vertex_project,
                            location=s.vertex_location or "us-central1")
    return genai.Client(api_key=s.gemini_api_key)


settings = Settings.load()
PROJECTS_DIR.mkdir(exist_ok=True)
