"""CLI do DarkStudio — roda o pipeline completo sem abrir a interface.

Exemplos:
  python cli.py --demo                                # teste rápido offline (mock)
  python cli.py --name "Meu vídeo" --script roteiro.txt --style cinematic \
                --provider gemini --animate kenburns --karaoke
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# console do Windows costuma ser cp1252 — evita crash com acentos/emoji
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from core import pipeline
from core.config import settings
from core.project import Project

DEMO_SCRIPT = (
    "Em uma noite silenciosa, uma cidade inteira desapareceu do mapa. "
    "Ninguém sabe explicar o que aconteceu naquele lugar. "
    "Mas os registros encontrados revelam algo perturbador. "
    "Esta é a história que tentaram esconder de você."
)


def progress(stage: str, i: int, n: int, msg: str = "") -> None:
    bar = f"[{stage:>13}] {i}/{n}"
    print(f"{bar} {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="DarkStudio CLI")
    ap.add_argument("--demo", action="store_true", help="pipeline de teste offline (mock)")
    ap.add_argument("--name", default=None)
    ap.add_argument("--script", default=None, help="arquivo .txt com o roteiro")
    ap.add_argument("--language", default="pt-BR")
    ap.add_argument("--engine", default="edge", help="edge|kokoro|chatterbox|mock")
    ap.add_argument("--voice", default="pt-BR-AntonioNeural")
    ap.add_argument("--whisper", default=None, help="tiny|base|small|medium")
    ap.add_argument("--style", default="cinematic")
    ap.add_argument("--provider", default="gemini", help="gemini|pollinations|mock")
    ap.add_argument("--animate", default="off", help="off|kenburns|veo")
    ap.add_argument("--karaoke", action="store_true")
    ap.add_argument("--bgm", default=None, help="arquivo de trilha sonora")
    ap.add_argument("--format", default="16:9", choices=["16:9", "9:16", "1:1"])
    ap.add_argument("--transition", default="fade",
                    help="none|fade|fadeblack|dissolve|random|… (ver editor.TRANSITIONS)")
    ap.add_argument("--preset", default="classic",
                    help="classic|beast|redalert|minimal|neon|ember|gold|tiktok|box_dark")
    ap.add_argument("--filter", default="none", dest="color_filter",
                    help="none|teal_orange|dark|noir|vintage|warm|cold|dream|sharp|grain|vhs|vignette")
    ap.add_argument("--scheduler", action="store_true",
                    help="roda o agendador headless (produz os jobs de schedule.json)")
    args = ap.parse_args()

    if args.scheduler:
        from core.scheduler import Scheduler
        s = Scheduler(settings)
        s.start()
        print("Agendador rodando — jobs em schedule.json (Ctrl+C para sair)")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            return 0

    if args.demo:
        args.name = args.name or f"demo-{int(time.time())}"
        script_text = DEMO_SCRIPT
        args.provider = "mock"
        args.engine = args.engine if args.engine != "edge" else "edge"
        args.whisper = args.whisper or "tiny"
        args.animate = "kenburns"
        args.karaoke = True
    else:
        if not args.script or not args.name:
            ap.error("--name e --script são obrigatórios (ou use --demo)")
        script_text = Path(args.script).read_text(encoding="utf-8")

    t0 = time.time()
    project = Project.create(args.name)
    print(f"Projeto: {project.dir}")

    project.state["format"] = args.format
    project.set_script(script_text, args.language)
    print(f"Frases: {len(project.sentences)} | formato: {args.format}")

    project.state["tts"].update({"engine": args.engine, "voice": args.voice})
    try:
        pipeline.run_tts(project, settings, progress)
    except Exception as e:
        if args.demo and args.engine == "edge":
            print(f"edge-tts falhou ({e}); usando TTS de teste offline…")
            project.state["tts"].update({"engine": "mock", "voice": "mock"})
            pipeline.run_tts(project, settings, progress)
        else:
            raise
    print(f"Áudio: {project.state['tts']['audio']} ({project.state['tts']['duration']:.1f}s)")

    project.state["transcription"]["model"] = args.whisper or settings.whisper_model
    pipeline.run_transcription(project, settings, progress)

    project.state["style"]["id"] = args.style
    pipeline.run_style_prompts(project, settings, progress)

    project.state["images"]["provider"] = args.provider
    pipeline.run_images(project, settings, progress)

    project.state["animation"]["enabled"] = args.animate != "off"
    project.state["animation"]["provider"] = args.animate if args.animate != "off" else "kenburns"
    pipeline.run_animation(project, settings, progress)

    from core.editor import KARAOKE_PRESETS
    exp = project.state["export"]
    exp["karaoke"] = bool(args.karaoke)
    exp["transition"] = args.transition
    pr = KARAOKE_PRESETS.get(args.preset, KARAOKE_PRESETS["classic"])
    exp.update({"sub_preset": args.preset, "sub_font": pr["font"], "sub_size": pr["size"],
                "sub_color": pr["color"], "sub_highlight": pr["highlight"],
                "sub_outline": pr["outline"], "sub_shadow": pr["shadow"],
                "sub_uppercase": pr["uppercase"], "sub_grow": pr["grow"],
                "sub_box": pr.get("box", False), "filter": args.color_filter})
    if args.bgm:
        exp["bgm"] = args.bgm
    final = pipeline.run_export(project, settings, progress)

    print(f"\n✅ Vídeo final: {final}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
