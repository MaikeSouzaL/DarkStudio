"""Animação das cenas.

  kenburns -> movimento de câmera local via FFmpeg zoompan (grátis);
              a direção/intensidade vem do plano de movimento da IA.
  veo      -> image-to-video real com Veo 3.1 pela API Gemini (pago).

O plano de movimento é gerado por LLM (frase + imagem) ou por heurística.
"""
from __future__ import annotations

import time
from pathlib import Path

from .config import Settings
from .llm import LLM

ANIM_PROVIDERS = {
    "kenburns": "Ken Burns inteligente (local, grátis)",
    "ltx": "🖥️ LTX-Video na sua GPU (grátis, offline)",
    "hf_video": "Hugging Face i2v (grátis com token, limitado)",
    "pollinations_video": "Pollinations vídeo (créditos)",
    "veo": "Google Veo 3.1 (vídeo real, pago)",
    "higgsfield": "Higgsfield (Sora/Kling/Veo, pago)",
}

# rotação usada quando não há LLM — variedade visual garantida
_HEURISTIC = ["zoom_in", "pan_right", "zoom_out", "diag_dr", "zoom_pan_right",
              "pan_left", "pulse", "pan_up", "diag_ur", "handheld"]


def plan_motions(llm: LLM, timed_sentences: list[dict], scene_prompts: list[str],
                 image_files: list[str | None], project_dir: Path,
                 use_ai: bool = True, progress=None) -> list[dict]:
    plans: list[dict] = []
    n = len(timed_sentences)
    for i, sent in enumerate(timed_sentences):
        scene = scene_prompts[i] if i < len(scene_prompts) else sent["text"]
        img = None
        if i < len(image_files) and image_files[i]:
            p = project_dir / image_files[i]
            img = str(p) if p.exists() else None
        if use_ai and llm.available:
            plan = llm.motion_plan(sent["text"], scene, image_path=img)
        else:
            plan = {"camera": _HEURISTIC[i % len(_HEURISTIC)],
                    "intensity": 0.10 + 0.02 * (i % 3),
                    "veo_prompt": f"Slow cinematic camera move, subtle ambient motion. {scene[:300]}"}
        plan["i"] = i
        plans.append(plan)
        if progress:
            progress(i + 1, n)
    return plans


def render_veo_clip(image_path: Path, veo_prompt: str, out_path: Path,
                    settings: Settings, timeout: int = 600) -> Path:
    """Gera clipe de vídeo a partir da imagem com Veo 3.1 (operação longa)."""
    from google.genai import types

    from .config import genai_client

    if not settings.gemini_ready:
        raise RuntimeError("Configure a GEMINI_API_KEY (ou Vertex) para usar o Veo.")
    client = genai_client(settings)

    # carrega a imagem de forma compatível com versões do SDK
    try:
        image = types.Image.from_file(location=str(image_path))
    except Exception:
        image = types.Image(image_bytes=image_path.read_bytes(), mime_type="image/jpeg")

    operation = client.models.generate_videos(
        model=settings.veo_model,
        prompt=veo_prompt,
        image=image,
    )
    start = time.time()
    while not operation.done:
        if time.time() - start > timeout:
            raise TimeoutError("Veo demorou demais — tente novamente")
        time.sleep(10)
        operation = client.operations.get(operation)

    if getattr(operation, "error", None):
        raise RuntimeError(f"Veo falhou: {operation.error}")
    videos = operation.response.generated_videos
    if not videos:
        raise RuntimeError("Veo não retornou vídeo (prompt pode ter sido bloqueado)")
    video = videos[0]
    client.files.download(file=video.video)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    video.video.save(str(out_path))
    return out_path


_LTX_PIPE: dict = {}


