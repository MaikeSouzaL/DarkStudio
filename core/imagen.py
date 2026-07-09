"""Geração de imagens — provedores plugáveis.

  gemini       -> Nano Banana via API oficial (google-genai), requer GEMINI_API_KEY
  pollinations -> API pública gratuita (sem chave) — útil para testar/fallback
  mock         -> imagem local (gradiente + cena) — testes offline

Toda imagem é normalizada para 1920x1080 (16:9) independente do provedor.
"""
from __future__ import annotations

import io
import textwrap
import time
import urllib.parse
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter

from .config import Settings

PROVIDERS = {
    "gemini": "Google Gemini (Nano Banana) — chave ou Vertex",
    "local": "🖥️ Local na sua GPU (diffusers) — grátis, offline",
    "sdwebui": "🖥️ SD WebUI local (A1111/Forge) — seus modelos",
    "pollinations": "Pollinations.ai — grátis, sem chave",
    "hf": "Hugging Face FLUX — grátis com token",
    "together": "Together AI FLUX — grátis com chave",
    "higgsfield": "Higgsfield (Soul) — pago, cinematográfico",
    "mock": "Teste local (sem IA)",
}

# Modelos locais curados para GPUs de 6-12GB (chave → repo HF, rótulo, config)
LOCAL_IMAGE_MODELS = {
    "sdxl": ("stabilityai/stable-diffusion-xl-base-1.0",
             "SDXL — flexível, comercial OK (openrail++), ~45s em 6GB"),
    "zimage": ("Tongyi-MAI/Z-Image-Turbo",
               "Z-Image-Turbo — TOP 2026, Apache 2.0, 8 passos (8GB+ ideal)"),
    "sd15": ("stable-diffusion-v1-5/stable-diffusion-v1-5",
             "SD 1.5 — leve e rápido (~10s), qualidade menor"),
    "flux-schnell": ("black-forest-labs/FLUX.1-schnell",
                     "FLUX.1 schnell — Apache 2.0, LENTO em 6GB (2-5 min)"),
}
_LOCAL_STEPS = {"sdxl": (28, 6.0), "zimage": (9, 3.0), "sd15": (28, 7.0),
                "flux-schnell": (4, 0.0)}
_LOCAL_BASE = {"sdxl": 1024, "zimage": 1024, "sd15": 512, "flux-schnell": 1024}
_NEGATIVE = ("text, watermark, logo, caption, low quality, blurry, deformed, "
             "bad anatomy, extra fingers, jpeg artifacts")


class ImagenError(RuntimeError):
    pass


class _LocalCancelled(RuntimeError):
    """Interrompe a difusão local quando o usuário cancela."""


def normalize_frame(data: bytes, out_path: Path, w: int = 1920, h: int = 1080) -> Path:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    img = img.crop((left, top, left + w, top + h))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=92)
    return out_path


# ----------------------------------------------------------------- gemini
def _gemini_generate(prompt: str, settings: Settings, aspect: str = "16:9",
                     ref_images: list | None = None) -> bytes:
    from google import genai
    from google.genai import types

    if not settings.gemini_ready:
        raise ImagenError("Configure a GEMINI_API_KEY (ou Vertex) em Configurações — "
                          "ou troque para um provedor grátis (Pollinations/HF/Together).")
    from .config import genai_client
    client = genai_client(settings)

    # imagens de referência (consistência de personagem) entram antes do prompt
    contents: list = []
    for ref in (ref_images or [])[:3]:
        try:
            contents.append(types.Part.from_bytes(data=Path(ref).read_bytes(),
                                                  mime_type="image/jpeg"))
        except Exception:
            pass
    if contents:
        prompt += ("\nUse the provided reference image(s) strictly for character "
                   "appearance: keep the exact same face, hair, body and clothing.")
    contents.append(prompt)

    models = [settings.image_model] + [m for m in settings.image_model_fallbacks
                                       if m != settings.image_model]
    last_err: Exception | None = None
    for model in models:
        # tenta com aspect ratio nativo; se a versão do SDK não suportar, sem ele
        configs = []
        try:
            configs.append(types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect),
            ))
        except Exception:
            pass
        configs.append(types.GenerateContentConfig(response_modalities=["IMAGE"]))

        for config in configs:
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=config)
                for cand in (resp.candidates or []):
                    content = getattr(cand, "content", None)
                    for part in (getattr(content, "parts", None) or []):
                        inline = getattr(part, "inline_data", None)
                        if inline is not None and getattr(inline, "data", None):
                            data = inline.data
                            return data if isinstance(data, (bytes, bytearray)) else bytes(data)
                last_err = ImagenError("resposta sem imagem (prompt pode ter sido bloqueado)")
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                if "not found" in msg or "404" in msg:
                    break  # modelo não existe nesta conta → próximo modelo
                if "image_config" in msg or "aspect" in msg:
                    continue  # tenta config sem aspect ratio
                raise ImagenError(f"Gemini: {e}") from e
    raise ImagenError(f"Gemini não retornou imagem: {last_err}")


