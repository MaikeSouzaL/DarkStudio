"""Estúdio de Voz — clonagem a partir de qualquer arquivo de áudio.

Pipeline de preparação da amostra (com fallbacks em cada etapa):
  1. conversão para WAV mono (ffmpeg)
  2. separação voz × música/fundo — audio-separator (modelos UVR MDX-NET)
  3. remoção de ruído + melhora — DeepFilterNet3 (SOTA, upscale 48kHz);
     fallback: noisereduce; último caso: ffmpeg afftdn
  4. polimento — highpass + loudnorm (nível de voz broadcast)
  5. extração do MELHOR trecho de fala (VAD silero do faster-whisper, 8–15s)
  6. transcrição do trecho (whisper) — vira o ref_text exigido pelo Qwen3

A amostra final fica na biblioteca (voices/<slug>/) e pode ser reusada em
qualquer projeto sem reprocessar: Coqui XTTS, Chatterbox e Qwen3-TTS.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

from .config import ROOT_DIR, Settings

VOICES_DIR = ROOT_DIR / "voices"
VOICES_DIR.mkdir(exist_ok=True)

SEG_MIN, SEG_MAX = 8.0, 15.0  # janela ideal da amostra (s)


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def _run_ffmpeg(settings: Settings, args: list[str]) -> None:
    proc = subprocess.run([settings.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                           *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg: " + "\n".join((proc.stderr or "").splitlines()[-6:]))


# --------------------------------------------------------------- biblioteca
def _slugify(name: str) -> str:
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "voz"


def list_voices() -> list[dict]:
    out = []
    for d in sorted(VOICES_DIR.iterdir()) if VOICES_DIR.exists() else []:
        meta = d / "meta.json"
        if meta.exists() and (d / "sample.wav").exists():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                m["slug"] = d.name
                m["file"] = str(d / "sample.wav")
                out.append(m)
            except Exception:
                pass
    return out


def resolve(voice_id: str) -> dict | None:
    """'lib:<slug>' → {path, ref_text, name} ou None."""
    if not voice_id.startswith("lib:"):
        return None
    d = VOICES_DIR / voice_id[4:]
    if not (d / "sample.wav").exists():
        raise RuntimeError(f"Voz clonada não encontrada: {voice_id[4:]}")
    meta = {}
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"path": str(d / "sample.wav"), "ref_text": meta.get("ref_text", ""),
            "name": meta.get("name", d.name)}


def save_voice(name: str, segment: Path, ref_text: str, source: str = "") -> str:
    slug = _slugify(name)
    base = slug
    i = 2
    while (VOICES_DIR / slug).exists():
        slug = f"{base}-{i}"
        i += 1
    d = VOICES_DIR / slug
    d.mkdir(parents=True)
    shutil.copy2(segment, d / "sample.wav")
    dur = 0.0
    try:
        import av
        with av.open(str(d / "sample.wav")) as c:
            dur = float(c.duration or 0) / 1_000_000.0
    except Exception:
        pass
    (d / "meta.json").write_text(json.dumps({
        "name": name, "ref_text": ref_text.strip(), "source": source,
        "duration": round(dur, 1), "created": time.strftime("%Y-%m-%d %H:%M"),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return slug


def delete_voice(slug: str) -> None:
    d = VOICES_DIR / slug
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------ etapas da limpeza
def _separate_vocals(src: Path, work: Path, progress) -> Path:
    """Isola a voz de música/efeitos com UVR MDX-NET (audio-separator)."""
    if not _has("audio_separator"):
        progress("audio-separator não instalado — pulando separação de música")
        return src
    from audio_separator.separator import Separator

    progress("Separando voz da música (UVR MDX-NET)… pode demorar")
    sep = Separator(output_dir=str(work), output_format="WAV",
                    model_file_dir=str(ROOT_DIR / "models" / "uvr"))
    sep.load_model(model_filename="UVR-MDX-NET-Voc_FT.onnx")
    outputs = sep.separate(str(src))
    for f in outputs:
        p = Path(f)
        if not p.is_absolute():
            p = work / p
        if "(Vocals)" in p.name and p.exists():
            return p
    progress("separação não retornou vocais — usando áudio original")
    return src


def _denoise(src: Path, work: Path, settings: Settings, progress) -> Path:
    """DeepFilterNet3 → UVR-DeNoise (audio-separator) → noisereduce → ffmpeg."""
    if _has("df"):
        try:
            progress("Removendo ruído e melhorando (DeepFilterNet3)…")
            from df.enhance import enhance, init_df, load_audio, save_audio
            model, df_state, _ = init_df()
            audio, _ = load_audio(str(src), sr=df_state.sr())
            enhanced = enhance(model, df_state, audio)
            out = work / "denoised.wav"
            save_audio(str(out), enhanced, df_state.sr())
            return out
        except Exception as e:
            progress(f"DeepFilterNet falhou ({e}) — usando fallback")
    if _has("audio_separator"):
        try:
            progress("Removendo ruído (UVR-DeNoise)…")
            from audio_separator.separator import Separator
            sep = Separator(output_dir=str(work), output_format="WAV",
                            model_file_dir=str(ROOT_DIR / "models" / "uvr"))
            sep.load_model(model_filename="UVR-DeNoise.pth")
            outputs = sep.separate(str(src))
            for f in outputs:
                p = Path(f)
                if not p.is_absolute():
                    p = work / p
                if "(No Noise)" in p.name and p.exists():
                    return p
        except Exception as e:
            progress(f"UVR-DeNoise falhou ({e}) — usando fallback")
    if _has("noisereduce"):
        try:
            progress("Removendo ruído (noisereduce)…")
            import numpy as np
            import soundfile as sf
            import noisereduce as nr
            data, sr = sf.read(str(src))
            if data.ndim > 1:
                data = data.mean(axis=1)
            red = nr.reduce_noise(y=data, sr=sr, stationary=False, prop_decrease=0.9)
            out = work / "denoised.wav"
            sf.write(str(out), red.astype(np.float32), sr)
            return out
        except Exception as e:
            progress(f"noisereduce falhou ({e}) — usando ffmpeg")
    progress("Removendo ruído (ffmpeg afftdn)…")
    out = work / "denoised.wav"
    _run_ffmpeg(settings, ["-i", str(src), "-af", "afftdn=nf=-28", str(out)])
    return out


def _polish(src: Path, work: Path, settings: Settings) -> Path:
    """Highpass + normalização de loudness para nível de voz consistente."""
    out = work / "clean.wav"
    _run_ffmpeg(settings, ["-i", str(src),
                           "-af", "highpass=f=60,loudnorm=I=-19:TP=-2:LRA=7",
                           "-ar", "48000", "-ac", "1", str(out)])
    return out


def _best_segment(src: Path, work: Path, settings: Settings, progress) -> Path:
    """Escolhe o melhor trecho contínuo de fala (8–15s) via VAD silero."""
    start, end = None, None
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        progress("Procurando o melhor trecho de fala (VAD)…")
        audio = decode_audio(str(src), sampling_rate=16000)
        total = len(audio) / 16000.0
        ts = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=350,
                                                     speech_pad_ms=120))
        regions = [(t["start"] / 16000.0, t["end"] / 16000.0) for t in ts]
        # funde regiões próximas (<0.4s de gap)
        merged: list[list[float]] = []
        for s, e in regions:
            if merged and s - merged[-1][1] < 0.4:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        # melhor região: a mais longa; janela central de até SEG_MAX
        if merged:
            s, e = max(merged, key=lambda r: r[1] - r[0])
            if e - s > SEG_MAX:
                mid = (s + e) / 2
                s, e = mid - SEG_MAX / 2, mid + SEG_MAX / 2
            if e - s < SEG_MIN:  # estende com vizinhos se curto demais
                e = min(total, s + SEG_MIN)
            start, end = s, e
    except Exception as e:
        progress(f"VAD indisponível ({e}) — usando trecho central")
    if start is None:
        import av
        with av.open(str(src)) as c:
            total = float(c.duration or 12_000_000) / 1_000_000.0
        mid = total / 2
        start, end = max(0, mid - 6), min(total, mid + 6)

    out = work / "sample.wav"
    dur = max(3.0, end - start)
    _run_ffmpeg(settings, ["-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(src),
                           "-af", f"afade=t=in:d=0.03,afade=t=out:st={dur - 0.05:.2f}:d=0.05",
                           "-ar", "44100", "-ac", "1", str(out)])
    return out


def _transcribe(segment: Path, settings: Settings, progress) -> str:
    try:
        progress("Transcrevendo a amostra (ref. para clonagem)…")
        from faster_whisper import WhisperModel
        model = WhisperModel("small", device="auto", compute_type=settings.whisper_compute)
        try:
            segs, _ = model.transcribe(str(segment), beam_size=3)
            return " ".join(s.text.strip() for s in segs).strip()
        except (RuntimeError, OSError) as e:
            if any(k in str(e).lower() for k in ("cublas", "cudnn", "cuda")):
                model = WhisperModel("small", device="cpu", compute_type="int8")
                segs, _ = model.transcribe(str(segment), beam_size=3)
                return " ".join(s.text.strip() for s in segs).strip()
            raise
    except Exception as e:
        progress(f"transcrição falhou ({e}) — preencha o texto manualmente")
        return ""


# ------------------------------------------------------------------ pipeline
def clean_and_extract(src: Path, settings: Settings, separate_music: bool = True,
                      progress=None) -> dict:
    """Arquivo bruto → amostra limpa de 8–15s + transcrição. Retorna caminhos."""
    def p(msg: str):
        if progress:
            progress(msg)

    work = VOICES_DIR / "_tmp"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    p("Convertendo áudio…")
    wav = work / "input.wav"
    _run_ffmpeg(settings, ["-i", str(src), "-ar", "44100", "-ac", "1", str(wav)])

    cur = _separate_vocals(wav, work, p) if separate_music else wav
    cur = _denoise(cur, work, settings, p)
    cur = _polish(cur, work, settings)
    segment = _best_segment(cur, work, settings, p)
    ref_text = _transcribe(segment, settings, p)
    p("Amostra pronta!")
    return {"segment": segment, "clean": cur, "ref_text": ref_text}
