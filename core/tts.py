"""Narração TTS — engines plugáveis.

APIs (só precisam de chave, nenhuma lib extra):
  edge       -> edge-tts: vozes neurais Microsoft, grátis, pt-BR excelente [padrão]
  gemini     -> Gemini TTS: usa a MESMA GEMINI_API_KEY do app; aceita instrução
                de estilo ("tom sombrio e misterioso") — ótimo p/ canal dark
  elevenlabs -> ElevenLabs (ELEVENLABS_API_KEY): referência comercial em pt-BR
  openai     -> OpenAI gpt-4o-mini-tts (OPENAI_API_KEY): barato, aceita estilo

Locais / open-source (instale no .venv só se quiser):
  qwen3      -> Qwen3-TTS (Apache 2.0, jan/2026): pip install qwen-tts torch soundfile
  coqui      -> Coqui XTTS-v2/VITS: pip install coqui-tts  (XTTS = NÃO comercial!)
  kokoro     -> Kokoro-82M (Apache 2.0): pip install kokoro soundfile
  chatterbox -> Chatterbox (MIT, GPU): pip install chatterbox-tts
  piper      -> Piper (MIT, levíssimo, CPU): pip install piper-tts
  mock       -> tom de teste (offline, sem voz real)
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import math
import struct
import subprocess
import wave
from pathlib import Path

from .config import ROOT_DIR, settings
from .textproc import split_sentences

# --------------------------------------------------------------- catálogo
EDGE_VOICES = {
    "pt-BR": [
        ("pt-BR-AntonioNeural", "Antonio — masculina, narração firme"),
        ("pt-BR-FranciscaNeural", "Francisca — feminina, clara"),
        ("pt-BR-ThalitaMultilingualNeural", "Thalita — feminina, multilíngue"),
        ("pt-BR-MacerioMultilingualNeural", "Macerio — masculina, multilíngue"),
        ("pt-PT-DuarteNeural", "Duarte — masculina (Portugal)"),
        ("pt-PT-RaquelNeural", "Raquel — feminina (Portugal)"),
        ("pt-PT-FernandaNeural", "Fernanda — feminina (Portugal)"),
    ],
    "en-US": [
        ("en-US-ChristopherNeural", "Christopher — deep male"),
        ("en-US-GuyNeural", "Guy — male"),
        ("en-US-EricNeural", "Eric — male"),
        ("en-US-RogerNeural", "Roger — male"),
        ("en-US-SteffanNeural", "Steffan — male"),
        ("en-US-AndrewMultilingualNeural", "Andrew — male, multilingual"),
        ("en-US-BrianMultilingualNeural", "Brian — male, multilingual"),
        ("en-US-AriaNeural", "Aria — female"),
        ("en-US-JennyNeural", "Jenny — female"),
        ("en-US-MichelleNeural", "Michelle — female"),
        ("en-US-AvaMultilingualNeural", "Ava — female, multilingual"),
        ("en-US-EmmaMultilingualNeural", "Emma — female, multilingual"),
    ],
    "es-ES": [
        ("es-ES-AlvaroNeural", "Álvaro — masculina"),
        ("es-ES-ElviraNeural", "Elvira — feminina"),
        ("es-MX-JorgeNeural", "Jorge — masculina (MX)"),
        ("es-MX-DaliaNeural", "Dalia — feminina (MX)"),
        ("es-AR-TomasNeural", "Tomás — masculina (AR)"),
        ("es-AR-ElenaNeural", "Elena — feminina (AR)"),
    ],
}

# vozes Gemini — catálogo completo (falam o idioma do texto automaticamente)
GEMINI_VOICES = [
    ("Charon", "Charon — grave, informativa (narração)"),
    ("Algenib", "Algenib — rasgada, sombria"),
    ("Kore", "Kore — firme"),
    ("Gacrux", "Gacrux — madura"),
    ("Iapetus", "Iapetus — clara"),
    ("Enceladus", "Enceladus — sussurrada"),
    ("Sulafat", "Sulafat — calorosa"),
    ("Alnilam", "Alnilam — firme, masculina"),
    ("Achernar", "Achernar — suave"),
    ("Puck", "Puck — animada"),
    ("Zephyr", "Zephyr — brilhante"),
    ("Fenrir", "Fenrir — empolgada"),
    ("Leda", "Leda — jovem"),
    ("Orus", "Orus — firme"),
    ("Aoede", "Aoede — leve"),
    ("Callirrhoe", "Callirrhoe — tranquila"),
    ("Autonoe", "Autonoe — brilhante"),
    ("Umbriel", "Umbriel — descontraída"),
    ("Algieba", "Algieba — macia"),
    ("Despina", "Despina — macia"),
    ("Erinome", "Erinome — clara"),
    ("Rasalgethi", "Rasalgethi — informativa"),
    ("Laomedeia", "Laomedeia — animada"),
    ("Schedar", "Schedar — equilibrada"),
    ("Pulcherrima", "Pulcherrima — direta"),
    ("Achird", "Achird — amigável"),
    ("Zubenelgenubi", "Zubenelgenubi — casual"),
    ("Vindemiatrix", "Vindemiatrix — gentil"),
    ("Sadachbia", "Sadachbia — vivaz"),
    ("Sadaltager", "Sadaltager — professoral"),
]

# lista oficial de speakers do Qwen3-TTS CustomVoice (validada pelo próprio modelo)
QWEN3_VOICES = [
    ("ryan", "Ryan — masculina firme"),
    ("aiden", "Aiden — masculina jovem"),
    ("dylan", "Dylan — masculina casual"),
    ("eric", "Eric — masculina calma"),
    ("uncle_fu", "Uncle Fu — masculina grave, senhor"),
    ("vivian", "Vivian — feminina"),
    ("serena", "Serena — feminina serena"),
    ("sohee", "Sohee — feminina doce"),
    ("ono_anna", "Ono Anna — feminina suave")]

COQUI_VOICES = [
    ("xtts:Dionisio Schuyler", "Dionisio — masculina (não comercial)"),
    ("xtts:Damien Black", "Damien — grave (não comercial)"),
    ("xtts:Viktor Menelaos", "Viktor — dramática (não comercial)"),
    ("xtts:Andrew Chipper", "Andrew — enérgica (não comercial)"),
    ("xtts:Craig Gutsy", "Craig — rouca (não comercial)"),
    ("xtts:Luis Moray", "Luis — calorosa (não comercial)"),
    ("xtts:Aaron Dreschner", "Aaron — narrador (não comercial)"),
    ("xtts:Kumar Dahl", "Kumar — profunda (não comercial)"),
    ("xtts:Ana Florence", "Ana — feminina (não comercial)"),
    ("xtts:Sofia Hellen", "Sofia — feminina suave (não comercial)"),
    ("xtts:Brenda Stern", "Brenda — séria (não comercial)"),
    ("xtts:Alison Dietlinde", "Alison — clara (não comercial)"),
    ("xtts:Daisy Studious", "Daisy — jovem (não comercial)"),
    ("xtts:Alexandra Hisakawa", "Alexandra — doce (não comercial)"),
    ("xtts:Rosemary Okafor", "Rosemary — madura (não comercial)"),
    ("xtts:Narelle Moon", "Narelle — misteriosa (não comercial)"),
    ("vits-pt", "VITS português — leve, licença aberta"),
]

ELEVEN_VOICES = [
    ("pNInz6obpgDQGcFmaJgB", "Adam — masculina profunda"),
    ("ErXwobaYiN019PkySvjV", "Antoni — masculina calorosa"),
    ("TxGEqnHWrfWFTfGW9XjX", "Josh — masculina jovem"),
    ("VR6AewLTigWG4xSOukaG", "Arnold — masculina firme"),
    ("onwK4e9ZLuTAKqWW03F9", "Daniel — masculina britânica"),
    ("JBFqnCBsd6RMkjVDRZzb", "George — masculina rouca"),
    ("TX3LPaxmHKxFdv7VOQHJ", "Liam — masculina articulada"),
    ("GBv7mTt0atIp3Br8iCZE", "Thomas — masculina calma"),
    ("21m00Tcm4TlvDq8ikWAM", "Rachel — feminina"),
    ("EXAVITQu4vr4xnSDxMaL", "Bella — feminina suave"),
    ("AZnzlk1XvdvUeBnXmlld", "Domi — feminina forte"),
    ("XB0fDUnXU5powFXDhCwa", "Charlotte — feminina sedutora"),
    ("XrExE9yKIg1WjnnlVkGX", "Matilda — feminina calorosa"),
    ("pFZP5JQG7iQjIQuC4Bku", "Lily — feminina britânica"),
    ("jsCqWAovK2LkecY7zXl4", "Freya — feminina expressiva"),
    ("ThT5KcBeYPX3keUQqHPh", "Dorothy — feminina narrativa"),
]

OPENAI_VOICES = [("onyx", "Onyx — masculina profunda"), ("ash", "Ash — masculina"),
                 ("echo", "Echo — masculina"), ("ballad", "Ballad — masculina suave"),
                 ("verse", "Verse — masculina expressiva"),
                 ("alloy", "Alloy — neutra"), ("fable", "Fable — narrativa"),
                 ("nova", "Nova — feminina"), ("shimmer", "Shimmer — feminina suave"),
                 ("coral", "Coral — feminina calorosa"), ("sage", "Sage — feminina serena")]

KOKORO_VOICES = {
    "pt-BR": [("pf_dora", "Dora — feminina"), ("pm_alex", "Alex — masculina"),
              ("pm_santa", "Santa — masculina")],
    "en-US": [("af_heart", "Heart — female"), ("af_bella", "Bella — female"),
              ("af_nicole", "Nicole — female (ASMR)"), ("af_sarah", "Sarah — female"),
              ("af_sky", "Sky — female"), ("af_nova", "Nova — female"),
              ("af_aoede", "Aoede — female"), ("af_kore", "Kore — female"),
              ("am_michael", "Michael — male"), ("am_adam", "Adam — male"),
              ("am_fenrir", "Fenrir — male"), ("am_puck", "Puck — male"),
              ("am_echo", "Echo — male"), ("am_onyx", "Onyx — male deep"),
              ("bm_george", "George — male (UK)"), ("bm_lewis", "Lewis — male (UK)"),
              ("bf_emma", "Emma — female (UK)"), ("bf_isabella", "Isabella — female (UK)")],
    "es-ES": [("ef_dora", "Dora — femenina"), ("em_alex", "Alex — masculina"),
              ("em_santa", "Santa — masculina")],
}

PIPER_VOICES = {
    "pt-BR": [("pt_BR-faber-medium", "Faber — masculina"),
              ("pt_BR-edresson-low", "Edresson — masculina (leve)"),
              ("pt_PT-tugão-medium", "Tugão — masculina (Portugal)")],
    "en-US": [("en_US-lessac-medium", "Lessac — female"),
              ("en_US-ryan-high", "Ryan — male"),
              ("en_US-joe-medium", "Joe — male"),
              ("en_US-amy-medium", "Amy — female"),
              ("en_US-hfc_male-medium", "HFC — male"),
              ("en_US-hfc_female-medium", "HFC — female"),
              ("en_US-kusal-medium", "Kusal — male"),
              ("en_GB-alan-medium", "Alan — male (UK)")],
    "es-ES": [("es_ES-davefx-medium", "Davefx — masculina"),
              ("es_ES-sharvard-medium", "Sharvard — feminina"),
              ("es_MX-claude-high", "Claude — masculina (MX)")],
}

_KOKORO_LANG = {"pt-BR": "p", "en-US": "a", "es-ES": "e"}
_QWEN_LANG = {"pt-BR": "Portuguese", "en-US": "English", "es-ES": "Spanish"}
_SHORT_LANG = {"pt-BR": "pt", "en-US": "en", "es-ES": "es"}


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


LOCAL_ENGINES = ("qwen3", "coqui", "chatterbox", "kokoro", "piper")


def device_label() -> str:
    """Rótulo do dispositivo usado pelos engines locais (GPU nome, ou CPU)."""
    try:
        import torch
        if torch.cuda.is_available():
            return "GPU · " + torch.cuda.get_device_name(0)
    except Exception:
        pass
    return "CPU"


def engines_info() -> list[dict]:
    """Catálogo de engines com disponibilidade e requisitos."""
    return [
        {"id": "edge", "label": "Edge TTS — grátis", "available": True, "needs_key": None,
         "hint": "Vozes neurais Microsoft — melhor custo/qualidade pt-BR, sem GPU", "style": False},
        {"id": "gemini", "label": "Gemini TTS — estilo dirigível",
         "available": settings.gemini_ready, "needs_key": "GEMINI_API_KEY",
         "hint": "Usa a mesma chave do app. Aceita instrução de estilo: “tom sombrio, ritmo lento”",
         "style": True},
        {"id": "qwen3", "label": "Qwen3-TTS — open source local", "available": _has("qwen_tts"),
         "needs_key": None, "style": False,
         "hint": "Apache 2.0, 10 idiomas incl. português — pip install qwen-tts torch soundfile (GPU recomendada)"},
        {"id": "elevenlabs", "label": "ElevenLabs — premium",
         "available": bool(settings.elevenlabs_api_key), "needs_key": "ELEVENLABS_API_KEY",
         "hint": "Referência comercial em narração pt-BR (pago por caractere)", "style": False},
        {"id": "openai", "label": "OpenAI TTS", "available": bool(settings.openai_api_key),
         "needs_key": "OPENAI_API_KEY", "style": True,
         "hint": "gpt-4o-mini-tts — barato, aceita instrução de estilo"},
        {"id": "coqui", "label": "Coqui XTTS/VITS — local", "available": _has("TTS"),
         "needs_key": None, "style": False,
         "hint": "pip install coqui-tts — ATENÇÃO: modelo XTTS tem licença NÃO comercial (CPML)"},
        {"id": "kokoro", "label": "Kokoro-82M — local leve", "available": _has("kokoro"),
         "needs_key": None, "style": False,
         "hint": "Apache 2.0, roda em CPU — pip install kokoro soundfile"},
        {"id": "chatterbox", "label": "Chatterbox — clonagem (GPU)",
         "available": _has("chatterbox"), "needs_key": None, "style": False,
         "hint": "MIT — clona voz a partir de amostra .wav — pip install chatterbox-tts"},
        {"id": "piper", "label": "Piper — local levíssimo", "available": _has("piper"),
         "needs_key": None, "style": False,
         "hint": "MIT, CPU instantâneo, qualidade média — pip install piper-tts"},
    ]


CLONE_ENGINES = ("coqui", "chatterbox", "qwen3")  # aceitam vozes da biblioteca


def _library_voices() -> list[tuple[str, str]]:
    from . import voices as vlib
    return [(f"lib:{v['slug']}", f"⭐ {v['name']} — voz clonada ({v.get('duration', 0):.0f}s)")
            for v in vlib.list_voices()]


def voices_for(engine: str, language: str) -> list[tuple[str, str]]:
    lib = _library_voices() if engine in CLONE_ENGINES else []
    if engine == "edge":
        return EDGE_VOICES.get(language, EDGE_VOICES["en-US"])
    if engine == "gemini":
        return GEMINI_VOICES
    if engine == "qwen3":
        return lib + QWEN3_VOICES
    if engine == "coqui":
        return lib + COQUI_VOICES
    if engine == "elevenlabs":
        return ELEVEN_VOICES
    if engine == "openai":
        return OPENAI_VOICES
    if engine == "kokoro":
        return KOKORO_VOICES.get(language, KOKORO_VOICES["en-US"])
    if engine == "piper":
        return PIPER_VOICES.get(language, PIPER_VOICES["en-US"])
    if engine == "chatterbox":
        return lib + [("default", "Voz padrão do Chatterbox")]
    return [("mock", "Tom de teste")]


# ---------------------------------------------------------------- helpers
def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Divide texto longo em blocos que respeitam limites das APIs."""
    chunks, cur = [], ""
    for s in split_sentences(text) or [text]:
        if cur and len(cur) + len(s) + 1 > max_chars:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks or [text]


