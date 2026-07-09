"""Configuração completa de vídeo — usada por Lote e Agendador.

Um único dict com TODAS as opções de todas as etapas do pipeline. A UI monta
o formulário a partir daqui e `apply_config` grava tudo no projeto, para que a
produção automática fique idêntica ao que se faria clicando etapa por etapa.
"""
from __future__ import annotations

from .editor import KARAOKE_PRESETS
from .project import Project

# Config padrão (espelha os defaults das telas do app)
DEFAULT_CONFIG: dict = {
    # geração de roteiro
    "minutes": 3, "tone": "mistério e suspense", "niche": "", "language": "pt-BR",
    "format": "16:9",
    # narração
    "tts_engine": "edge", "tts_voice": "pt-BR-AntonioNeural", "tts_rate": 0,
    "tts_style": "",
    # sincronia
    "whisper": "small",
    # estilo visual
    "style": "cinematic",
    # imagens
    "provider": "gemini", "use_refs": True,
    # animação
    "animate": True, "anim_provider": "kenburns",
    # exportação / legendas
    "preset": "classic", "karaoke": True, "karaoke_mode": "kf",
    "uppercase": False, "grow": False, "sub_position": "bottom",
    "subtitles_on": True, "transition": "fade", "transition_dur": 0.4,
    "filter": "none", "bgm_volume": 0.18, "bgm_path": "",
    # aparência da legenda (vazio = usa o que o preset define)
    "sub_font": "", "sub_size": 0, "sub_color": "", "sub_highlight": "",
    # toggles por seção: True = usa suas configs; False = IA/app escolhe sozinho
    "manual_content": True, "manual_narration": True,
    "manual_production": True, "manual_captions": True,
}


def resolve_auto(cfg: dict, idea: str, script: str, llm) -> dict:
    """Preenche as seções marcadas como automáticas (manual_*=False) com
    escolhas da IA (estilo/preset) e padrões sensatos. Retorna cfg resolvido."""
    from .editor import KARAOKE_PRESETS
    from .styles import STYLES

    c = dict(cfg)
    lang = c.get("language", "pt-BR")

    # narração automática → Edge (rápido/grátis) com voz padrão do idioma
    if not c.get("manual_narration", True):
        c["tts_engine"] = "edge"
        c["tts_voice"] = {"pt-BR": "pt-BR-AntonioNeural",
                          "es-ES": "es-ES-AlvaroNeural"}.get(lang, "en-US-ChristopherNeural")
        c["tts_rate"] = 0
        c["tts_style"] = ""

    # produção automática → imagens grátis + Ken Burns + whisper leve
    if not c.get("manual_production", True):
        c["provider"] = "pollinations"
        c["whisper"] = "small"
        c["animate"] = True
        c["anim_provider"] = "kenburns"
        c["use_refs"] = True

    # conteúdo/legendas automáticos → IA escolhe estilo visual e preset
    need_style = not c.get("manual_content", True)
    need_preset = not c.get("manual_captions", True)
    if (need_style or need_preset) and llm is not None and llm.available:
        try:
            styles = {k: v["label"] for k, v in STYLES.items() if k != "custom"}
            presets = {k: v["label"] for k, v in KARAOKE_PRESETS.items()}
            pick = llm.auto_pick(idea or script[:300], c.get("tone", ""),
                                 styles, presets)
            if need_style and pick.get("style") in STYLES:
                c["style"] = pick["style"]
            if need_preset and pick.get("preset") in KARAOKE_PRESETS:
                c["preset"] = pick["preset"]
        except Exception:
            pass
    if need_captions_defaults := (not c.get("manual_captions", True)):
        c["karaoke"] = True
        c["karaoke_mode"] = "kf"
        c["subtitles_on"] = True
        c["transition"] = "fade"
        c["filter"] = "none"
        c["sub_font"] = c["sub_size"] = c["sub_color"] = c["sub_highlight"] = ""
    return c


def merged(overrides: dict | None = None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def apply_config(project: Project, cfg: dict) -> None:
    """Aplica a config completa ao estado do projeto (todas as etapas)."""
    c = merged(cfg)
    project.state["format"] = c["format"]

    project.state["tts"].update({
        "engine": c["tts_engine"], "voice": c["tts_voice"],
        "rate": int(c["tts_rate"]), "style": c["tts_style"]})

    project.state["transcription"]["model"] = c["whisper"]
    project.state["style"]["id"] = c["style"]
    project.state["images"].update({"provider": c["provider"],
                                    "use_refs": bool(c["use_refs"])})
    project.state["animation"].update({
        "enabled": bool(c["animate"]),
        "provider": c["anim_provider"] if c["animate"] else "kenburns"})

    pr = KARAOKE_PRESETS.get(c["preset"], KARAOKE_PRESETS["classic"])
    project.state["export"].update({
        "sub_preset": c["preset"], "sub_font": pr["font"], "sub_size": pr["size"],
        "sub_color": pr["color"], "sub_highlight": pr["highlight"],
        "sub_outline": pr["outline"], "sub_shadow": pr["shadow"],
        "sub_uppercase": bool(c["uppercase"]), "sub_grow": bool(c["grow"]),
        "sub_box": pr.get("box", False), "sub_position": c["sub_position"],
        "karaoke": bool(c["karaoke"]), "karaoke_mode": c["karaoke_mode"],
        "subtitles_on": bool(c["subtitles_on"]), "transition": c["transition"],
        "transition_dur": float(c["transition_dur"]), "filter": c["filter"],
        "bgm_volume": float(c["bgm_volume"])})
    # aparência custom da legenda sobrescreve o preset (se preenchida)
    exp = project.state["export"]
    if c.get("sub_font"):
        exp["sub_font"] = c["sub_font"]
    if c.get("sub_size"):
        exp["sub_size"] = int(c["sub_size"])
    if c.get("sub_color"):
        exp["sub_color"] = c["sub_color"]
    if c.get("sub_highlight"):
        exp["sub_highlight"] = c["sub_highlight"]

    # trilha de fundo única para todos os vídeos do lote/agenda
    bgm = (c.get("bgm_path") or "").strip().strip('"')
    if bgm:
        import shutil
        from pathlib import Path
        src = Path(bgm)
        if src.is_file():
            dest = project.path("assets", f"bgm{src.suffix or '.mp3'}")
            shutil.copy2(src, dest)
            project.state["export"]["bgm"] = project.rel(dest)
