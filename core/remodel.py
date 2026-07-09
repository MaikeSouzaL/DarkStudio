"""Remodelagem de canal — minerar o que já funciona e recriar melhor.

Fluxo: URL do canal → top vídeos por visualização (yt-dlp, sem chave) →
legenda/transcrição do vídeo escolhido → IA reescreve a narrativa do zero
(sem copiar frases) → novo projeto pronto para o pipeline.

Nota: o YouTube não expõe receita de terceiros; visualizações são o melhor
indicador público de sucesso. Use como pesquisa criativa — a reescrita gera
texto original, mas confira direitos sobre histórias/fatos exclusivos.
"""
from __future__ import annotations

import re

import httpx


def _channel_videos_url(channel_url: str) -> str:
    url = channel_url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://www.youtube.com/" + url  # aceita "@handle" ou nome do canal
    if not re.search(r"/(videos|shorts|streams)$", url):
        url += "/videos"
    return url


def top_videos(channel_url: str, limit: int = 12) -> list[dict]:
    """Lista os vídeos mais vistos do canal (até ~200 mais recentes analisados)."""
    import yt_dlp

    opts = {"extract_flat": True, "quiet": True, "no_warnings": True,
            "playlistend": 200, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_channel_videos_url(channel_url), download=False)
    entries = info.get("entries") or []
    vids = []
    for e in entries:
        if not e or not e.get("id"):
            continue
        vids.append({
            "id": e["id"],
            "title": e.get("title") or "(sem título)",
            "views": int(e.get("view_count") or 0),
            "duration": int(e.get("duration") or 0),
            "url": f"https://www.youtube.com/watch?v={e['id']}",
        })
    vids.sort(key=lambda v: v["views"], reverse=True)
    return vids[:limit]


def video_details(video_url: str) -> dict:
    """Metadados públicos completos de um vídeo (data, views, likes, duração)."""
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
    return {
        "upload_date": info.get("upload_date"),          # YYYYMMDD
        "view_count": int(info.get("view_count") or 0),
        "like_count": int(info.get("like_count") or 0),
        "duration": int(info.get("duration") or 0),
        "title": info.get("title"),
    }


def study_channel(channel_url: str, limit: int = 12, progress=None) -> dict:
    """Estudo completo: dados do canal + detalhes de cada top vídeo."""
    from datetime import datetime

    from .agents import fetch_channel_public

    if progress:
        progress("Coletando dados públicos do canal…")
    data = fetch_channel_public(channel_url)
    vids = data.get("top_videos", [])[:limit]
    for i, v in enumerate(vids, 1):
        if progress:
            progress(f"Analisando vídeo {i}/{len(vids)}: {v['title'][:40]}…")
        try:
            det = video_details(v["url"])
            v.update({k: det[k] for k in ("upload_date", "like_count") if det.get(k)})
            v["views"] = det["view_count"] or v["views"]
            v["duration"] = det["duration"] or v["duration"]
        except Exception:
            pass
        # velocidade: views por mês desde a publicação
        try:
            up = datetime.strptime(v["upload_date"], "%Y%m%d")
            months = max(1.0, (datetime.now() - up).days / 30.4)
            v["months"] = round(months, 1)
            v["views_month"] = int(v["views"] / months)
        except Exception:
            v["months"] = None
            v["views_month"] = None
    data["top_videos"] = vids
    data["total_top_views"] = sum(v["views"] for v in vids)
    return data


def apply_earnings(videos: list[dict], rpm_min: float, rpm_max: float) -> None:
    """Estimativa de ganho por vídeo: views/1000 × faixa de RPM do nicho."""
    for v in videos:
        v["earn_min"] = round(v["views"] / 1000 * rpm_min)
        v["earn_max"] = round(v["views"] / 1000 * rpm_max)
        if v.get("views_month"):
            v["earn_month_min"] = round(v["views_month"] / 1000 * rpm_min)
            v["earn_month_max"] = round(v["views_month"] / 1000 * rpm_max)


_CLEAN_RE = re.compile(r"\[(?:música|music|aplausos|applause|risos)\]", re.IGNORECASE)


def get_transcript(video_url: str, prefer_langs: tuple[str, ...] = ("pt", "en", "es")) -> str:
    """Extrai a legenda (manual ou automática) do vídeo como texto corrido."""
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=False)

    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    def pick(source: dict) -> dict | None:
        for pref in prefer_langs:
            for lang, fmts in source.items():
                if lang.lower().startswith(pref):
                    for f in fmts:
                        if f.get("ext") == "json3":
                            return f
                    if fmts:
                        return fmts[0]
        return None

    fmt = pick(manual) or pick(auto)
    if not fmt:
        raise RuntimeError("Este vídeo não tem legenda disponível (nem automática).")

    with httpx.Client(timeout=120, follow_redirects=True) as client:
        r = client.get(fmt["url"])
        r.raise_for_status()

    if fmt.get("ext") == "json3":
        data = r.json()
        parts = []
        for ev in data.get("events", []):
            for seg in ev.get("segs", []) or []:
                t = seg.get("utf8", "")
                if t and t != "\n":
                    parts.append(t)
        text = "".join(parts)
    else:  # vtt/srv: remove timestamps e tags
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"^\s*\d{2}:\d{2}.*$", " ", text, flags=re.MULTILINE)
        text = re.sub(r"WEBVTT.*?\n", " ", text)

    text = _CLEAN_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 200:
        raise RuntimeError("Legenda muito curta — este vídeo não serve para remodelar.")
    return text