def _write_wav(pcm: bytes, out_path: Path, rate: int = 24000) -> None:
    with wave.open(str(out_path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)


def _concat_media(parts: list[Path], out_path: Path) -> None:
    """Junta partes de áudio (mp3) sem re-encode via ffmpeg concat."""
    if len(parts) == 1:
        parts[0].replace(out_path)
        return
    lst = out_path.with_suffix(".txt")
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    subprocess.run([settings.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    str(out_path)], check=True)
    lst.unlink(missing_ok=True)
    for p in parts:
        p.unlink(missing_ok=True)


_MODEL_CACHE: dict = {}
_QWEN_FORCE_PLAIN = False   # memoriza que o Qwen precisa de carga "plain" (sem device_map)


# ---------------------------------------------------------------- engines
def _synth_edge(text, voice, rate, out_path, language, style=""):
    import edge_tts

    async def _run():
        await edge_tts.Communicate(text, voice, rate=f"{rate:+d}%").save(str(out_path))

    asyncio.run(_run())


def _synth_gemini(text, voice, rate, out_path, language, style=""):
    from google.genai import types

    from .config import genai_client

    if not settings.gemini_ready:
        raise RuntimeError("Configure a GEMINI_API_KEY (ou Vertex) nas Configurações.")
    client = genai_client(settings)
    models = [settings.tts_model] + [m for m in settings.tts_model_fallbacks
                                     if m != settings.tts_model]
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
    )
    pcm = bytearray()
    for chunk in _chunk_text(text, 3800):
        content = f"{style.strip().rstrip(':')}: {chunk}" if style.strip() else chunk
        last, got = None, False
        for model in models:
            try:
                resp = client.models.generate_content(model=model, contents=content,
                                                      config=config)
                for cand in (resp.candidates or []):
                    for part in (getattr(cand.content, "parts", None) or []):
                        inline = getattr(part, "inline_data", None)
                        if inline is not None and getattr(inline, "data", None):
                            data = inline.data
                            pcm += (data if isinstance(data, (bytes, bytearray))
                                    else base64.b64decode(data))
                            got = True
                if got:
                    break
            except Exception as e:
                last = e
                continue
        if not got:
            raise RuntimeError(f"Gemini TTS não retornou áudio: {last}")
    _write_wav(bytes(pcm), out_path, 24000)