def render_ltx_clip(image_path: Path, prompt: str, out_path: Path,
                    settings: Settings, seconds: float = 4.0) -> Path:
    """Image-to-video LOCAL com LTX-Video (roda em 6GB com offload).

    Lento em GPUs modestas (~2-5 min/clipe na RTX 2060), mas 100% grátis e
    offline. Resolução 704×416 (16:9) reescalada no render final.
    """
    import torch
    from diffusers import LTXImageToVideoPipeline
    from diffusers.utils import export_to_video, load_image

    if "pipe" not in _LTX_PIPE:
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        pipe = LTXImageToVideoPipeline.from_pretrained(settings.ltx_model,
                                                       torch_dtype=dtype)
        if torch.cuda.is_available():
            pipe.enable_model_cpu_offload()
            try:
                pipe.vae.enable_tiling()
            except Exception:
                pass
        _LTX_PIPE["pipe"] = pipe
    pipe = _LTX_PIPE["pipe"]

    image = load_image(str(image_path))
    w, h = (704, 416) if image.width >= image.height else (416, 704)
    frames = int(min(max(seconds, 2.0), 6.0) * 24)
    frames = (frames // 8) * 8 + 1          # LTX exige 8n+1 quadros
    result = pipe(image=image, prompt=prompt[:800],
                  negative_prompt="worst quality, jitter, distorted, watermark",
                  width=w, height=h, num_frames=frames,
                  num_inference_steps=30).frames[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    export_to_video(result, str(out_path), fps=24)
    return out_path


def render_hf_video_clip(image_path: Path, prompt: str, out_path: Path,
                         settings: Settings) -> Path:
    """Image-to-video via Hugging Face Inference (grátis com HF_TOKEN, com limites).

    Modelos i2v são grandes; podem estar em cold start (espera) ou fora do tier
    grátis. Em falha, o pipeline registra e segue (a cena fica em Ken Burns)."""
    if not settings.hf_token:
        raise RuntimeError("Configure o HF_TOKEN nas Configurações (huggingface.co).")
    from huggingface_hub import InferenceClient

    client = InferenceClient(token=settings.hf_token)
    data = client.image_to_video(str(image_path), prompt=prompt[:500],
                                 model=settings.hf_video_model)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data if isinstance(data, (bytes, bytearray)) else bytes(data))
    return out_path


def render_pollinations_video_clip(image_path: Path, prompt: str, out_path: Path,
                                   settings: Settings) -> Path:
    """Image-to-video via Pollinations (gen.pollinations.ai). Usa créditos Pollen;
    pode ter tier grátis limitado. Endpoint de keyframe: imagem inicial → vídeo."""
    import base64

    import httpx

    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    body = {"model": settings.pollinations_video_model, "prompt": prompt[:800],
            "image": f"data:image/jpeg;base64,{img_b64}", "type": "video"}
    with httpx.Client(timeout=600, follow_redirects=True) as client:
        r = client.post("https://gen.pollinations.ai/video", json=body)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Pollinations vídeo {r.status_code}: {r.text[:160]}")
        ct = r.headers.get("content-type", "")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if ct.startswith("video") or ct == "application/octet-stream":
            out_path.write_bytes(r.content)
        else:  # resposta JSON com URL
            url = (r.json().get("url") or r.json().get("output"))
            if not url:
                raise RuntimeError("Pollinations não retornou vídeo")
            vid = client.get(url)
            vid.raise_for_status()
            out_path.write_bytes(vid.content)
    return out_path


def render_higgsfield_clip(image_path: Path, prompt: str, out_path: Path,
                           settings: Settings) -> Path:
    """Image-to-video via Higgsfield (agrega Sora/Kling/Veo). Endpoint configurável."""
    import base64

    import httpx

    from .imagen import _higgsfield_headers, _higgsfield_poll

    if not settings.higgsfield_api_key:
        raise RuntimeError("Configure a HIGGSFIELD_API_KEY para usar o Higgsfield.")
    base = settings.higgsfield_base.rstrip("/")
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    body = {"model": settings.higgsfield_video_model, "prompt": prompt[:1500],
            "image": f"data:image/jpeg;base64,{img_b64}", "duration": 5}
    with httpx.Client(timeout=600, follow_redirects=True) as client:
        r = client.post(f"{base}/v1/image2video", headers=_higgsfield_headers(settings),
                        json=body)
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"Higgsfield {r.status_code}: {r.text[:200]}")
        url = _higgsfield_poll(client, base, r.json(), settings)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
    return out_path
