"""Pré-download dos modelos locais — deixa tudo pronto no software.

Baixa (uma única vez, para o cache do Hugging Face) tudo que a geração local
usa, para que NENHUMA etapa espere download na hora de produzir:

  • modelo local de imagens configurado (SDXL por padrão)
  • LTX-Video (imagem→vídeo local)
  • Whisper configurado (ex.: large-v3)
  • modelos do Qwen3-TTS (voz + clonagem), se ainda não estiverem no cache

Usado pelo botão "Baixar modelos locais agora" nas Configurações.
"""
from __future__ import annotations

import gc

from .config import Settings


def _free():
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def download_all(settings: Settings, progress=None, include_video: bool = True) -> list[str]:
    """Baixa/valida todos os modelos locais. Retorna lista do que ficou pronto."""
    def p(msg: str):
        if progress:
            progress(msg)

    done: list[str] = []

    # 1) modelo local de imagens (carrega o pipeline = baixa exatamente o necessário)
    try:
        from .imagen import LOCAL_IMAGE_MODELS, _LOCAL_PIPES, _local_generate  # noqa: F401
        import torch
        from diffusers import AutoPipelineForText2Image
        key = settings.local_image_model
        repo = LOCAL_IMAGE_MODELS.get(key, LOCAL_IMAGE_MODELS["sdxl"])[0]
        p(f"Baixando modelo de imagens ({key}: {repo})…")
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        try:
            pipe = AutoPipelineForText2Image.from_pretrained(
                repo, torch_dtype=dtype, use_safetensors=True, variant="fp16")
        except Exception:
            pipe = AutoPipelineForText2Image.from_pretrained(
                repo, torch_dtype=dtype, use_safetensors=True)
        del pipe
        _free()
        done.append(f"imagens ({key})")
    except Exception as e:
        p(f"imagens: falhou ({str(e)[:80]})")

    # 2) LTX-Video (imagem→vídeo local)
    if include_video:
        try:
            import torch
            from diffusers import LTXImageToVideoPipeline
            p(f"Baixando LTX-Video ({settings.ltx_model})… é o maior (~10GB)")
            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            pipe = LTXImageToVideoPipeline.from_pretrained(settings.ltx_model,
                                                           torch_dtype=dtype)
            del pipe
            _free()
            done.append("LTX-Video")
        except Exception as e:
            p(f"LTX: falhou ({str(e)[:80]})")

    # 3) Whisper configurado (ex.: large-v3)
    try:
        p(f"Baixando Whisper {settings.whisper_model}…")
        from faster_whisper import WhisperModel
        WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
        _free()
        done.append(f"whisper {settings.whisper_model}")
    except Exception as e:
        p(f"whisper: falhou ({str(e)[:80]})")

    # 4) Qwen3-TTS (voz e clonagem) — só baixa se faltar no cache
    try:
        from huggingface_hub import snapshot_download
        for repo in ("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
                     "Qwen/Qwen3-TTS-12Hz-0.6B-Base"):
            p(f"Verificando {repo.split('/')[-1]}…")
            snapshot_download(repo)
        done.append("Qwen3-TTS")
    except Exception as e:
        p(f"qwen3: falhou ({str(e)[:80]})")

    p("Pré-download concluído: " + ", ".join(done))
    return done