def _load_qwen(model_id: str, force_plain: bool = False):
    import torch
    from qwen_tts import Qwen3TTSModel

    key = model_id + ("|plain" if force_plain else "")
    if key not in _MODEL_CACHE:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        # SEMPRE float32: o Qwen3-TTS foi treinado p/ bf16 (que Turing não tem)
        # e em float16 alguns speakers disparam asserts CUDA; com 0.6B cabe em
        # 6GB tranquilamente e fica numericamente estável.
        dtype = torch.float32
        if force_plain:
            # carga "plena" (sem device_map/meta) + mover — evita o erro
            # "Cannot copy out of meta tensor" de alguns speakers
            model = Qwen3TTSModel.from_pretrained(model_id, dtype=dtype)
            for attr in ("to", ):
                try:
                    model = model.to(device)
                    break
                except AttributeError:
                    inner = getattr(model, "model", None)
                    if inner is not None and hasattr(inner, "to"):
                        inner.to(device)
                    break
        else:
            model = Qwen3TTSModel.from_pretrained(model_id, device_map=device,
                                                  dtype=dtype)
        _MODEL_CACHE.clear()          # 1 modelo grande por vez na VRAM
        _MODEL_CACHE[key] = model
    return _MODEL_CACHE[key]


def _synth_qwen3(text, voice, rate, out_path, language, style=""):
    import numpy as np
    import soundfile as sf

    lang = _QWEN_LANG.get(language, "Auto")

    def _run(force_plain: bool):
        waves, sr = [], 24000
        if voice.startswith("lib:"):  # clonagem com amostra da biblioteca
            from . import voices as vlib
            ref = vlib.resolve(voice)
            model = _load_qwen("Qwen/Qwen3-TTS-12Hz-0.6B-Base", force_plain)
            for chunk in _chunk_text(text, 1200):
                wavs, sr = model.generate_voice_clone(text=chunk, language=lang,
                                                      ref_audio=ref["path"],
                                                      ref_text=ref["ref_text"] or None)
                waves.append(np.asarray(wavs[0]))
        else:
            model = _load_qwen("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", force_plain)
            for chunk in _chunk_text(text, 1200):
                wavs, sr = model.generate_custom_voice(text=chunk, language=lang,
                                                       speaker=voice)
                waves.append(np.asarray(wavs[0]))
        return waves, sr

    global _QWEN_FORCE_PLAIN
    try:
        waves, sr = _run(force_plain=_QWEN_FORCE_PLAIN)
    except (RuntimeError, NotImplementedError) as e:
        if "meta tensor" not in str(e).lower() or _QWEN_FORCE_PLAIN:
            raise
        # detectou 1x que precisa de "plain" → MEMORIZA (evita recarregar a
        # cada bloco tentando device_map de novo, que travava a narração)
        _QWEN_FORCE_PLAIN = True
        _MODEL_CACHE.clear()
        waves, sr = _run(force_plain=True)
    sf.write(str(out_path), np.concatenate(waves), sr)