# ----------------------------------------------------------- pollinations
_POLL_SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}


def _pollinations_generate(prompt: str, settings: Settings, aspect: str = "16:9",
                           ref_images: list | None = None) -> bytes:
    w, h = _POLL_SIZES.get(aspect, (1280, 720))
    url = ("https://image.pollinations.ai/prompt/"
           + urllib.parse.quote(prompt[:1500])
           + f"?width={w}&height={h}&nologo=true&model=flux&seed=" + str(int(time.time() * 1000) % 999999))
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image"):
            raise ImagenError("Pollinations não retornou imagem")
        return r.content


# ------------------------------------------------- hugging face (grátis)
def _hf_generate(prompt: str, settings: Settings, aspect: str = "16:9",
                 ref_images: list | None = None) -> bytes:
    if not settings.hf_token:
        raise ImagenError("Crie um token grátis em huggingface.co/settings/tokens "
                          "e salve como HF_TOKEN nas Configurações.")
    w, h = _POLL_SIZES.get(aspect, (1280, 720))
    url = f"https://api-inference.huggingface.co/models/{settings.hf_image_model}"
    with httpx.Client(timeout=300) as client:
        for attempt in range(4):
            r = client.post(url,
                            headers={"Authorization": f"Bearer {settings.hf_token}",
                                     "x-wait-for-model": "true"},
                            json={"inputs": prompt[:1800],
                                  "parameters": {"width": w, "height": h}})
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                return r.content
            if r.status_code == 503:  # modelo carregando no serverless
                time.sleep(12)
                continue
            raise ImagenError(f"HuggingFace {r.status_code}: {r.text[:200]}")
    raise ImagenError("HuggingFace: modelo não carregou a tempo — tente de novo")


# --------------------------------------------------- together ai (grátis)
def _together_generate(prompt: str, settings: Settings, aspect: str = "16:9",
                       ref_images: list | None = None) -> bytes:
    import base64
    if not settings.together_api_key:
        raise ImagenError("Crie uma chave grátis em api.together.ai "
                          "e salve como TOGETHER_API_KEY nas Configurações.")
    w, h = _POLL_SIZES.get(aspect, (1280, 720))
    with httpx.Client(timeout=180) as client:
        r = client.post("https://api.together.xyz/v1/images/generations",
                        headers={"Authorization": f"Bearer {settings.together_api_key}"},
                        json={"model": settings.together_image_model,
                              "prompt": prompt[:1800], "width": w, "height": h,
                              "steps": 4, "n": 1, "response_format": "b64_json"})
        if r.status_code != 200:
            raise ImagenError(f"Together {r.status_code}: {r.text[:200]}")
        data = r.json().get("data") or []
        if not data:
            raise ImagenError("Together não retornou imagem")
        return base64.b64decode(data[0]["b64_json"])


# ------------------------------------------- local (diffusers, sua GPU)
_LOCAL_PIPES: dict = {}


