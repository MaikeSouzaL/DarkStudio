"""Sincronização: faster-whisper extrai tempos por palavra e alinhamos
cada frase do roteiro original com início/fim + tempos de cada palavra
(usados no efeito karaokê).
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from .textproc import normalize_token, tokenize

_LANG = {"pt-BR": "pt", "en-US": "en", "es-ES": "es"}


def _add_nvidia_dll_paths() -> None:
    """Torna as DLLs cuBLAS/cuDNN dos wheels pip visíveis para o ctranslate2
    (habilita whisper em GPU no Windows sem instalar o CUDA Toolkit)."""
    import os
    try:
        import nvidia
        base = Path(nvidia.__file__).parent
        for sub in ("cublas", "cudnn"):
            p = base / sub / "bin"
            if p.exists():
                os.add_dll_directory(str(p))
                os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


def _whisper_words(audio: Path, model_size: str, compute: str, language: str,
                   progress=None) -> tuple[list[dict], float]:
    _add_nvidia_dll_paths()
    from faster_whisper import WhisperModel

    def _run(device: str, compute_type: str):
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        segments, info = model.transcribe(
            str(audio),
            language=_LANG.get(language, None),
            word_timestamps=True,
            beam_size=5,
            vad_filter=False,
        )
        words: list[dict] = []
        for seg in segments:  # generator — erros de CUDA só aparecem aqui
            for w in (seg.words or []):
                words.append({"w": w.word.strip(), "s": float(w.start), "e": float(w.end)})
            if progress and info.duration:
                progress(min(seg.end, info.duration), info.duration)
        return words, float(info.duration or (words[-1]["e"] if words else 0.0))

    try:
        return _run("auto", compute)
    except (RuntimeError, OSError) as e:
        msg = str(e).lower()
        if any(k in msg for k in ("cublas", "cudnn", "cuda", "gpu")):
            # GPU sem runtime CUDA completo → refaz em CPU
            return _run("cpu", "int8")
        raise


def align_sentences(sentences: list[str], words: list[dict], total: float) -> list[dict]:
    """Alinha frases do roteiro aos tempos das palavras reconhecidas.

    Estratégia: SequenceMatcher entre tokens normalizados do roteiro e do whisper;
    tokens sem correspondência são interpolados; se o reconhecimento falhar por
    completo (ex.: áudio de teste), distribui o tempo proporcional ao tamanho.
    """
    # tokens do roteiro com mapeamento token -> (frase, posição)
    script_tokens: list[str] = []
    tok_owner: list[tuple[int, int]] = []
    display: list[list[str]] = []
    for si, sent in enumerate(sentences):
        ws = tokenize(sent)
        display.append(ws)
        for wi, w in enumerate(ws):
            script_tokens.append(normalize_token(w))
            tok_owner.append((si, wi))

    hyp_tokens = [normalize_token(w["w"]) for w in words]
    times: list[tuple[float, float] | None] = [None] * len(script_tokens)

    if hyp_tokens and script_tokens:
        sm = SequenceMatcher(a=script_tokens, b=hyp_tokens, autojunk=False)
        for block in sm.get_matching_blocks():
            for k in range(block.size):
                times[block.a + k] = (words[block.b + k]["s"], words[block.b + k]["e"])

    matched = sum(1 for t in times if t)
    if not script_tokens:
        return []

    if matched < max(2, len(script_tokens) * 0.25):
        # fallback proporcional por caracteres
        total = total or 1.0
        total_chars = sum(len(t) + 1 for t in script_tokens)
        cursor = 0.0
        for i, t in enumerate(script_tokens):
            dur = total * (len(t) + 1) / total_chars
            times[i] = (cursor, cursor + dur)
            cursor += dur
    else:
        # interpola buracos entre âncoras conhecidas
        anchors = [i for i, t in enumerate(times) if t]
        first, last = anchors[0], anchors[-1]
        for i in range(len(times)):
            if times[i]:
                continue
            prev_i = max((a for a in anchors if a < i), default=None)
            next_i = min((a for a in anchors if a > i), default=None)
            if prev_i is None:
                start = max(0.0, times[first][0] - 0.3 * (first - i))
                times[i] = (start, start + 0.25)
            elif next_i is None:
                start = times[prev_i][1] + 0.25 * (i - prev_i - 1)
                times[i] = (start, min(total, start + 0.25))
            else:
                t0, t1 = times[prev_i][1], times[next_i][0]
                frac = (i - prev_i) / (next_i - prev_i)
                start = t0 + (t1 - t0) * max(0.0, frac - 0.5 / (next_i - prev_i))
                end = t0 + (t1 - t0) * frac
                times[i] = (start, max(start + 0.05, end))

    # monta estrutura por frase, garantindo monotonicidade
    out: list[dict] = []
    idx = 0
    prev_end = 0.0
    for si, sent in enumerate(sentences):
        n = len(display[si])
        toks = times[idx: idx + n]
        wlist = []
        for wi in range(n):
            s, e = toks[wi]
            s, e = max(prev_end if wi == 0 else s, s), e
            wlist.append({"w": display[si][wi], "s": round(s, 3), "e": round(max(e, s + 0.05), 3)})
        start = wlist[0]["s"]
        end = max(w["e"] for w in wlist)
        start = max(prev_end, start)
        end = max(end, start + 0.4)
        # normaliza palavras dentro dos limites e monotônicas
        cur = start
        for w in wlist:
            w["s"] = round(max(cur, min(w["s"], end)), 3)
            w["e"] = round(min(max(w["e"], w["s"] + 0.05), end), 3)
            cur = w["e"]
        out.append({"i": si, "text": sent, "start": round(start, 3),
                    "end": round(end, 3), "words": wlist})
        prev_end = end
        idx += n

    # estica fins até o início da próxima frase (sem buracos pretos no vídeo)
    for i in range(len(out) - 1):
        out[i]["end"] = round(max(out[i]["end"], out[i + 1]["start"]), 3)
    if out and total:
        out[-1]["end"] = round(max(out[-1]["end"], total), 3)
    return out


def transcribe_and_align(audio: Path, sentences: list[str], model_size: str,
                         compute: str, language: str, progress=None) -> list[dict]:
    words, duration = _whisper_words(audio, model_size, compute, language, progress)
    return align_sentences(sentences, words, duration)