def _synth_coqui(text, voice, rate, out_path, language, style=""):
    import os
    os.environ.setdefault("COQUI_TOS_AGREED", "1")  # licença exibida na UI
    from TTS.api import TTS as CoquiTTS

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"  # GPU por padrão
    if voice.startswith("vits"):
        model_name = {"pt-BR": "tts_models/pt/cv/vits",
                      "es-ES": "tts_models/es/css10/vits",
                      "en-US": "tts_models/en/ljspeech/vits"}.get(language,
                                                                  "tts_models/en/ljspeech/vits")
        if model_name not in _MODEL_CACHE:
            _MODEL_CACHE[model_name] = CoquiTTS(model_name).to(device)
        _MODEL_CACHE[model_name].tts_to_file(text=text, file_path=str(out_path))
        return
    model_name = "tts_models/multilingual/multi-dataset/xtts_v2"
    if model_name not in _MODEL_CACHE:
        _MODEL_CACHE[model_name] = CoquiTTS(model_name).to(device)
    tts = _MODEL_CACHE[model_name]
    kwargs = {"language": _SHORT_LANG.get(language, "en"), "file_path": str(out_path)}
    if voice.startswith("lib:"):  # voz clonada da biblioteca
        from . import voices as vlib
        kwargs["speaker_wav"] = vlib.resolve(voice)["path"]
    else:
        speaker = voice.split(":", 1)[1] if ":" in voice else voice
        if Path(speaker).exists():
            kwargs["speaker_wav"] = speaker
        else:
            kwargs["speaker"] = speaker
    tts.tts_to_file(text=text, **kwargs)