def _local_dims(model_key: str, aspect: str) -> tuple[int, int]:
    base = _LOCAL_BASE.get(model_key, 1024)
    ratios = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1)}
    rw, rh = ratios.get(aspect, (16, 9))
    if rw >= rh:
        w, h = base, int(base * rh / rw)
    else:
        w, h = int(base * rw / rh), base
    return (w // 64) * 64 or 64, (h // 64) * 64 or 64


def _local_generate(prompt: str, settings: Settings, aspect: str = "16:9",
                    ref_images: list | None = None, cancel=None) -> bytes:
    import torch
    from diffusers import AutoPipelineForText2Image

    key = settings.local_image_model
    repo = LOCAL_IMAGE_MODELS.get(key, LOCAL_IMAGE_MODELS["sdxl"])[0]
    if key not in _LOCAL_PIPES:
        has_gpu = torch.cuda.is_available()
        dtype = torch.float16 if has_gpu else torch.float32
        try:  # variant fp16 = metade do download quando o repo oferece
            pipe = AutoPipelineForText2Image.from_pretrained(
                repo, torch_dtype=dtype, use_safetensors=True, variant="fp16")
        except Exception:
            pipe = AutoPipelineForText2Image.from_pretrained(
                repo, torch_dtype=dtype, use_safetensors=True)
        if has_gpu:
            pipe.enable_model_cpu_offload()   # cabe em 6GB (RTX 2060)
            try:
                pipe.enable_vae_tiling()
            except Exception:
                pass
        _LOCAL_PIPES.clear()                  # 1 modelo por vez na VRAM
        _LOCAL_PIPES[key] = pipe
    pipe = _LOCAL_PIPES[key]
    steps, guidance = _LOCAL_STEPS.get(key, (25, 6.0))
    w, h = _local_dims(key, aspect)
    kwargs = {"prompt": prompt[:1500], "num_inference_steps": steps,
              "guidance_scale": guidance, "width": w, "height": h}

    # callback que ABORTA a difusão no meio se o usuário cancelar (parada rápida)
    def _step_cb(pipe_, step, timestep, cbk):
        if cancel and cancel():
            raise _LocalCancelled()
        return cbk

    if cancel is not None:
        kwargs["callback_on_step_end"] = _step_cb
    try:
        img = pipe(**kwargs, negative_prompt=_NEGATIVE).images[0]
    except TypeError:  # pipelines sem negative_prompt e/ou sem callback (ex.: FLUX)
        kwargs.pop("callback_on_step_end", None)
        img = pipe(**kwargs).images[0]
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# --------------------------------- SD WebUI local (A1111 / Forge / SD.Next)
def _sdwebui_generate(prompt: str, settings: Settings, aspect: str = "16:9",
                      ref_images: list | None = None) -> bytes:
    import base64
    w, h = _local_dims("sdxl", aspect)
    url = settings.sdwebui_url.rstrip("/")
    try:
        with httpx.Client(timeout=600) as client:
            r = client.post(f"{url}/sdapi/v1/txt2img",
                            json={"prompt": prompt[:1500],
                                  "negative_prompt": _NEGATIVE,
                                  "steps": 26, "width": w, "height": h,
                                  "sampler_name": "DPM++ 2M",
                                  "cfg_scale": 6.0})
    except httpx.ConnectError as e:
        raise ImagenError(f"SD WebUI não está rodando em {url} — abra o "
                          "A1111/Forge com a flag --api") from e
    if r.status_code != 200:
        raise ImagenError(f"SD WebUI {r.status_code}: {r.text[:200]}")
    images = r.json().get("images") or []
    if not images:
        raise ImagenError("SD WebUI não retornou imagem")
    return base64.b64decode(images[0].split(",", 1)[-1])


# -------------------------------------------------- higgsfield (pago)
def _higgsfield_headers(settings: Settings) -> dict:
    h = {"Authorization": f"Bearer {settings.higgsfield_api_key}",
         "Content-Type": "application/json"}
    if settings.higgsfield_secret:  # algumas contas exigem key+secret
        h["hf-api-key"] = settings.higgsfield_api_key
        h["hf-secret"] = settings.higgsfield_secret
    return h


def _higgsfield_poll(client, base: str, job: dict, settings: Settings) -> str:
    """Aguarda o job e devolve a URL do resultado (imagem ou vídeo)."""
    job_id = job.get("id") or job.get("job_id") or job.get("jobId")
    # resposta já traz a URL?
    for k in ("url", "result_url", "output_url", "image_url", "video_url"):
        if job.get(k):
            return job[k]
    if not job_id:
        raise ImagenError("Higgsfield: resposta sem id de job (verifique o endpoint)")
    for _ in range(90):
        time.sleep(3)
        r = client.get(f"{base}/v1/jobs/{job_id}", headers=_higgsfield_headers(settings))
        if r.status_code != 200:
            continue
        data = r.json()
        status = (data.get("status") or "").lower()
        for k in ("url", "result_url", "output_url", "image_url", "video_url"):
            nested = data.get("results") or data.get("output") or {}
            if data.get(k):
                return data[k]
            if isinstance(nested, dict) and nested.get(k):
                return nested[k]
            if isinstance(nested, list) and nested and isinstance(nested[0], dict):
                for kk in ("url", "image_url", "video_url"):
                    if nested[0].get(kk):
                        return nested[0][kk]
        if status in ("failed", "error", "canceled"):
            raise ImagenError(f"Higgsfield falhou: {data.get('error', status)}")
    raise ImagenError("Higgsfield: tempo esgotado aguardando o resultado")


def _higgsfield_generate(prompt: str, settings: Settings, aspect: str = "16:9",
                         ref_images: list | None = None) -> bytes:
    if not settings.higgsfield_api_key:
        raise ImagenError("Configure a HIGGSFIELD_API_KEY em Configurações "
                          "(cloud.higgsfield.ai).")
    base = settings.higgsfield_base.rstrip("/")
    body = {"model": settings.higgsfield_image_model, "prompt": prompt[:1800],
            "aspect_ratio": aspect, "width": _POLL_SIZES.get(aspect, (1280, 720))[0],
            "height": _POLL_SIZES.get(aspect, (1280, 720))[1]}
    with httpx.Client(timeout=300, follow_redirects=True) as client:
        r = client.post(f"{base}/v1/image/generate", headers=_higgsfield_headers(settings),
                        json=body)
        if r.status_code not in (200, 201, 202):
            raise ImagenError(f"Higgsfield {r.status_code}: {r.text[:200]}")
        url = _higgsfield_poll(client, base, r.json(), settings)
        img = client.get(url)
        img.raise_for_status()
        return img.content


# ------------------------------------------------------------------ mock
_MOCK_PALETTES = [((30, 30, 60), (120, 60, 160)), ((10, 40, 60), (30, 130, 160)),
                  ((60, 20, 30), (180, 80, 60)), ((20, 50, 30), (90, 160, 90))]


def _mock_generate(prompt: str, settings: Settings, aspect: str = "16:9",
                   ref_images: list | None = None) -> bytes:
    pal = _MOCK_PALETTES[abs(hash(prompt)) % len(_MOCK_PALETTES)]
    w, h = _POLL_SIZES.get(aspect, (1280, 720))
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(pal[0], pal[1])))
    d.ellipse([w * 0.6, h * 0.1, w * 0.95, h * 0.6], fill=tuple(min(255, c + 40) for c in pal[1]))
    img = img.filter(ImageFilter.GaussianBlur(2))
    d = ImageDraw.Draw(img)
    wrapped = textwrap.fill(prompt[:220], width=48)
    d.multiline_text((w // 2, h // 2), wrapped, fill=(255, 255, 255), anchor="mm", align="center")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


# ------------------------------------------------------------------ API
_GENERATORS = {
    "gemini": _gemini_generate,
    "local": _local_generate,
    "sdwebui": _sdwebui_generate,
    "pollinations": _pollinations_generate,
    "hf": _hf_generate,
    "together": _together_generate,
    "higgsfield": _higgsfield_generate,
    "mock": _mock_generate,
}


def generate_image(prompt: str, out_path: Path, settings: Settings,
                   provider: str = "gemini", retries: int = 3,
                   dims: tuple[int, int] = (1920, 1080), aspect: str = "16:9",
                   ref_images: list | None = None, cancel=None) -> Path:
    gen = _GENERATORS.get(provider)
    if not gen:
        raise ImagenError(f"Provedor desconhecido: {provider}")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            if provider == "local":  # só o local aceita interrupção no meio
                data = gen(prompt, settings, aspect=aspect, ref_images=ref_images,
                           cancel=cancel)
            else:
                data = gen(prompt, settings, aspect=aspect, ref_images=ref_images)
            return normalize_frame(data, out_path, dims[0], dims[1])
        except _LocalCancelled:
            raise                       # cancelamento não é erro para retry
        except ImagenError as e:
            last = e
            if "GEMINI_API_KEY" in str(e):
                raise
            time.sleep(2.0 * (attempt + 1))
        except Exception as e:
            last = e
            time.sleep(2.0 * (attempt + 1))
    raise ImagenError(f"Falha ao gerar imagem após {retries} tentativas: {last}")
