"""Editor final — montagem com FFmpeg.

Pipeline de render:
  1. um segmento .ts por frase (estático, Ken Burns ou clipe Veo) — com CACHE:
     só re-renderiza a cena cujo conteúdo mudou (hash de imagem+duração+movimento)
  2. união: concat sem re-encode OU corrente de xfade (transições suaves)
  3. passada final: narração + trilha (ducking) + fades + legendas ASS (karaokê
     com presets) queimadas com libass → MP4 H.264 pronto p/ YouTube/Shorts
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .config import Settings


class FFmpegError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(args, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-14:])
        raise FFmpegError(f"FFmpeg falhou ({args[1:3]}):\n{tail}")


def probe_duration(path: Path, settings: Settings) -> float:
    try:  # PyAV já vem com o faster-whisper — dispensa ffprobe no sistema
        import av
        with av.open(str(path)) as c:
            if c.duration:
                return float(c.duration) / 1_000_000.0
            for s in c.streams:
                if s.duration and s.time_base:
                    return float(s.duration * s.time_base)
    except Exception:
        pass
    if settings.ffprobe:
        proc = subprocess.run(
            [settings.ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            return float(json.loads(proc.stdout)["format"]["duration"])
        except Exception:
            pass
    return 0.0


# ------------------------------------------------------------- movimentos
def _kenburns_expr(camera: str, intensity: float, frames: int, w: int, h: int,
                   fps: int) -> str:
    n = max(frames - 1, 1)
    z_in = f"1+{intensity:.3f}*on/{n}"
    z_out = f"{1 + intensity:.3f}-{intensity:.3f}*on/{n}"
    z_fix = f"{1 + max(intensity, 0.10):.3f}"
    cx, cy = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    presets = {
        "zoom_in": (z_in, cx, cy),
        "zoom_out": (z_out, cx, cy),
        "pan_right": (z_fix, f"(iw-iw/zoom)*on/{n}", cy),
        "pan_left": (z_fix, f"(iw-iw/zoom)*(1-on/{n})", cy),
        "pan_down": (z_fix, cx, f"(ih-ih/zoom)*on/{n}"),
        "pan_up": (z_fix, cx, f"(ih-ih/zoom)*(1-on/{n})"),
    }
    diag = f"(iw-iw/zoom)*on/{n}"
    diag_y_up = f"(ih-ih/zoom)*(1-on/{n})"
    presets.update({
        "diag_dr": (z_fix, diag, f"(ih-ih/zoom)*on/{n}"),
        "diag_ur": (z_fix, diag, diag_y_up),
        "zoom_pan_right": (z_in, diag, cy),
        "zoom_pan_left": (z_in, f"(iw-iw/zoom)*(1-on/{n})", cy),
        "pulse": (f"1.07+0.028*sin(2*PI*on/{max(fps * 3, 2)})", cx, cy),
        "handheld": ("1.10", f"(iw-iw/zoom)/2+7*sin(on/3.1)",
                     f"(ih-ih/zoom)/2+5*cos(on/2.3)"),
    })
    z, x, y = presets.get(camera, presets["zoom_in"])
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps}"


CAMERA_LABELS = {
    "zoom_in": "Zoom in", "zoom_out": "Zoom out", "pan_left": "Pan ←",
    "pan_right": "Pan →", "pan_up": "Pan ↑", "pan_down": "Pan ↓",
    "diag_dr": "Diagonal ↘", "diag_ur": "Diagonal ↗",
    "zoom_pan_right": "Zoom + pan →", "zoom_pan_left": "Zoom + pan ←",
    "pulse": "Pulsar (respiração)", "handheld": "Câmera na mão",
}


def segment_hash(kind: str, src: Path, dur: float, motion: dict | None,
                 dims: tuple[int, int], tail: float, fps: int) -> str:
    try:
        st = src.stat()
        src_sig = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        src_sig = "na"
    m = motion or {}
    key = (f"v3|{kind}|{src.name}|{src_sig}|{dur:.2f}|{tail:.2f}|{dims[0]}x{dims[1]}"
           f"|{fps}|{m.get('camera')}|{float(m.get('intensity', 0)):.2f}")
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def render_segment(kind: str, src: Path, dur: float, out_ts: Path, settings: Settings,
                   motion: dict | None = None, dims: tuple[int, int] = (1920, 1080),
                   tail: float = 0.0) -> Path:
    """Renderiza um segmento de vídeo (sem áudio) com duração exata (+ cauda p/ xfade)."""
    fps = settings.fps
    w, h = dims
    total = max(dur, 0.35) + tail
    out_ts.parent.mkdir(parents=True, exist_ok=True)
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
           "-pix_fmt", "yuv420p", "-an", "-f", "mpegts", str(out_ts)]
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
           f"crop={w}:{h},fps={fps},setsar=1,format=yuv420p")

    if kind == "kenburns":
        frames = max(int(round(total * fps)), 2)
        up_w, up_h = round(w * 1.5 / 2) * 2, round(h * 1.5 / 2) * 2
        vf = (f"scale={up_w}:{up_h}:flags=lanczos,"
              + _kenburns_expr((motion or {}).get("camera", "zoom_in"),
                               float((motion or {}).get("intensity", 0.1)),
                               frames, w, h, fps)
              + ",setsar=1,format=yuv420p")
        _run([settings.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
              "-i", str(src), "-vf", vf, "-frames:v", str(frames), *enc])
    elif kind == "video":
        clip_dur = probe_duration(src, settings)
        pad = max(0.0, total - clip_dur) + 0.5
        vf = fit + f",tpad=stop_mode=clone:stop_duration={pad:.3f}"
        _run([settings.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
              "-i", str(src), "-vf", vf, "-t", f"{total:.3f}", *enc])
    else:  # imagem estática
        _run([settings.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
              "-loop", "1", "-t", f"{total:.3f}", "-i", str(src), "-vf", fit, *enc])
    return out_ts


def render_segment_cached(i: int, kind: str, src: Path, dur: float, seg_dir: Path,
                          settings: Settings, motion: dict | None = None,
                          dims: tuple[int, int] = (1920, 1080),
                          tail: float = 0.0) -> tuple[Path, bool]:
    """Render incremental: reaproveita o segmento se nada da cena mudou."""
    h = segment_hash(kind, src, dur, motion, dims, tail, settings.fps)
    out = seg_dir / f"seg_{i:03d}_{h}.ts"
    if out.exists() and out.stat().st_size > 1000:
        return out, True
    for old in seg_dir.glob(f"seg_{i:03d}_*.ts"):
        old.unlink(missing_ok=True)
    render_segment(kind, src, dur, out, settings, motion=motion, dims=dims, tail=tail)
    return out, False


# ------------------------------------------------------------------ união
def concat_segments(segments: list[Path], out_path: Path, settings: Settings) -> Path:
    lst = out_path.with_suffix(".txt")
    lst.write_text("\n".join(f"file '{s.as_posix()}'" for s in segments), encoding="utf-8")
    _run([settings.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
          "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c", "copy", str(out_path)])
    return out_path


# transições xfade curadas para vídeo narrado (ids = nomes oficiais do FFmpeg)
TRANSITIONS = {
    "none": "Corte seco",
    "fade": "Crossfade suave",
    "fadeblack": "Fade pelo preto",
    "fadewhite": "Flash branco",
    "fadegrays": "Fade pelo cinza",
    "dissolve": "Dissolver granulado",
    "smoothleft": "Deslizar suave ←",
    "smoothright": "Deslizar suave →",
    "slideup": "Empurrar ↑",
    "wipeleft": "Cortina ←",
    "circleopen": "Círculo abrindo",
    "radial": "Varredura radial",
    "zoomin": "Zoom através",
    "pixelize": "Pixelizar (retrô)",
    "hblur": "Borrão de velocidade",
    "random": "🎲 Aleatória a cada corte",
}
_RANDOM_POOL = ["fade", "fadeblack", "dissolve", "smoothleft", "smoothright",
                "slideup", "circleopen", "radial", "zoomin", "hblur"]


def pick_transitions(transition: str, n_cuts: int) -> list[str]:
    """Lista de transições por corte (suporta modo aleatório)."""
    import random
    if transition == "random":
        return [random.choice(_RANDOM_POOL) for _ in range(n_cuts)]
    return [transition] * n_cuts


def xfade_concat(segments: list[Path], durations: list[float], trans_dur: float,
                 transitions: list[str] | str, out_path: Path,
                 settings: Settings) -> Path:
    """Une segmentos com transições xfade, mantendo o sincronismo do áudio.

    Cada segmento (exceto o último) foi renderizado com cauda extra = trans_dur,
    consumida pela sobreposição — a linha do tempo das frases não muda.
    """
    if len(segments) == 1:
        return concat_segments(segments, out_path, settings)
    if isinstance(transitions, str):
        transitions = [transitions] * (len(segments) - 1)
    lines = []
    offset = 0.0
    prev = "[0:v]"
    for k in range(1, len(segments)):
        offset += durations[k - 1]
        label = f"[v{k}]" if k < len(segments) - 1 else "[vout]"
        lines.append(f"{prev}[{k}:v]xfade=transition={transitions[k - 1]}:"
                     f"duration={trans_dur:.3f}:offset={offset:.3f}{label}")
        prev = f"[v{k}]"
    script = out_path.with_suffix(".filter")
    script.write_text(";\n".join(lines), encoding="utf-8")
    args = [settings.ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for s in segments:
        args += ["-i", str(s)]
    args += ["-filter_complex_script", str(script), "-map", "[vout]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
             "-pix_fmt", "yuv420p", str(out_path)]
    _run(args)
    return out_path


# ---------------------------------------------------------------- legendas
# filtros de cor/efeito aplicados ao vídeo final (antes das legendas)
FILTERS = {
    "none": ("Sem filtro", ""),
    "teal_orange": ("Cinema teal & orange",
                    "curves=red='0/0 0.5/0.53 1/1':blue='0/0.05 0.5/0.5 1/0.95',"
                    "eq=saturation=1.12:contrast=1.05"),
    "dark": ("Dark (contraste + vinheta)",
             "eq=contrast=1.12:brightness=-0.03:saturation=0.92,vignette=PI/5"),
    "noir": ("Noir P&B", "hue=s=0,eq=contrast=1.28:brightness=-0.02,vignette=PI/5"),
    "vintage": ("Vintage anos 70", "curves=vintage,vignette=PI/6"),
    "warm": ("Quente dourado", "colortemperature=temperature=4600,eq=saturation=1.08"),
    "cold": ("Frio azulado", "colortemperature=temperature=8800,eq=saturation=1.05"),
    "dream": ("Sonho (glow suave)", "gblur=sigma=0.9,eq=saturation=1.18:brightness=0.03"),
    "sharp": ("Nítido vibrante", "unsharp=5:5:0.8,eq=saturation=1.15:contrast=1.05"),
    "grain": ("Grão de filme", "noise=alls=7:allf=t+u"),
    "vhs": ("VHS retrô", "rgbashift=rh=2:bh=-2,noise=alls=9:allf=t,eq=saturation=0.9"),
    "vignette": ("Vinheta escura", "vignette=PI/4.6"),
}

KARAOKE_PRESETS = {
    "classic": {"label": "Clássico", "font": "Arial", "size": 64, "color": "#FFFFFF",
                "highlight": "#FFD400", "outline": 3, "shadow": 1,
                "uppercase": False, "grow": False, "box": False},
    "beast": {"label": "Impacto (bold)", "font": "Arial Black", "size": 86,
              "color": "#FFFFFF", "highlight": "#FFE600", "outline": 5, "shadow": 2,
              "uppercase": True, "grow": True, "box": False},
    "redalert": {"label": "Alerta vermelho", "font": "Impact", "size": 90,
                 "color": "#FFFFFF", "highlight": "#FF2A2A", "outline": 5, "shadow": 2,
                 "uppercase": True, "grow": True, "box": False},
    "minimal": {"label": "Minimal", "font": "Segoe UI", "size": 52, "color": "#EAEAEA",
                "highlight": "#FFFFFF", "outline": 2, "shadow": 0,
                "uppercase": False, "grow": False, "box": False},
    "neon": {"label": "Neon", "font": "Arial Black", "size": 70, "color": "#DFFBFF",
             "highlight": "#00E8FF", "outline": 3, "shadow": 0,
             "uppercase": True, "grow": True, "box": False},
    "ember": {"label": "Ember (dark)", "font": "Georgia", "size": 62, "color": "#F3E9DC",
              "highlight": "#FF6B35", "outline": 3, "shadow": 2,
              "uppercase": False, "grow": False, "box": False},
    "gold": {"label": "Dourado elegante", "font": "Georgia", "size": 64,
             "color": "#F5E9CE", "highlight": "#FFD700", "outline": 2, "shadow": 2,
             "uppercase": False, "grow": False, "box": False},
    "tiktok": {"label": "Caixa (TikTok)", "font": "Arial Black", "size": 62,
               "color": "#FFFFFF", "highlight": "#25F4EE", "outline": 4, "shadow": 0,
               "uppercase": False, "grow": False, "box": True},
    "box_dark": {"label": "Caixa escura", "font": "Segoe UI", "size": 58,
                 "color": "#FFFFFF", "highlight": "#FFD400", "outline": 5, "shadow": 0,
                 "uppercase": False, "grow": False, "box": True},
}


def _ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _fmt_time(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _chunk_words(words: list[dict], max_words: int = 7) -> list[list[dict]]:
    return [words[i:i + max_words] for i in range(0, len(words), max_words)]


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


GROW_TAG = "{\\fscx86\\fscy86\\t(0,140,\\fscx100\\fscy100)}"


def build_ass(timed_sentences: list[dict], opts: dict, karaoke: bool,
              dims: tuple[int, int] = (1920, 1080)) -> str:
    w, h = dims
    scale = h / 1080  # legendas proporcionais em 9:16 / 1:1
    align = {"bottom": 2, "center": 5, "top": 8}.get(opts.get("sub_position", "bottom"), 2)
    margin_v = round(h * 0.085) if align != 5 else 10
    margin_lr = round(w * 0.05)
    base = _ass_color(opts.get("sub_color", "#FFFFFF"))
    hilite = _ass_color(opts.get("sub_highlight", "#FFD400"))
    font = opts.get("sub_font", "Arial")
    size = round(int(opts.get("sub_size", 64)) * scale)
    outline = round(int(opts.get("sub_outline", 3)) * scale)
    shadow = round(int(opts.get("sub_shadow", 1)) * scale)
    upper = bool(opts.get("sub_uppercase", False))
    grow = bool(opts.get("sub_grow", False))
    box = bool(opts.get("sub_box", False))
    border_style = 3 if box else 1          # 3 = caixa opaca atrás do texto
    back = "&H60000000" if box else "&H90000000"
    k_tag = "kf" if opts.get("karaoke_mode", "kf") == "kf" else "k"  # kf = varredura
    primary, secondary = (hilite, base) if karaoke else (base, hilite)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{size},{primary},{secondary},&H00000000,{back},1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},{align},{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def word_text(word: str) -> str:
        return _ass_escape(word.upper() if upper else word)

    lines: list[str] = []
    prefix = GROW_TAG if grow else ""
    for sent in timed_sentences:
        words = sent.get("words") or []
        if karaoke and words:
            for chunk in _chunk_words(words):
                start, end = chunk[0]["s"], chunk[-1]["e"]
                parts, cursor = [prefix], start
                for wd in chunk:
                    gap = max(0, round((wd["s"] - cursor) * 100))
                    if gap > 3:
                        parts.append(f"{{\\k{gap}}}")
                    k = max(1, round((wd["e"] - max(wd["s"], cursor)) * 100))
                    parts.append(f"{{\\{k_tag}{k}}}{word_text(wd['w'])} ")
                    cursor = wd["e"]
                text = "".join(parts).rstrip()
                lines.append(f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(end)},Sub,,0,0,0,,{text}")
        else:
            text = prefix + word_text(sent["text"]) if not karaoke else prefix + _ass_escape(sent["text"])
            lines.append(f"Dialogue: 0,{_fmt_time(sent['start'])},{_fmt_time(sent['end'])},Sub,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"


def build_srt(timed_sentences: list[dict]) -> str:
    def fmt(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"
    out = []
    for n, s in enumerate(timed_sentences, 1):
        out.append(f"{n}\n{fmt(s['start'])} --> {fmt(s['end'])}\n{s['text']}\n")
    return "\n".join(out)


# ------------------------------------------------------------ passada final
def final_mux(base_video: Path, narration: Path, out_path: Path, settings: Settings,
              ass_file: Path | None = None, bgm: Path | None = None,
              bgm_volume: float = 0.18, color_filter: str = "") -> Path:
    """Junta vídeo + narração (+ trilha com ducking), aplica filtro de cor,
    fades e queima legendas."""
    vid_dur = probe_duration(base_video, settings)
    fade_out_st = max(0.0, vid_dur - 0.8)

    args = [settings.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", base_video.name, "-i", str(narration)]
    if bgm:
        args += ["-stream_loop", "-1", "-i", str(bgm)]
        afilter = (
            f"[2:a]volume={bgm_volume}[bg];"
            f"[bg][1:a]sidechaincompress=threshold=0.06:ratio=10:attack=8:release=500[duck];"
            f"[1:a][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix];"
            f"[mix]afade=t=in:st=0:d=0.25,afade=t=out:st={fade_out_st:.2f}:d=0.8[aout]"
        )
    else:
        afilter = f"[1:a]afade=t=in:st=0:d=0.25,afade=t=out:st={fade_out_st:.2f}:d=0.8[aout]"
    args += ["-filter_complex", afilter, "-map", "0:v", "-map", "[aout]"]

    vf_parts = []
    if color_filter:
        vf_parts.append(color_filter)  # antes das legendas: texto fica limpo
    if ass_file:
        # cwd na pasta do arquivo evita escaping de caminho no Windows
        vf_parts.append(f"ass={ass_file.name}")
    vf_parts.append("fade=t=in:st=0:d=0.35")
    vf_parts.append(f"fade=t=out:st={fade_out_st:.2f}:d=0.8")
    args += ["-vf", ",".join(vf_parts)]

    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             "-shortest", out_path.name]
    _run(args, cwd=out_path.parent)
    return out_path