def _synth_elevenlabs(text, voice, rate, out_path, language, style=""):
    import httpx

    if not settings.elevenlabs_api_key:
        raise RuntimeError("Configure a ELEVENLABS_API_KEY nas Configurações.")
    parts = []
    with httpx.Client(timeout=300) as client:
        for i, chunk in enumerate(_chunk_text(text, 4500)):
            r = client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": settings.elevenlabs_api_key},
                json={"text": chunk, "model_id": settings.elevenlabs_model},
            )
            if r.status_code != 200:
                raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
            part = out_path.with_suffix(f".part{i}.mp3")
            part.write_bytes(r.content)
            parts.append(part)
    _concat_media(parts, out_path)


def _synth_openai(text, voice, rate, out_path, language, style=""):
    import httpx

    if not settings.openai_api_key:
        raise RuntimeError("Configure a OPENAI_API_KEY nas Configurações.")
    parts = []
    with httpx.Client(timeout=300) as client:
        for i, chunk in enumerate(_chunk_text(text, 3500)):
            body = {"model": "gpt-4o-mini-tts", "voice": voice, "input": chunk,
                    "response_format": "mp3"}
            if style.strip():
                body["instructions"] = style.strip()
            r = client.post("https://api.openai.com/v1/audio/speech",
                            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                            json=body)
            if r.status_code != 200:
                raise RuntimeError(f"OpenAI TTS {r.status_code}: {r.text[:300]}")
            part = out_path.with_suffix(f".part{i}.mp3")
            part.write_bytes(r.content)
            parts.append(part)
    _concat_media(parts, out_path)


