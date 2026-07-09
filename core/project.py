"""Projeto DarkStudio: estado persistido em projects/<slug>/project.json."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import PROJECTS_DIR
from .textproc import slugify, split_sentences

# Ordem do pipeline — refazer uma etapa invalida as seguintes
STAGES = ["script", "tts", "transcription", "style", "images", "animation", "export"]


def _default_state(name: str) -> dict:
    return {
        "name": name,
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "format": "16:9",
        "publish": {"kit": None, "thumbs": []},
        "script": {"text": "", "language": "pt-BR", "sentences": [], "done": False},
        "tts": {"engine": "edge", "voice": "pt-BR-AntonioNeural", "rate": 0, "style": "",
                "audio": None, "duration": 0.0, "done": False},
        "transcription": {"model": "small", "sentences": [], "done": False},
        "style": {"id": "cinematic", "custom_style": None, "analysis": None,
                  "prompts": [], "char_refs": [], "done": False},
        "images": {"provider": "gemini", "files": [], "use_refs": True, "done": False},
        "animation": {"enabled": False, "provider": "kenburns", "plans": [],
                      "clips": [], "done": False},
        "export": {"karaoke": True, "sub_preset": "classic", "sub_font": "Arial",
                   "sub_size": 64, "sub_color": "#FFFFFF", "sub_highlight": "#FFD400",
                   "sub_position": "bottom", "sub_outline": 3, "sub_shadow": 1,
                   "sub_uppercase": False, "sub_grow": False, "sub_box": False,
                   "karaoke_mode": "kf", "filter": "none",
                   "transition": "fade", "transition_dur": 0.4,
                   "bgm": None, "bgm_volume": 0.18, "file": None, "done": False},
    }


class Project:
    def __init__(self, slug: str, state: dict):
        self.slug = slug
        self.state = state

    # -------------------------------------------------- caminhos
    @property
    def dir(self) -> Path:
        return PROJECTS_DIR / self.slug

    def path(self, *parts: str) -> Path:
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def rel(self, p: Path) -> str:
        return p.relative_to(self.dir).as_posix()

    def clip_rel(self, i: int) -> str | None:
        """Caminho relativo do clipe da cena i se ele existir no disco.

        O disco é a fonte da verdade: um clipe já renderizado conta como feito
        mesmo que a lista em memória/JSON tenha se dessincronizado."""
        p = self.dir / "clips" / f"clip_{i:03d}.mp4"
        return self.rel(p) if p.exists() else None

    # -------------------------------------------------- persistência
    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        f = self.dir / "project.json"
        f.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def create(cls, name: str) -> "Project":
        slug = slugify(name)
        base = slug
        i = 2
        while (PROJECTS_DIR / slug / "project.json").exists():
            slug = f"{base}-{i}"
            i += 1
        p = cls(slug, _default_state(name))
        p.save()
        return p

    @classmethod
    def load(cls, slug: str) -> "Project | None":
        f = PROJECTS_DIR / slug / "project.json"
        if not f.exists():
            return None
        state = _default_state(slug)
        try:
            saved = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None
        # merge raso preservando chaves novas de versões futuras
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(state.get(k), dict):
                state[k].update(v)
            else:
                state[k] = v
        return cls(slug, state)

    @classmethod
    def list_all(cls) -> list["Project"]:
        out = []
        if PROJECTS_DIR.exists():
            for d in sorted(PROJECTS_DIR.iterdir()):
                if (d / "project.json").exists():
                    p = cls.load(d.name)
                    if p:
                        out.append(p)
        return out

    # -------------------------------------------------- pipeline
    def set_script(self, text: str, language: str) -> None:
        st = self.state["script"]
        text = text.strip()
        changed = (text != st["text"]) or (language != st["language"])
        st["text"] = text
        st["language"] = language
        st["sentences"] = split_sentences(text)
        st["done"] = bool(st["sentences"])
        if changed:
            # roteiro novo = vídeo novo: NUNCA reaproveitar dados do anterior
            self.reset_derived_data()
        self.invalidate_after("script")
        self.save()

    def clear_images(self) -> None:
        """Apaga as imagens geradas (arquivos no disco + lista) e os clipes de
        animação que dependem delas. Usado ao trocar estilo/regerar prompts."""
        img_dir = self.dir / "images"
        if img_dir.exists():
            for f in img_dir.glob("scene_*.jpg"):
                f.unlink(missing_ok=True)
        clip_dir = self.dir / "clips"
        if clip_dir.exists():
            for f in clip_dir.glob("clip_*.mp4"):
                f.unlink(missing_ok=True)
        self.state["images"].update({"files": [], "done": False})
        self.state["animation"].update({"plans": [], "clips": [], "done": False})

    def reset_derived_data(self) -> None:
        """Limpa tudo que foi gerado a partir do roteiro anterior."""
        self.state["tts"].update({"audio": None, "duration": 0.0, "done": False})
        self.state["transcription"].update({"sentences": [], "done": False})
        self.state["style"].update({"analysis": None, "prompts": [], "scenes": [],
                                    "char_refs": [], "done": False})
        self.clear_images()
        self.state["export"].update({"file": None, "done": False})

    def invalidate_after(self, stage: str) -> None:
        """Marca etapas posteriores como pendentes (dados ficam, mas precisam refazer)."""
        if stage not in STAGES:
            return
        for s in STAGES[STAGES.index(stage) + 1:]:
            self.state[s]["done"] = False

    def stage_done(self, stage: str) -> bool:
        """Estado derivado dos DADOS reais (não de flags que dessincronizam)."""
        s = self.state
        n = len(s["script"]["sentences"])
        if stage == "script":
            return n > 0
        if stage == "tts":
            rel = s["tts"].get("audio")
            return bool(rel) and (self.dir / rel).exists()
        if stage == "transcription":
            return n > 0 and len(s["transcription"].get("sentences") or []) == n
        if stage == "style":
            return n > 0 and len(s["style"].get("prompts") or []) == n
        if stage == "images":
            prompts = s["style"].get("prompts") or []
            files = s["images"].get("files") or []
            return bool(prompts) and sum(1 for f in files if f) == len(prompts)
        if stage == "animation":
            a = s["animation"]
            return (not a.get("enabled")) or bool(a.get("plans"))
        if stage == "export":
            rel = s["export"].get("file")
            return bool(rel) and (self.dir / rel).exists()
        return bool(self.state.get(stage, {}).get("done"))

    @property
    def sentences(self) -> list[str]:
        return self.state["script"]["sentences"]

    @property
    def timed_sentences(self) -> list[dict]:
        return self.state["transcription"]["sentences"]
