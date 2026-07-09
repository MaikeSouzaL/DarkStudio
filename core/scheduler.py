"""Agendador de produção — a fábrica automática do DarkStudio.

O usuário programa: ideias + dia/hora de produção + (opcional) publicação
automática no YouTube. Um thread de fundo produz cada vídeo na hora marcada:

  ideia → roteiro (IA) → narração → sincronia → prompts → imagens → animação
        → render final → kit de publicação → upload agendado no YouTube

Os jobs ficam em schedule.json (sobrevivem a reinícios; produções atrasadas
rodam assim que o app abre). Rode headless com:  python cli.py --scheduler
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from . import pipeline, youtube
from .config import ROOT_DIR, Settings
from .llm import LLM
from .project import Project

SCHEDULE_FILE = ROOT_DIR / "schedule.json"
_LOCK = threading.Lock()


# ------------------------------------------------------------------ store
def load_jobs() -> list[dict]:
    with _LOCK:
        if not SCHEDULE_FILE.exists():
            return []
        try:
            return json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []


def _save(jobs: list[dict]) -> None:
    SCHEDULE_FILE.write_text(json.dumps(jobs, indent=2, ensure_ascii=False),
                             encoding="utf-8")


def save_jobs(jobs: list[dict]) -> None:
    with _LOCK:
        _save(jobs)


def update_job(job_id: str, **fields) -> None:
    with _LOCK:
        jobs = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8")) \
            if SCHEDULE_FILE.exists() else []
        for j in jobs:
            if j["id"] == job_id:
                j.update(fields)
        _save(jobs)


def add_jobs(ideas: list[str], run_at: datetime, cfg: dict, upload: dict) -> int:
    """Cria um job por ideia. Publicações são espaçadas por upload['interval_h']."""
    jobs = load_jobs()
    first_pub = upload.get("publish_first_at")
    interval = float(upload.get("interval_h") or 24)
    for k, idea in enumerate(ideas):
        pub_at = None
        if upload.get("enabled") and first_pub:
            pub_at = (datetime.fromisoformat(first_pub)
                      + timedelta(hours=interval * k)).isoformat(timespec="minutes")
        jobs.append({
            "id": f"job-{int(time.time() * 1000)}-{k}",
            "idea": idea,
            "run_at": run_at.isoformat(timespec="minutes"),
            "created": datetime.now().isoformat(timespec="minutes"),
            "cfg": cfg,
            "upload": {"enabled": bool(upload.get("enabled")),
                       "privacy": upload.get("privacy", "private"),
                       "publish_at": pub_at},
            "status": "pending", "project": None, "url": None, "error": None,
        })
    save_jobs(jobs)
    return len(ideas)


def delete_job(job_id: str) -> None:
    save_jobs([j for j in load_jobs() if j["id"] != job_id])


# ----------------------------------------------------------------- runner
class Scheduler:
    def __init__(self, settings: Settings, ui_job=None):
        self.settings = settings
        self.ui_job = ui_job          # objeto Job da UI (progresso compartilhado)
        self.current: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="darkstudio-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _busy(self) -> bool:
        return bool(self.ui_job and self.ui_job.running and self.current is None)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not self._busy():
                    due = [j for j in load_jobs() if j["status"] == "pending"
                           and datetime.fromisoformat(j["run_at"]) <= datetime.now()]
                    due.sort(key=lambda j: (j["run_at"], j["created"]))
                    if due:
                        self._run_job(due[0])
            except Exception:
                traceback.print_exc()
            self._stop.wait(20)

    # -------------------------------------------------------------- job
    def _progress(self, stage: str, i: int, n: int, msg: str = "") -> None:
        if self.ui_job:
            self.ui_job.cb(stage, i, n, f"[agendado] {msg}")

    def _run_job(self, j: dict) -> None:
        self.current = j["id"]
        if self.ui_job:
            self.ui_job.running = True
        pipeline.CANCEL.clear()
        update_job(j["id"], status="running", error=None)
        try:
            cfg = j.get("cfg", {})
            llm = LLM(self.settings)
            if not llm.available:
                raise RuntimeError("GEMINI_API_KEY ausente — necessária para o roteiro")

            self._progress("batch", 0, 1, f"Roteiro: {j['idea'][:50]}…")
            script = llm.generate_script(j["idea"], float(cfg.get("minutes", 3)),
                                         cfg.get("tone", "mistério e suspense"),
                                         cfg.get("language", "pt-BR"),
                                         niche=cfg.get("niche", ""))

            project = Project.create(j["idea"][:48])
            from .vconfig import apply_config, resolve_auto
            project.set_script(script, cfg.get("language", "pt-BR"))
            apply_config(project, resolve_auto(cfg, j["idea"], script, llm))
            project.save()
            update_job(j["id"], project=project.slug)

            # Automático desligado no agendador → só cria o projeto com roteiro
            if not cfg.get("auto_produce", True):
                update_job(j["id"], status="done")
                self._progress("script", 1, 1, f"Roteiro pronto: {j['idea'][:40]}")
                return

            final = pipeline.run_full(project, self.settings, self._progress)

            try:
                pipeline.run_publish_kit(project, self.settings, self._progress)
            except Exception as e:
                self._progress("export", 1, 1, f"kit falhou (seguindo): {e}")

            url = None
            up = j.get("upload", {})
            if up.get("enabled") and youtube.available():
                self._progress("export", 0, 1, "Enviando para o YouTube…")
                pub = project.state.get("publish", {})
                kit = pub.get("kit") or {}
                titles = kit.get("titles") or [project.state["name"]]
                thumbs = [project.dir / t for t in (pub.get("thumbs") or [])
                          if (project.dir / t).exists()]
                publish_at = None
                if up.get("publish_at"):
                    publish_at = datetime.fromisoformat(up["publish_at"]).astimezone()
                url = youtube.upload_video(
                    final, titles[0], kit.get("description", ""),
                    kit.get("tags", []), up.get("privacy", "private"),
                    publish_at, thumbs[0] if thumbs else None)

            update_job(j["id"], status="done", url=url)
            self._progress("export", 1, 1, f"Concluído: {j['idea'][:40]}")
        except pipeline.Cancelled:
            update_job(j["id"], status="pending")  # volta pra fila
        except Exception as e:
            update_job(j["id"], status="error", error=str(e)[:500])
        finally:
            self.current = None
            if self.ui_job:
                self.ui_job.running = False