def _synth_kokoro(text, voice, rate, out_path, language, style=""):
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    key = f"kokoro-{language}"
    if key not in _MODEL_CACHE:
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"  # GPU por padrão
            _MODEL_CACHE[key] = KPipeline(lang_code=_KOKORO_LANG.get(language, "a"),
                                          device=device)
        except TypeError:  # versões antigas sem parâmetro device
            _MODEL_CACHE[key] = KPipeline(lang_code=_KOKORO_LANG.get(language, "a"))
    chunks = [a for _, _, a in _MODEL_CACHE[key](text, voice=voice,
                                                 speed=1.0 + rate / 100.0)]
    if not chunks:
        raise RuntimeError("Kokoro não gerou áudio")
    sf.write(str(out_path), np.concatenate(chunks), 24000)


def _patch_perth():
    """Alguns builds do resemble-perth expõem PerthImplicitWatermarker=None,
    o que quebra o Chatterbox. Injetamos um watermarker no-op (não marca o
    áudio, mas permite a síntese)."""
    try:
        import perth
        if getattr(perth, "PerthImplicitWatermarker", None) is None:
            class _NoopWatermarker:
                def apply_watermark(self, wav, sample_rate=None, **_):
                    return wav

                def get_watermark(self, *a, **k):
                    return None
            perth.PerthImplicitWatermarker = _NoopWatermarker
            if hasattr(perth, "perth_net"):
                perth.perth_net = getattr(perth, "perth_net", None)
    except Exception:
        pass


def _synth_chatterbox(text, voice, rate, out_path, language, style=""):
    import torch
    import torchaudio

    _patch_perth()
    from chatterbox.tts import ChatterboxTTS

    if "chatterbox" not in _MODEL_CACHE:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _MODEL_CACHE["chatterbox"] = ChatterboxTTS.from_pretrained(device=device)
    model = _MODEL_CACHE["chatterbox"]
    ref = None
    if voice.startswith("lib:"):
        from . import voices as vlib
        ref = vlib.resolve(voice)["path"]
    elif voice not in ("default", "") and Path(voice).exists():
        ref = voice
    wav = model.generate(text, audio_prompt_path=ref)
    torchaudio.save(str(out_path), wav, model.sr)


def _ensure_piper_voice(voice: str) -> Path:
    """Baixa a voz Piper (onnx + json) do HuggingFace na primeira vez."""
    import httpx

    models_dir = ROOT_DIR / "models" / "piper"
    models_dir.mkdir(parents=True, exist_ok=True)
    onnx = models_dir / f"{voice}.onnx"
    if onnx.exists():
        return onnx
    locale, name, quality = voice.split("-", 2)
    base = (f"https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"{locale.split('_')[0]}/{locale}/{name}/{quality}/{voice}")
    with httpx.Client(timeout=600, follow_redirects=True) as client:
        for suffix in (".onnx", ".onnx.json"):
            r = client.get(base + suffix)
            r.raise_for_status()
            (models_dir / f"{voice}{suffix}").write_bytes(r.content)
    return onnx


def _synth_piper(text, voice, rate, out_path, language, style=""):
    from piper.voice import PiperVoice

    onnx = _ensure_piper_voice(voice)
    if voice not in _MODEL_CACHE:
        _MODEL_CACHE[voice] = PiperVoice.load(str(onnx))
    with wave.open(str(out_path), "wb") as f:
        _MODEL_CACHE[voice].synthesize(text, f,
                                       length_scale=max(0.6, 1.0 - rate / 100.0))


def _synth_mock(text, voice, rate, out_path, language, style=""):
    """Bipes proporcionais ao texto — só para testar o pipeline offline."""
    sr = 24000
    frames = bytearray()
    for w in text.split():
        dur = max(0.18, min(0.5, 0.075 * len(w)))
        freq = 180 + (abs(hash(w)) % 220)
        n = int(sr * dur)
        for j in range(n):
            env = min(1.0, j / 400, (n - j) / 400)
            frames += struct.pack("<h", int(12000 * env * math.sin(2 * math.pi * freq * j / sr)))
        frames += b"\x00\x00" * int(sr * 0.06)
        if w.rstrip('"\')').endswith((".", "!", "?", "…")):
            frames += b"\x00\x00" * int(sr * 0.35)
    _write_wav(bytes(frames), out_path, sr)


_ENGINES = {
    "edge": (_synth_edge, ".mp3"),
    "gemini": (_synth_gemini, ".wav"),
    "qwen3": (_synth_qwen3, ".wav"),
    "coqui": (_synth_coqui, ".wav"),
    "elevenlabs": (_synth_elevenlabs, ".mp3"),
    "openai": (_synth_openai, ".mp3"),
    "kokoro": (_synth_kokoro, ".wav"),
    "chatterbox": (_synth_chatterbox, ".wav"),
    "piper": (_synth_piper, ".wav"),
    "mock": (_synth_mock, ".wav"),
}

_IMPORT_CHECK = {"qwen3": "qwen_tts", "coqui": "TTS", "kokoro": "kokoro",
                 "chatterbox": "chatterbox", "piper": "piper"}


SAMPLE_TEXT = {
    "pt-BR": "Esta é uma amostra da voz escolhida para a narração do seu vídeo.",
    "es-ES": "Esta es una muestra de la voz elegida para tu video.",
    "en-US": "This is a sample of the selected narration voice for your video.",
}


def sample_filename(engine: str, voice: str, style: str = "") -> str:
    import hashlib
    import re
    vslug = re.sub(r"[^a-z0-9]+", "-", voice.lower())[:40]
    shash = hashlib.sha1(style.encode()).hexdigest()[:6] if style else "0"
    return f"{engine}_{vslug}_{shash}"


def sample_path(samples_dir: Path, engine: str, voice: str, style: str = "") -> Path:
    ext = {"edge": ".mp3", "elevenlabs": ".mp3", "openai": ".mp3"}.get(engine, ".wav")
    return samples_dir / f"{sample_filename(engine, voice, style)}{ext}"


def ensure_sample(samples_dir: Path, engine: str, voice: str, language: str,
                  style: str = "", rate: int = 0) -> Path:
    """Gera a amostra da voz se ainda não existir; devolve o caminho (cache)."""
    out = sample_path(samples_dir, engine, voice, style)
    if out.exists() and out.stat().st_size > 800:
        return out
    text = SAMPLE_TEXT.get(language, SAMPLE_TEXT["en-US"])
    return synthesize(text, engine, voice, rate, samples_dir, language, style,
                      sample_filename(engine, voice, style))


def pregenerate_samples(samples_dir: Path, engine: str, language: str,
                        progress=None) -> tuple[int, int]:
    """Pré-gera as amostras de todas as vozes de um engine. (ok, falhas)."""
    samples_dir.mkdir(parents=True, exist_ok=True)
    voices = voices_for(engine, language)
    ok = fail = 0
    for i, (vid, _) in enumerate(voices):
        if vid.startswith("lib:"):
            continue
        try:
            ensure_sample(samples_dir, engine, vid, language)
            ok += 1
        except Exception:
            fail += 1
        if progress:
            progress(i + 1, len(voices))
    return ok, fail


def _check_engine(engine: str):
    if engine not in _ENGINES:
        raise ValueError(f"Engine TTS desconhecida: {engine}")
    mod = _IMPORT_CHECK.get(engine)
    if mod and not _has(mod):
        info = next((e for e in engines_info() if e["id"] == engine), None)
        raise RuntimeError(f"Engine '{engine}' não instalada no .venv — "
                           f"{info['hint'] if info else 'veja requirements.txt'}")


def synthesize(text: str, engine: str, voice: str, rate: int,
               out_dir: Path, language: str, style: str = "",
               filename: str = "narration") -> Path:
    """Gera a narração completa numa chamada. Retorna o caminho do áudio."""
    _check_engine(engine)
    func, ext = _ENGINES[engine]
    out_path = out_dir / f"{filename}{ext}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    func(text, voice, rate, out_path, language, style=style)
    if not out_path.exists() or out_path.stat().st_size < 1000:
        raise RuntimeError("TTS não produziu áudio válido")
    return out_path


def _group_sentences(sentences: list[str], max_chars: int = 300) -> list[str]:
    """Agrupa frases COMPLETAS em blocos (nunca corta uma frase no meio)."""
    groups, cur = [], ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if cur and len(cur) + len(s) + 1 > max_chars:
            groups.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        groups.append(cur)
    return groups


def synthesize_narration(sentences: list[str], engine: str, voice: str, rate: int,
                         out_dir: Path, language: str, style: str = "",
                         filename: str = "narration", progress=None,
                         cancel=None) -> Path:
    """Gera a narração POR BLOCOS de frases — com progresso real e cancelamento.

    progress(feitos, total) é chamado ANTES de cada bloco (bom ponto de checagem
    de cancelamento, já que progress pode levantar exceção). cancel() -> bool
    também interrompe. Em cancelamento/erro, os arquivos parciais são apagados.
    """
    _check_engine(engine)
    func, ext = _ENGINES[engine]
    out_dir.mkdir(parents=True, exist_ok=True)
    blocks = _group_sentences(sentences) or [" ".join(sentences)]
    total = len(blocks)
    parts: list[Path] = []
    try:
        for i, block in enumerate(blocks):
            if progress:
                progress(i, total)          # reporta e (via callback) checa cancel
            if cancel and cancel():
                raise RuntimeError("__CANCELLED__")
            part = out_dir / f"{filename}.part{i:03d}{ext}"
            func(block, voice, rate, part, language, style=style)
            if not part.exists() or part.stat().st_size < 500:
                raise RuntimeError(f"TTS falhou no bloco {i + 1}/{total}")
            parts.append(part)
        if progress:
            progress(total, total)
        out_path = out_dir / f"{filename}{ext}"
        if len(parts) == 1:
            parts[0].replace(out_path)
        else:
            _concat_media(parts, out_path)  # remove os parciais
        if not out_path.exists() or out_path.stat().st_size < 1000:
            raise RuntimeError("TTS não produziu áudio válido")
        return out_path
    except BaseException:
        for p in parts:
            p.unlink(missing_ok=True)
        raise
