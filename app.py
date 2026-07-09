"""DarkStudio — estúdio desktop de vídeos narrados por IA.

Roteiro → Narração TTS → Sincronia (faster-whisper) → Estilo visual → Imagens IA
→ Animação → MP4 final com karaokê, pronto para o YouTube.

Execução:
    python app.py           # janela desktop nativa (padrão)
    python app.py --web     # modo navegador (desenvolvimento) em :8420
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from nicegui import app, run, ui

from core import pipeline, remodel, scheduler as sched, tts, voices as vlib, youtube
from core.config import PROVIDER_LINKS
from core.vconfig import DEFAULT_CONFIG, merged
from core.agents import (AGENTS, NICHE_CATALOG, NICHES, Crew, fetch_channel_public,
                         niche_count)


def niche_select(label: str = "Nicho", value: str | None = None, classes: str = "grow"):
    """Select de nicho com busca por digitação e valor livre (nicho personalizado)."""
    sel = ui.select(NICHES, value=value or NICHES[0], label=label,
                    with_input=True, new_value_mode="add-unique") \
        .props("outlined dense use-input input-debounce=0 behavior=menu") \
        .classes(classes)
    with sel:
        ui.tooltip(f"{niche_count()} nichos catalogados — digite para buscar "
                   "ou escreva o seu próprio")
    return sel
from core.config import FORMATS, PROJECTS_DIR, settings
from core.editor import CAMERA_LABELS, FILTERS, KARAOKE_PRESETS, TRANSITIONS
from core.imagen import PROVIDERS
from core.llm import LLM
from core.project import Project
from core.styles import STYLES
from ui import theme

# ----------------------------------------------------------------- estado
STEPS = [
    ("script", "Roteiro", "edit_note", "Cada frase do roteiro vira uma cena do vídeo"),
    ("tts", "Narração", "mic", "Voz neural que dá vida ao texto"),
    ("transcription", "Sincronia", "av_timer", "Tempo exato de cada frase e palavra"),
    ("style", "Estilo Visual", "palette", "Engenharia de prompt para cada estilo"),
    ("images", "Imagens", "image", "Uma imagem gerada por IA para cada frase"),
    ("animation", "Animação", "movie_filter", "Movimento de câmera decidido pela IA"),
    ("export", "Exportar", "rocket_launch", "Edição final sincronizada com karaokê"),
]
STEP_IDS = [s[0] for s in STEPS]
LANGUAGES = {"pt-BR": "Português (Brasil)", "en-US": "English (US)", "es-ES": "Español"}


class State:
    def __init__(self):
        self.project: Project | None = None
        self.step: str = "script"


class Job:
    def __init__(self):
        self.running = False
        self.i, self.n, self.msg = 0, 1, ""

    def cb(self, stage: str, i: int, n: int, msg: str = ""):
        self.i, self.n, self.msg = i, max(n, 1), msg

    @property
    def fraction(self) -> float:
        return min(1.0, self.i / self.n) if self.n else 0.0


state = State()
job = Job()
app.add_media_files("/media", str(PROJECTS_DIR))
app.add_media_files("/voices", str(vlib.VOICES_DIR))


def voice_url(path: Path) -> str:
    rel = Path(path).relative_to(vlib.VOICES_DIR).as_posix()
    v = int(Path(path).stat().st_mtime) if Path(path).exists() else 0
    return f"/voices/{rel}?v={v}"

# agendador de produção automática (thread de fundo, jobs em schedule.json)
_scheduler = sched.Scheduler(settings, ui_job=job)
app.on_startup(_scheduler.start)


def _pregen_edge_samples():
    """Deixa as amostras das vozes Edge (grátis) prontas de fábrica, em background."""
    import threading

    def worker():
        samples = vlib.VOICES_DIR / "_samples"
        for lang in ("pt-BR", "en-US", "es-ES"):
            try:
                tts.pregenerate_samples(samples, "edge", lang)
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True, name="pregen-edge").start()


app.on_startup(_pregen_edge_samples)


def media_url(rel: str) -> str:
    p = state.project.dir / rel
    v = int(p.stat().st_mtime) if p.exists() else 0
    return f"/media/{state.project.slug}/{rel}?v={v}"


def open_folder(path: Path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


async def run_stage(func, *args, success: str = "Concluído", chain: bool = True):
    if job.running:
        ui.notify("Aguarde a tarefa atual terminar", type="warning")
        return
    job.running = True
    job.i, job.n, job.msg = 0, 1, "Preparando…"
    pipeline.CANCEL.clear()
    refresh_all()
    ok = False
    try:
        await run.io_bound(func, state.project, settings, job.cb, *args)
        ui.notify(success, type="positive", position="top")
        ok = True
    except pipeline.Cancelled:
        ui.notify("Tarefa cancelada", type="warning", position="top")
    except Exception as e:
        ui.notify(f"Erro: {e}", type="negative", position="top",
                  multi_line=True, timeout=12000, close_button=True)
    finally:
        job.running = False
        refresh_all()
    # piloto automático: encadeia a próxima etapa pendente
    if ok and chain and app.storage.general.get("autopilot"):
        await _autopilot_next()


# etapas que o piloto automático sabe executar sozinho (script é manual)
AUTO_FUNCS = {
    "tts": pipeline.run_tts,
    "transcription": pipeline.run_transcription,
    "style": pipeline.run_style_prompts,
    "images": pipeline.run_images,
    "animation": pipeline.run_animation,
    "export": pipeline.run_export,
}
_AUTO_MSG = {"tts": "Gerando narração…", "transcription": "Sincronizando…",
             "style": "Criando prompts…", "images": "Gerando imagens…",
             "animation": "Planejando animação…", "export": "Renderizando vídeo…"}


async def _autopilot_next():
    """Executa a próxima etapa pendente automaticamente (até o vídeo final)."""
    p = state.project
    if not p or job.running:
        return
    for stage in ("tts", "transcription", "style", "images", "animation", "export"):
        if not p.stage_done(stage):
            state.step = stage
            refresh_all()
            await run_stage(AUTO_FUNCS[stage], success=f"{_AUTO_MSG[stage]} ✔")
            return
    ui.notify("Piloto automático: vídeo finalizado! 🎬", type="positive",
              position="top", timeout=8000)


def _toggle_autopilot(value: bool):
    app.storage.general["autopilot"] = bool(value)
    if not value:
        return
    p = state.project
    pending = p and any(not p.stage_done(s) for s in AUTO_FUNCS) \
        and p.stage_done("script")
    if pending:
        ui.notify("Piloto automático LIGADO — produzindo as etapas restantes sozinho. "
                  "Os provedores pagos que você escolheu serão cobrados; use Pollinations/"
                  "Local para custo zero. Clique em Cancelar a qualquer momento.",
                  type="warning", position="top", timeout=10000)
        import asyncio
        asyncio.create_task(_autopilot_next())
    elif not (p and p.stage_done("script")):
        ui.notify("Salve o roteiro primeiro — depois o piloto produz o resto sozinho.",
                  type="info")


async def confirm_cost(count: int, unit_usd: float, what: str) -> bool:
    """Estimativa de custo antes de gerar em lote com API paga."""
    with ui.dialog() as dlg, ui.card().classes("card gap-3").style("width:440px"):
        ui.label("Custo estimado").classes("card-h")
        ui.label(f"{what}: {count} gerações ≈ US$ {count * unit_usd:.2f}") \
            .classes("text-base font-medium")
        ui.label("Estimativa aproximada — o valor real depende do modelo e da sua conta. "
                 "Ajuste os preços unitários em config.json.").classes("mut2 text-xs")
        with ui.row().classes("w-full justify-end gap-2"):
            theme.ghost_btn("Cancelar", lambda: dlg.submit(False))
            theme.primary_btn("Continuar", lambda: dlg.submit(True))
    return bool(await dlg)


def refresh_all():
    sidebar.refresh()
    content.refresh()
    header_status.refresh()


def goto(step: str):
    state.step = step
    refresh_all()


def step_unlocked(step: str) -> bool:
    p = state.project
    if not p:
        return step == "script"
    has_images = any(p.state["images"].get("files") or [])
    return {
        "script": True,
        "tts": p.stage_done("script"),
        "transcription": p.stage_done("tts"),
        "style": p.stage_done("script"),
        "images": p.stage_done("style"),
        "animation": p.stage_done("transcription") and has_images,
        "export": p.stage_done("transcription") and has_images,
    }[step]


def step_caption(sid: str) -> str:
    p = state.project
    if not p:
        return ""
    s = p.state
    if sid == "script":
        n = len(p.sentences)
        return f"{n} cenas" if n else "aguardando roteiro"
    if sid == "tts":
        if s["tts"].get("audio") and p.stage_done("tts"):
            v = s["tts"]["voice"]
            if v.startswith("lib:"):
                voice = "voz clonada " + v[4:].replace("-", " ").title()
            else:
                voice = v.split("-")[-1].replace("Neural", "").replace("Multilingual", "")
            return f"{s['tts'].get('duration', 0):.0f}s · {voice}"
        return "voz neural"
    if sid == "transcription":
        n = len(s["transcription"].get("sentences") or [])
        return f"{n} frases no tempo" if n and s["transcription"]["done"] else "faster-whisper"
    if sid == "style":
        style_id = s["style"]["id"]
        if style_id == "custom":
            return (s["style"].get("custom_style") or {}).get("name", "personalizado")
        return STYLES[style_id]["label"].split(" (")[0]
    if sid == "images":
        files = s["images"].get("files") or []
        total = len(s["style"].get("prompts") or [])
        done = sum(1 for f in files if f)
        return f"{done}/{total} geradas" if total else "aguardando prompts"
    if sid == "animation":
        if not s["animation"].get("enabled"):
            return "desligada"
        return "Veo 3.1" if s["animation"].get("provider") == "veo" else "Ken Burns IA"
    if sid == "export":
        return "MP4 pronto" if s["export"]["done"] else "1080p · karaokê"
    return ""


# ------------------------------------------------------------------ dialogs
def key_field(name: str, value: str, hint: str = ""):
    """Campo de chave com link clicável para obtê-la."""
    with ui.row().classes("w-full items-center justify-between no-wrap"):
        ui.label(name).classes("mut text-xs mono")
        link = PROVIDER_LINKS.get(name)
        if link:
            ui.link("obter chave ↗", link, new_tab=True).classes("text-xs") \
                .style("color:var(--acc)")
    field = ui.input(value=value, password=True, password_toggle_button=True) \
        .props("outlined dense").classes("w-full")
    if hint:
        ui.label(hint).classes("mut2 text-xs")
    return field


def settings_dialog():
    with ui.dialog() as dlg, ui.card().classes("card gap-4").style("width:600px;max-width:95vw"):
        ui.label("Configurações").classes("h-title").style("font-size:19px")
        key_in = key_field("GEMINI_API_KEY", settings.gemini_api_key,
                           "Google AI Studio — imagens (Nano Banana), prompts e Veo.")
        with ui.row().classes("w-full gap-3 no-wrap"):
            text_in = ui.input("Modelo de texto", value=settings.text_model).props("outlined dense").classes("grow")
            img_in = ui.input("Modelo de imagem", value=settings.image_model).props("outlined dense").classes("grow")
        with ui.row().classes("w-full gap-3 no-wrap"):
            veo_in = ui.input("Modelo Veo", value=settings.veo_model).props("outlined dense").classes("grow")
            whisper_in = ui.select(["tiny", "base", "small", "medium", "large-v3"],
                                   value=settings.whisper_model, label="Whisper padrão") \
                .props("outlined dense").classes("grow")

        with ui.expansion("Chaves opcionais — reservas e provedores grátis") \
                .classes("w-full").props("dense"):
            ui.html('<span class="pill ok"><i></i>Créditos do Gemini acabaram? '
                    'Configure o DeepSeek (texto) e use Pollinations/HF/Together '
                    '(imagens grátis) — o app continua produzindo.</span>')
            ds_in = key_field("DEEPSEEK_API_KEY", settings.deepseek_api_key,
                              "LLM reserva — roteiros/prompts seguem se o Gemini esgotar.")
            hf_in = key_field("HF_TOKEN", settings.hf_token,
                              "Imagens FLUX grátis (Hugging Face).")
            tg_in = key_field("TOGETHER_API_KEY", settings.together_api_key,
                              "Imagens FLUX grátis (Together AI).")
            el_in = key_field("ELEVENLABS_API_KEY", settings.elevenlabs_api_key,
                              "Narração premium (paga).")
            oa_in = key_field("OPENAI_API_KEY", settings.openai_api_key,
                              "Narração OpenAI (paga).")

        with ui.expansion("Higgsfield — Sora / Kling / Veo (pago)") \
                .classes("w-full").props("dense"):
            hg_in = key_field("HIGGSFIELD_API_KEY", settings.higgsfield_api_key,
                              "Agrega os melhores modelos de vídeo (Sora 2, Kling 3, "
                              "Veo 3.1, Seedance) num só lugar. Selecione 'Higgsfield' "
                              "no provedor de imagens ou na animação.")
            hg_sec = ui.input("HIGGSFIELD_SECRET (se sua conta exigir key+secret)",
                              value=settings.higgsfield_secret,
                              password=True, password_toggle_button=True) \
                .props("outlined dense").classes("w-full")
            with ui.row().classes("w-full gap-3 no-wrap"):
                hg_base = ui.input("Base da API", value=settings.higgsfield_base) \
                    .props("outlined dense").classes("grow")
                hg_vmodel = ui.input("Modelo de vídeo", value=settings.higgsfield_video_model) \
                    .props("outlined dense").classes("w-44")
            ui.label("Integração configurável (a doc da Higgsfield é fechada por login). "
                     "Se o endpoint da sua conta diferir, ajuste a Base da API — "
                     "o padrão segue o formato REST comum.").classes("mut2 text-xs")

        with ui.expansion("🖥️ Geração local na sua GPU (RTX)") \
                .classes("w-full").props("dense"):
            ui.label("💡 O modelo de IMAGEM local agora é escolhido direto na tela "
                     "Imagens (ao selecionar 'Local na sua GPU'). Aqui fica só o "
                     "modelo de VÍDEO local (LTX) e o pré-download.") \
                .classes("mut2 text-xs")
            from core.imagen import LOCAL_IMAGE_MODELS
            lim = ui.select({k: v[1] for k, v in LOCAL_IMAGE_MODELS.items()},
                            value=settings.local_image_model,
                            label="Modelo local de imagem (padrão)") \
                .props("outlined dense").classes("w-full")
            sdw = ui.input("URL do SD WebUI (A1111/Forge com --api)",
                           value=settings.sdwebui_url).props("outlined dense") \
                .classes("w-full")
            ltxm = ui.input("Modelo LTX-Video (animação local)",
                            value=settings.ltx_model).props("outlined dense") \
                .classes("w-full")
            async def predl():
                if job.running:
                    ui.notify("Aguarde a tarefa atual", type="warning")
                    return
                from core import predownload
                job.running = True
                job.cb("download", 0, 1, "Pré-baixando modelos locais…")
                dl_btn.props("loading")
                try:
                    done = await run.io_bound(predownload.download_all, settings,
                                              lambda m: job.cb("download", 0, 1, m))
                    ui.notify("Modelos prontos: " + ", ".join(done), type="positive",
                              timeout=10000)
                except Exception as e:
                    ui.notify(f"Erro no download: {e}", type="negative",
                              multi_line=True, timeout=10000)
                finally:
                    job.running = False
                    try:
                        dl_btn.props(remove="loading")
                    except Exception:
                        pass

            with ui.row().classes("w-full items-center gap-3"):
                dl_btn = theme.ghost_btn("⬇ Baixar modelos locais agora "
                                         "(deixa tudo pronto)", predl, icon="download")
                busy_guard(dl_btn)
            ui.label("Baixa de uma vez: modelo de imagens escolhido, LTX-Video e Whisper "
                     "(fica no cache — nunca mais espera download na hora de gerar). "
                     "Na RTX 2060 6GB: SDXL ~45s/imagem, LTX ~2-5 min/clipe.") \
                .classes("mut2 text-xs")

        with ui.expansion("Google via OAuth — Vertex AI (avançado)") \
                .classes("w-full").props("dense"):
            ui.html('<span class="pill warn"><i></i>Atenção: o Vertex também é PAGO '
                    '(cobra no seu projeto Google Cloud). Não é uma forma grátis de '
                    'repor os créditos do Gemini.</span>')
            vx_sw = ui.switch("Usar Vertex AI em vez da chave de API",
                              value=settings.use_vertex).props("color=negative")
            with ui.row().classes("w-full gap-3 no-wrap"):
                vx_proj = ui.input("ID do projeto Google Cloud",
                                   value=settings.vertex_project) \
                    .props("outlined dense").classes("grow")
                vx_loc = ui.input("Região", value=settings.vertex_location) \
                    .props("outlined dense").classes("w-40")
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("Passos:").classes("mut text-xs")
                ui.link("console.cloud.google.com ↗", PROVIDER_LINKS["VERTEX"],
                        new_tab=True).classes("text-xs").style("color:var(--acc)")
            ui.label("1) crie um projeto e ative o billing; 2) ative a Vertex AI API; "
                     "3) instale o gcloud CLI e rode `gcloud auth application-default "
                     "login`; 4) ligue o switch acima e informe o ID do projeto. "
                     "IMPORTANTE: a assinatura Google AI Pro/Ultra (app/site Gemini) é do "
                     "produto consumidor e NÃO dá cota de API/Veo para programas.") \
                .classes("mut2 text-xs")

        def save():
            settings.set_api_key(key_in.value or "")
            settings.set_env_key("ELEVENLABS_API_KEY", el_in.value or "")
            settings.set_env_key("OPENAI_API_KEY", oa_in.value or "")
            settings.set_env_key("DEEPSEEK_API_KEY", ds_in.value or "")
            settings.set_env_key("HF_TOKEN", hf_in.value or "")
            settings.set_env_key("TOGETHER_API_KEY", tg_in.value or "")
            settings.set_env_key("HIGGSFIELD_API_KEY", hg_in.value or "")
            settings.set_env_key("HIGGSFIELD_SECRET", hg_sec.value or "")
            settings.higgsfield_base = (hg_base.value or "").strip() or settings.higgsfield_base
            settings.higgsfield_video_model = (hg_vmodel.value or "").strip() \
                or settings.higgsfield_video_model
            settings.text_model = text_in.value.strip()
            settings.image_model = img_in.value.strip()
            settings.veo_model = veo_in.value.strip()
            settings.whisper_model = whisper_in.value
            settings.use_vertex = bool(vx_sw.value)
            settings.vertex_project = (vx_proj.value or "").strip()
            settings.vertex_location = (vx_loc.value or "us-central1").strip()
            settings.local_image_model = lim.value
            settings.sdwebui_url = (sdw.value or "").strip() or settings.sdwebui_url
            settings.ltx_model = (ltxm.value or "").strip() or settings.ltx_model
            settings.save()
            ui.notify("Configurações salvas", type="positive")
            dlg.close()
            refresh_all()

        with ui.row().classes("w-full justify-end gap-2"):
            theme.ghost_btn("Cancelar", dlg.close)
            theme.primary_btn("Salvar", save)
    dlg.open()


def new_project_dialog():
    with ui.dialog() as dlg, ui.card().classes("card gap-4").style("width:480px;max-width:95vw"):
        ui.label("Novo projeto").classes("h-title").style("font-size:19px")
        name_in = ui.input("Nome do vídeo", placeholder="Ex.: A cidade que desapareceu") \
            .props("outlined autofocus").classes("w-full")

        def create():
            if not (name_in.value or "").strip():
                ui.notify("Dê um nome ao projeto", type="warning")
                return
            state.project = Project.create(name_in.value.strip())
            app.storage.general["last_project"] = state.project.slug
            state.step = "script"
            dlg.close()
            refresh_all()

        name_in.on("keydown.enter", create)
        with ui.row().classes("w-full justify-end gap-2"):
            theme.ghost_btn("Cancelar", dlg.close)
            theme.primary_btn("Criar projeto", create, icon="add")
    dlg.open()


TONES = ["mistério e suspense", "terror sombrio", "curiosidade e fatos surpreendentes",
         "documentário investigativo", "motivacional e reflexivo", "história emocionante"]


def _fmt_views(v) -> str:
    v = int(v or 0)
    if v >= 1_000_000:
        return f"{v / 1e6:.1f}M"
    if v >= 1_000:
        return f"{v / 1e3:.0f}k"
    return str(v)


def _bgm_suggestion(mood: str) -> str:
    m = mood.lower()
    if any(k in m for k in ("terror", "horror", "medo")):
        return "drones graves + cordas dissonantes"
    if any(k in m for k in ("dark", "sombrio", "tenso", "mist", "suspense")):
        return "dark ambient, pulso lento"
    if any(k in m for k in ("triste", "melanc", "emotiv")):
        return "piano melancólico minimalista"
    if any(k in m for k in ("épic", "epic", "guerra", "grandio")):
        return "orquestral percussivo"
    if any(k in m for k in ("curios", "ciên", "tech", "futur")):
        return "eletrônica minimal pulsada"
    return "ambient neutro discreto"


def _apply_preset(st: dict, pid: str) -> None:
    p = KARAOKE_PRESETS.get(pid, KARAOKE_PRESETS["classic"])
    st.update({"sub_preset": pid, "sub_font": p["font"], "sub_size": p["size"],
               "sub_color": p["color"], "sub_highlight": p["highlight"],
               "sub_outline": p["outline"], "sub_shadow": p["shadow"],
               "sub_uppercase": p["uppercase"], "sub_grow": p["grow"],
               "sub_box": p.get("box", False)})


# --------------------------------------------------------- remodelar canal
def remodel_dialog():
    with ui.dialog() as dlg, ui.card().classes("card gap-3") \
            .style("width:900px;max-width:97vw;max-height:92vh;overflow-y:auto"):
        ui.label("Estudar & Remodelar canal do YouTube").classes("h-title").style("font-size:19px")
        ui.label("Passe a URL de um canal que já dá resultado. Os agentes estudam TUDO: "
                 "nicho, formato, fórmula de títulos, top vídeos com views, velocidade "
                 "(views/mês) e ganho estimado por vídeo. Escolha um vídeo e a IA reescreve "
                 "a história do zero — mais forte e sem copiar frases.").classes("mut text-sm")
        with ui.row().classes("w-full gap-2 no-wrap items-end"):
            url_in = ui.input("URL do canal",
                              placeholder="https://www.youtube.com/@canal  ou  @canal") \
                .props("outlined dense").classes("grow")
            fetch_btn = theme.primary_btn("Estudar canal", None, icon="analytics")
        results = ui.column().classes("w-full gap-0")
        step2 = ui.column().classes("w-full gap-2")
        ui.label("Use como pesquisa criativa: a reescrita gera texto original, mas confira "
                 "direitos sobre histórias exclusivas.").classes("mut2 text-xs")

        async def use_video(vid: dict):
            step2.clear()
            with step2:
                ui.label(f"Vídeo escolhido: {vid['title']}").classes("text-sm font-medium")
                spin = ui.spinner("dots", size="24px", color="negative")
            try:
                transcript = await run.io_bound(remodel.get_transcript, vid["url"])
            except Exception as e:
                step2.clear()
                with step2:
                    theme.pill(f"erro ao extrair legenda: {e}", "warn")
                return
            spin.set_visibility(False)
            with step2:
                ui.label(f"Legenda extraída: {len(transcript.split())} palavras. "
                         "Escolha o tom da reescrita:").classes("mut text-sm")
                with ui.row().classes("w-full gap-2 no-wrap items-end"):
                    tone = ui.select(TONES, value=TONES[0], label="Tom") \
                        .props("outlined dense").classes("grow")
                    rw_btn = theme.primary_btn("Reescrever e criar projeto", None,
                                               icon="auto_awesome")

                async def rewrite():
                    if not settings.gemini_api_key:
                        ui.notify("A reescrita precisa da GEMINI_API_KEY", type="warning")
                        return
                    rw_btn.props("loading")
                    try:
                        llm = LLM(settings)
                        script = await run.io_bound(llm.rewrite_script, transcript,
                                                    "pt-BR", tone.value)
                        proj = Project.create(f"Remodel — {vid['title'][:42]}")
                        proj.set_script(script, "pt-BR")
                        state.project = proj
                        app.storage.general["last_project"] = proj.slug
                        state.step = "script"
                        dlg.close()
                        refresh_all()
                        ui.notify("Roteiro remodelado criado — revise e siga o pipeline",
                                  type="positive", timeout=8000)
                    except Exception as e:
                        ui.notify(f"Erro na reescrita: {e}", type="negative",
                                  multi_line=True, timeout=10000)
                    finally:
                        rw_btn.props(remove="loading")

                rw_btn.on_click(rewrite)

        async def fetch():
            if not (url_in.value or "").strip():
                ui.notify("Informe a URL do canal", type="warning")
                return
            fetch_btn.props("loading")
            results.clear()
            step2.clear()
            try:
                def pcb(msg):
                    job.cb("study", 0, 1, msg)

                data = await run.io_bound(remodel.study_channel,
                                          url_in.value.strip(), 12, pcb)
                vids = data.get("top_videos", [])
                study = {}
                if settings.gemini_ready or settings.deepseek_api_key:
                    pcb("Agentes estudando o canal (nicho, RPM, fórmula)…")
                    crew = Crew(settings)
                    try:
                        study = await run.io_bound(crew.channel_study, data, "pt-BR")
                    except Exception:
                        study = {}
                rpm_min = float(study.get("rpm_min") or 1.5)
                rpm_max = float(study.get("rpm_max") or 4.0)
                remodel.apply_earnings(vids, rpm_min, rpm_max)
                prior = {p.get("indice"): p.get("porque", "")
                         for p in (study.get("prioridade_remodelagem") or [])}

                with results:
                    # ------- resumo do estudo -------
                    with ui.row().classes("w-full items-center gap-4 no-wrap"):
                        with ui.column().classes("gap-0"):
                            ui.label(f"{data.get('name')}").classes("text-base font-semibold")
                            ui.label(f"{_fmt_views(data.get('subscribers') or 0)} inscritos · "
                                     f"{data.get('video_count', '?')} vídeos · top 12 somam "
                                     f"{_fmt_views(data.get('total_top_views', 0))} views") \
                                .classes("mut text-xs")
                        ui.element("div").classes("grow")
                        theme.pill(f"nicho: {study.get('nicho', '—')}", "acc")
                        theme.pill(f"RPM est.: US$ {rpm_min:g}–{rpm_max:g}/1000 views", "warn")
                    if study:
                        for k, ico in (("formato", "movie"), ("cadencia", "schedule"),
                                       ("formula_titulos", "title")):
                            if study.get(k):
                                with ui.row().classes("items-start gap-2 no-wrap"):
                                    ui.icon(ico).classes("text-sm mt-1") \
                                        .style("color:var(--acc)")
                                    ui.label(study[k]).classes("mut text-xs")
                        if study.get("o_que_usa"):
                            with ui.row().classes("gap-2 wrap"):
                                for u in study["o_que_usa"][:6]:
                                    theme.pill(str(u)[:48], "off")
                        ui.label("RPM: " + study.get("rpm_justificativa", "")) \
                            .classes("mut2 text-xs")

                    # ------- tabela de vídeos c/ ganhos -------
                    ui.label("Vídeos — views, velocidade e ganho estimado").classes("card-h mt-2")
                    for i, v in enumerate(vids, 1):
                        with ui.element("div").classes("syncrow w-full"):
                            ui.label(f"{i:02d}").classes("tchip")
                            ui.label(_fmt_views(v["views"])).classes("tchip") \
                                .style("min-width:54px;text-align:center")
                            vm = v.get("views_month")
                            ui.label(f"{_fmt_views(vm)}/mês" if vm else "—") \
                                .classes("mono mut2 text-xs").style("min-width:64px")
                            ui.label(f"{v['duration'] // 60}:{v['duration'] % 60:02d}") \
                                .classes("mono mut2 text-xs").style("min-width:40px")
                            ui.label(f"💰 US$ {v.get('earn_min', 0):,}–{v.get('earn_max', 0):,}") \
                                .classes("mono text-xs").style("color:var(--ok);min-width:120px")
                            with ui.column().classes("gap-0 grow"):
                                ui.label(v["title"][:70]).classes("text-sm")
                                if prior.get(i):
                                    ui.label(f"⭐ prioridade: {prior[i]}") \
                                        .classes("text-xs").style("color:var(--warn)")
                            theme.primary_btn("Remodelar", lambda v=v: use_video(v))
                    ui.label("⚠ Ganhos são ESTIMATIVAS (views ÷ 1000 × RPM típico do nicho, "
                             "antes da divisão com o YouTube variar) — a receita real é "
                             "privada e depende de país, anunciantes e época.") \
                        .classes("mut2 text-xs")
            except Exception as e:
                ui.notify(f"Erro ao estudar canal: {e}", type="negative",
                          multi_line=True, timeout=10000)
            finally:
                fetch_btn.props(remove="loading")

        fetch_btn.on_click(fetch)
        url_in.on("keydown.enter", fetch)
    dlg.open()


def video_config_form(defaults: dict | None = None):
    """Formulário com TODAS as configurações das etapas do pipeline.
    Retorna get_cfg() que devolve o dict de config completo. Usado por
    Lote e Agendador — configure uma vez, aplica a todos os vídeos."""
    from core.animate import ANIM_PROVIDERS
    from core.editor import FILTERS, KARAOKE_PRESETS, TRANSITIONS
    c = merged(defaults)
    W: dict = {}

    def section(title: str, key: str):
        """Cabeçalho de seção com toggle 'IA escolhe'. LIGADO = a IA decide esta
        seção por vídeo; DESLIGADO (padrão) = usa o que você configurar."""
        with ui.row().classes("w-full items-center justify-between no-wrap mt-1"):
            ui.label(title).classes("card-h")
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.label("IA escolhe").classes("mut2 text-xs")
                # manual_<key> guardado invertido: toggle ON = IA (manual=False)
                tg = ui.switch(value=not bool(c.get(f"manual_{key}", True))) \
                    .props("color=secondary dense")
                W[f"manual_{key}"] = tg
        note = ui.label(f"🤖 A IA escolhe {title.lower()} automaticamente para cada vídeo.") \
            .classes("mut2 text-xs")
        note.bind_visibility_from(tg, "value")
        box = ui.column().classes("w-full gap-2")
        box.bind_visibility_from(tg, "value", backward=lambda v: not v)
        return box

    with ui.column().classes("w-full gap-2"):
        with section("Conteúdo", "content"):
            with ui.row().classes("w-full gap-3 no-wrap"):
                W["niche"] = niche_select("Nicho do canal", c["niche"])
                W["minutes"] = ui.select({1: "~1 min (short)", 3: "~3 min", 5: "~5 min",
                                          8: "~8 min", 12: "~12 min"}, value=c["minutes"],
                                         label="Duração").props("outlined dense").classes("w-36")
                W["tone"] = ui.select(TONES, value=c["tone"], label="Tom") \
                    .props("outlined dense").classes("grow")
            with ui.row().classes("w-full gap-3 no-wrap"):
                W["format"] = ui.select({"16:9": "16:9 — YouTube", "9:16": "9:16 — Shorts",
                                         "1:1": "1:1 — quadrado"}, value=c["format"],
                                        label="Formato").props("outlined dense").classes("grow")
                W["language"] = ui.select(LANGUAGES, value=c["language"], label="Idioma") \
                    .props("outlined dense").classes("grow")
                W["style"] = ui.select({k: v["label"] for k, v in STYLES.items() if k != "custom"},
                                       value=c["style"], label="Estilo visual") \
                    .props("outlined dense").classes("grow")

        engines = tts.engines_info()
        with section("Narração", "narration"):
            with ui.row().classes("w-full gap-3 no-wrap"):
                W["tts_engine"] = ui.select(
                    {e["id"]: e["label"] for e in engines}, value=c["tts_engine"],
                    label="Engine TTS").props("outlined dense").classes("w-64")
                voice_opts = {v: d for v, d in tts.voices_for(c["tts_engine"], c["language"])}
                W["tts_voice"] = ui.select(voice_opts, value=c["tts_voice"]
                                           if c["tts_voice"] in voice_opts
                                           else (next(iter(voice_opts), None)),
                                           label="Voz").props("outlined dense").classes("grow")

                def _refresh_voices(e=None):
                    vs = tts.voices_for(W["tts_engine"].value, W["language"].value)
                    W["tts_voice"].set_options({v: d for v, d in vs},
                                               value=vs[0][0] if vs else None)

                W["tts_engine"].on_value_change(_refresh_voices)
                W["language"].on_value_change(_refresh_voices)
                W["tts_rate"] = ui.number("Vel. %", value=c["tts_rate"], min=-40, max=40,
                                          step=5).props("outlined dense").classes("w-24")
            W["tts_style"] = ui.input(
                "Instrução de estilo da voz (Gemini/OpenAI — opcional)",
                value=c["tts_style"],
                placeholder='ex.: "narre em tom sombrio e misterioso, ritmo lento"') \
                .props("outlined dense").classes("w-full")

        with section("Produção", "production"):
            with ui.row().classes("w-full gap-3 no-wrap"):
                W["whisper"] = ui.select(["tiny", "base", "small", "medium", "large-v3"],
                                         value=c["whisper"], label="Whisper") \
                    .props("outlined dense").classes("w-32")
                W["provider"] = ui.select(PROVIDERS, value=c["provider"], label="Imagens") \
                    .props("outlined dense").classes("grow")
            with ui.row().classes("w-full gap-3 no-wrap items-center"):
                W["use_refs"] = ui.switch("Consistência de personagem (refs)",
                                          value=c["use_refs"]).props("color=negative")
                W["animate"] = ui.switch("Animar", value=c["animate"]).props("color=negative")
                W["anim_provider"] = ui.select(ANIM_PROVIDERS, value=c["anim_provider"],
                                               label="Tipo de animação") \
                    .props("outlined dense").classes("grow")
                W["anim_provider"].bind_visibility_from(W["animate"], "value")

        from core.editor import KARAOKE_PRESETS as _KP
        _pr0 = _KP.get(c["preset"], _KP["classic"])
        with section("Legendas e edição", "captions"):
            with ui.row().classes("w-full gap-3 no-wrap"):
                W["preset"] = ui.select({k: v["label"] for k, v in KARAOKE_PRESETS.items()},
                                        value=c["preset"], label="Preset de legenda") \
                    .props("outlined dense").classes("grow")
                W["karaoke_mode"] = ui.select({"kf": "Varredura suave", "k": "Bloco"},
                                              value=c["karaoke_mode"], label="Karaokê") \
                    .props("outlined dense").classes("w-40")
                W["sub_position"] = ui.select({"bottom": "Embaixo", "center": "Centro",
                                               "top": "Topo"}, value=c["sub_position"],
                                              label="Posição").props("outlined dense").classes("w-32")
            with ui.row().classes("w-full gap-3 no-wrap items-center"):
                W["transition"] = ui.select(TRANSITIONS, value=c["transition"],
                                            label="Transição").props("outlined dense").classes("grow")
                ui.label("duração").classes("mut2 text-xs")
                W["transition_dur"] = ui.slider(min=0.2, max=0.8, step=0.05,
                                                value=c["transition_dur"]) \
                    .props("color=negative label").classes("w-28")
                W["filter"] = ui.select({k: v[0] for k, v in FILTERS.items()},
                                        value=c["filter"], label="Filtro de cor") \
                    .props("outlined dense").classes("grow")
            with ui.row().classes("w-full gap-3 no-wrap items-end"):
                W["sub_font"] = ui.select(["Arial", "Arial Black", "Impact", "Verdana",
                                           "Segoe UI", "Trebuchet MS", "Georgia"],
                                          value=c.get("sub_font") or _pr0["font"],
                                          label="Fonte").props("outlined dense").classes("grow")
                W["sub_size"] = ui.number("Tamanho", value=c.get("sub_size") or _pr0["size"],
                                          min=36, max=120).props("outlined dense").classes("w-28")
                W["sub_color"] = ui.color_input("Cor base",
                                                value=c.get("sub_color") or _pr0["color"]) \
                    .props("dense outlined").classes("grow")
                W["sub_highlight"] = ui.color_input("Cor do destaque",
                                                    value=c.get("sub_highlight") or _pr0["highlight"]) \
                    .props("dense outlined").classes("grow")

            def _sync_preset(e):
                pr = _KP.get(e.value, _KP["classic"])
                W["sub_font"].set_value(pr["font"])
                W["sub_size"].set_value(pr["size"])
                W["sub_color"].set_value(pr["color"])
                W["sub_highlight"].set_value(pr["highlight"])

            W["preset"].on_value_change(_sync_preset)

            with ui.row().classes("w-full gap-3 no-wrap items-center"):
                W["bgm_path"] = ui.input("Trilha de fundo p/ todos (opcional — caminho .mp3)",
                                         value=c.get("bgm_path", ""),
                                         placeholder=r"C:\musicas\dark-ambient.mp3") \
                    .props("outlined dense").classes("grow")
                ui.label("volume").classes("mut2 text-xs")
                W["bgm_volume"] = ui.slider(min=0.05, max=0.5, step=0.01,
                                            value=c["bgm_volume"]) \
                    .props("color=negative").classes("w-28")
            with ui.row().classes("w-full gap-5 no-wrap items-center"):
                W["karaoke"] = ui.switch("Karaokê", value=c["karaoke"]).props("color=negative")
                W["subtitles_on"] = ui.switch("Legendas", value=c["subtitles_on"]) \
                    .props("color=negative")
                W["uppercase"] = ui.switch("MAIÚSCULAS", value=c["uppercase"]) \
                    .props("color=negative")
                W["grow"] = ui.switch("Pop de entrada", value=c["grow"]).props("color=negative")

    def get_cfg() -> dict:
        out = {}
        for k, w in W.items():
            val = w.value if hasattr(w, "value") else w
            # toggle 'IA escolhe' (ON) significa manual_<key>=False
            out[k] = (not val) if k.startswith("manual_") else val
        return out

    return get_cfg


# --------------------------------------------------------- produção em lote
def batch_dialog(prefill_ideas: list[str] | None = None,
                 prefill_niche: str | None = None):
    from core.vconfig import apply_config
    with ui.dialog() as dlg, ui.card().classes("card gap-3") \
            .style("width:720px;max-width:96vw;max-height:92vh;overflow-y:auto"):
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label("Produção em lote").classes("h-title").style("font-size:19px")
            with ui.row().classes("items-center gap-2 no-wrap"):
                auto_lbl = ui.label("produz tudo até o MP4").classes("mut2 text-xs")
                auto_produce = ui.switch("Automático", value=True) \
                    .props("color=negative")
                auto_produce.on_value_change(lambda e: auto_lbl.set_text(
                    "produz tudo até o MP4" if e.value
                    else "só cria os roteiros (você produz depois)"))
        ui.label("Uma ideia por linha. Com o toggle Automático LIGADO, a IA escreve o "
                 "roteiro e produz cada vídeo até o MP4 (avançando por todas as etapas "
                 "sozinho, como se o Automático estivesse ligado em cada etapa). "
                 "DESLIGADO, ele só cria os projetos com o roteiro — você produz cada um "
                 "manualmente depois. As configurações abaixo valem para TODOS os vídeos.") \
            .classes("mut text-sm")
        ideas_ta = ui.textarea(value="\n".join(prefill_ideas or []),
                               placeholder="O mistério do voo 370\nA cidade proibida da "
                                           "Sibéria\nO homem que sobreviveu a 2 bombas…") \
            .props("outlined autogrow input-style=min-height:100px").classes("w-full")

        def fill_ideas(titles: list[str]):
            cur = (ideas_ta.value or "").strip()
            ideas_ta.set_value((cur + "\n" if cur else "") + "\n".join(titles))

        with ui.row().classes("w-full justify-end"):
            theme.ghost_btn("Sugerir histórias (IA)", lambda: ideas_dialog(fill_ideas),
                            icon="insights")

        ui.separator().classes("bg-white/10")
        get_cfg = video_config_form({"niche": prefill_niche})

        async def start():
            ideas = [l.strip() for l in (ideas_ta.value or "").splitlines() if l.strip()]
            if not ideas:
                ui.notify("Cole ao menos uma ideia", type="warning")
                return
            if not settings.gemini_ready and not settings.deepseek_api_key:
                ui.notify("O lote precisa de GEMINI_API_KEY ou DEEPSEEK_API_KEY (roteiro)",
                          type="warning")
                return
            cfg = get_cfg()
            if cfg["provider"] == "gemini" and settings.gemini_ready:
                est_imgs = len(ideas) * int(cfg["minutes"]) * 12
                if not await confirm_cost(est_imgs, settings.image_cost_usd,
                                          f"Lote de {len(ideas)} vídeos — imagens"):
                    return
            if job.running:
                ui.notify("Já existe uma tarefa em execução", type="warning")
                return
            dlg.close()
            job.running = True
            pipeline.CANCEL.clear()
            refresh_all()
            done = 0
            try:
                for k, idea in enumerate(ideas, 1):
                    if pipeline.CANCEL.is_set():
                        break
                    job.cb("batch", 0, 1, f"[{k}/{len(ideas)}] Escrevendo roteiro…")
                    llm = LLM(settings)
                    script = await run.io_bound(llm.generate_script, idea,
                                                float(cfg["minutes"]), cfg["tone"],
                                                cfg["language"], cfg["niche"] or "")
                    proj = Project.create(idea[:48])
                    proj.set_script(script, cfg["language"])
                    from core.vconfig import resolve_auto
                    rcfg = resolve_auto(cfg, idea, script, llm)  # seções auto → IA/padrão
                    apply_config(proj, rcfg)  # todas as etapas configuradas de uma vez
                    proj.save()
                    state.project = proj
                    app.storage.general["last_project"] = proj.slug

                    def cb(stage, i, n, msg="", k=k):
                        job.cb(stage, i, n, f"[{k}/{len(ideas)}] {msg}")

                    if auto_produce.value:
                        await run.io_bound(pipeline.run_full, proj, settings, cb)
                    done += 1
                if auto_produce.value:
                    ui.notify(f"Lote concluído: {done}/{len(ideas)} vídeos prontos",
                              type="positive", timeout=10000)
                else:
                    ui.notify(f"{done} projetos criados com roteiro — produza cada um "
                              "nas telas quando quiser", type="positive", timeout=10000)
            except pipeline.Cancelled:
                ui.notify(f"Lote cancelado — {done} vídeos concluídos", type="warning")
            except Exception as e:
                ui.notify(f"Lote parou no vídeo {done + 1}: {e}", type="negative",
                          multi_line=True, timeout=12000)
            finally:
                job.running = False
                refresh_all()

        with ui.row().classes("w-full justify-end gap-2 pt-2"):
            theme.ghost_btn("Cancelar", dlg.close)
            theme.primary_btn("Iniciar produção", start, icon="factory")
    dlg.open()


# ------------------------------------------------------- sugestor de ideias
def ideas_dialog(on_use, preset_niche: str | None = None,
                 preset_extra: str | None = None):
    """Estrategista de Conteúdo: sugere histórias com potencial no nicho."""
    with ui.dialog() as dlg, ui.card().classes("card gap-3") \
            .style("width:720px;max-width:96vw;max-height:90vh;overflow-y:auto"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("insights").style("color:var(--acc)")
            ui.label("Estrategista de Conteúdo — sugestões de histórias") \
                .classes("h-title").style("font-size:18px")
        ui.label(f"{niche_count()} nichos catalogados em {len(NICHE_CATALOG)} categorias — "
                 "digite no campo para buscar ou criar um nicho seu.").classes("mut2 text-xs")
        with ui.row().classes("w-full gap-3 no-wrap items-end"):
            niche = niche_select(value=preset_niche)
            extra = ui.input("Direcionamento (opcional)", value=preset_extra or "",
                             placeholder="ex.: Brasil anos 90, sem violência…") \
                .props("outlined dense").classes("grow")
            gen_btn = theme.primary_btn("Sugerir 10 histórias", None, icon="insights")
        list_box = ui.column().classes("w-full gap-1")
        selected: dict[int, dict] = {}

        async def gen():
            if not settings.gemini_api_key:
                ui.notify("Requer GEMINI_API_KEY", type="warning")
                return
            gen_btn.props("loading")
            list_box.clear()
            selected.clear()
            try:
                crew = Crew(settings)
                ideas = await run.io_bound(crew.suggest_ideas, niche.value, 10,
                                           "pt-BR", extra.value or "")
                with list_box:
                    for i, idea in enumerate(ideas):
                        with ui.row().classes("w-full items-start gap-2 no-wrap py-1") \
                                .style("border-bottom:1px solid var(--border-soft)"):
                            cb = ui.checkbox(value=False).props("dense color=negative")

                            def toggle(e, i=i, idea=idea):
                                if e.value:
                                    selected[i] = idea
                                else:
                                    selected.pop(i, None)

                            cb.on_value_change(toggle)
                            with ui.column().classes("gap-0 grow"):
                                ui.label(idea.get("title", "")).classes("text-sm font-medium")
                                ui.label(f"Gancho: {idea.get('hook', '')}") \
                                    .classes("mut text-xs")
                                ui.label(idea.get("why", "")).classes("mut2 text-xs")
                    with ui.row().classes("w-full justify-end gap-2 pt-2"):
                        def picked() -> list[str]:
                            return [v["title"] for _, v in sorted(selected.items())]

                        def use():
                            titles = picked()
                            if not titles:
                                ui.notify("Marque ao menos uma história", type="warning")
                                return
                            on_use(titles)
                            dlg.close()

                        def to_batch():
                            titles = picked()
                            if not titles:
                                ui.notify("Marque ao menos uma história", type="warning")
                                return
                            dlg.close()
                            batch_dialog(prefill_ideas=titles, prefill_niche=niche.value)

                        theme.ghost_btn("Produzir em lote agora", to_batch,
                                        icon="precision_manufacturing")
                        theme.primary_btn("Usar selecionadas", use, icon="playlist_add")
            except Exception as e:
                ui.notify(f"Erro: {e}", type="negative", multi_line=True, timeout=10000)
            finally:
                gen_btn.props(remove="loading")

        gen_btn.on_click(gen)
    dlg.open()


# ------------------------------------------------- piloto de navegador
def browser_whisk_dialog():
    """Gera as imagens das cenas no Whisk (conta Google do usuário, sem API)."""
    from core import browserbot
    p = state.project
    prompts = p.state["style"].get("prompts") or []
    files = p.state["images"].get("files") or [None] * len(prompts)
    files = (files + [None] * len(prompts))[:len(prompts)]
    missing = [(i, prompts[i]) for i in range(len(prompts)) if not files[i]]

    with ui.dialog() as dlg, ui.card().classes("card gap-3").style("width:640px;max-width:96vw"):
        ui.label("Whisk/Flow — gerar imagens pelo navegador").classes("h-title") \
            .style("font-size:18px")
        ui.label("Abre um Chrome do DarkStudio no Flow (labs.google — o Whisk agora vive "
                 "dentro dele). Você loga na sua conta Google UMA vez (fica salvo); o "
                 "piloto digita cada prompt, gera, captura a imagem e coloca direto na "
                 "cena. Se algum passo automático falhar, baixe manualmente que ele "
                 "importa sozinho.").classes("mut text-sm")
        theme.pill("experimental — usa sua conta e os limites do Labs", "warn")
        alvo = ui.radio({"missing": f"Só as cenas faltantes ({len(missing)})",
                         "all": f"Todas as cenas ({len(prompts)})"},
                        value="missing").props("color=negative")
        prog = ui.label("").classes("text-sm").style("color:var(--acc)")

        async def start():
            todo = missing if alvo.value == "missing" else list(enumerate(prompts))
            if not todo:
                ui.notify("Nada a gerar", type="positive")
                return
            if job.running:
                ui.notify("Aguarde a tarefa atual", type="warning")
                return
            job.running = True
            pipeline.CANCEL.clear()
            start_btn.props("loading")

            def pcb(msg):
                job.cb("browser", 0, 1, msg)
                try:
                    prog.set_text(msg)
                except Exception:
                    pass

            def save_scene(i, tmp_path):
                from core.imagen import normalize_frame
                from core.config import FORMATS
                dims = FORMATS.get(p.state.get("format", "16:9"), (1920, 1080))
                out = p.path("images", f"scene_{i:03d}.jpg")
                normalize_frame(Path(tmp_path).read_bytes(), out, dims[0], dims[1])
                fl = p.state["images"].get("files") or [None] * len(prompts)
                fl = (fl + [None] * len(prompts))[:len(prompts)]
                fl[i] = p.rel(out)
                p.state["images"]["files"] = fl
                p.save()

            def worker():
                bot = browserbot.BrowserBot(headed=True).start()
                try:
                    return bot.whisk_generate(todo, save_scene, pcb,
                                              cancel=pipeline.CANCEL.is_set)
                finally:
                    bot.stop()

            try:
                ok, fail = await run.io_bound(worker)
                ui.notify(f"Whisk: {ok} imagens importadas"
                          + (f", {fail} falharam" if fail else ""),
                          type="positive" if ok else "warning", timeout=9000)
            except Exception as e:
                ui.notify(f"Piloto falhou: {e}", type="negative", multi_line=True,
                          timeout=12000)
            finally:
                job.running = False
                try:
                    start_btn.props(remove="loading")
                except Exception:
                    pass
                refresh_all()

        with ui.row().classes("w-full justify-end gap-2"):
            theme.ghost_btn("Fechar", dlg.close)
            start_btn = theme.primary_btn("Abrir navegador e gerar", start, icon="public")
    dlg.open()


def browser_flow_dialog():
    """Anima as cenas no Flow/Veo 3 (assistido): prompt no clipboard + importa download."""
    from core import browserbot
    p = state.project
    plans = {pl["i"]: pl for pl in (p.state["animation"].get("plans") or [])}
    files = p.state["images"].get("files") or []
    clips = p.state["animation"].get("clips") or [None] * len(files)
    clips = (clips + [None] * len(files))[:len(files)]
    scenes = [(i, p.dir / files[i],
               (plans.get(i) or {}).get("veo_prompt", "slow cinematic motion"))
              for i in range(len(files)) if files[i] and not clips[i]]

    with ui.dialog() as dlg, ui.card().classes("card gap-3").style("width:640px;max-width:96vw"):
        ui.label("Flow / Veo 3 — animar pelo navegador (automático)").classes("h-title") \
            .style("font-size:18px")
        ui.label(f"{len(scenes)} cenas sem clipe. O piloto abre o Flow na SUA conta e, "
                 "para cada cena, sozinho: cria o projeto, entra no modo Vídeo→Frames, "
                 "envia a imagem, escreve o prompt, clica em Criar, baixa o vídeo e "
                 "passa para a próxima — até terminar. Você só precisa estar logado.") \
            .classes("mut text-sm")
        theme.pill("usa CRÉDITOS do seu plano Flow (~24/geração) — não é a API Gemini", "warn")
        theme.pill("best-effort: se o layout do Flow mudar numa cena, copia o prompt e "
                   "espera você baixar (assistido) só naquela, e segue", "ok")
        with ui.row().classes("w-full gap-2"):
            theme.ghost_btn("Abrir pasta das imagens",
                            lambda: open_folder(p.path("images")), icon="folder_open")
        prog = ui.label("").classes("text-sm").style("color:var(--acc)")

        async def start():
            if not scenes:
                ui.notify("Todas as cenas já têm clipe", type="positive")
                return
            if job.running:
                ui.notify("Aguarde a tarefa atual", type="warning")
                return
            job.running = True
            pipeline.CANCEL.clear()
            start_btn.props("loading")

            def pcb(msg):
                job.cb("browser", 0, 1, msg)
                try:
                    prog.set_text(msg)
                except Exception:
                    pass

            def save_clip(i, tmp_path):
                out = p.path("clips", f"clip_{i:03d}.mp4")
                shutil.copy2(tmp_path, out)
                cl = p.state["animation"].get("clips") or [None] * len(files)
                cl = (cl + [None] * len(files))[:len(files)]
                cl[i] = p.rel(out)
                p.state["animation"]["clips"] = cl
                p.state["animation"]["provider"] = "veo"  # usa clipes no render
                p.save()

            def worker():
                bot = browserbot.BrowserBot(headed=True).start()
                try:
                    return bot.flow_auto(scenes, save_clip, pcb,
                                         cancel=pipeline.CANCEL.is_set)
                finally:
                    bot.stop()

            try:
                ok, fail = await run.io_bound(worker)
                ui.notify(f"Flow: {ok} clipes gerados"
                          + (f", {fail} pendentes" if fail else ""),
                          type="positive" if ok else "warning", timeout=9000)
            except Exception as e:
                ui.notify(f"Piloto falhou: {e}", type="negative", multi_line=True,
                          timeout=12000)
            finally:
                job.running = False
                try:
                    start_btn.props(remove="loading")
                except Exception:
                    pass
                refresh_all()

        with ui.row().classes("w-full justify-end gap-2"):
            theme.ghost_btn("Fechar", dlg.close)
            start_btn = theme.primary_btn("Abrir Flow e gerar tudo", start, icon="public")
    dlg.open()


# --------------------------------------------------------- galeria de vozes
@ui.refreshable
def _voice_gallery_body(engine: str, lang: str):
    samples_dir = vlib.VOICES_DIR / "_samples"
    voices = [(v, d) for v, d in tts.voices_for(engine, lang) if not v.startswith("lib:")]
    ready = sum(1 for v, _ in voices
                if tts.sample_path(samples_dir, engine, v).exists())
    with ui.row().classes("w-full items-center justify-between no-wrap"):
        ui.label(f"{len(voices)} vozes · {ready} amostras prontas").classes("mut text-sm")
        free = engine in ("edge",) or (engine == "gemini" and settings.gemini_ready)

        async def pregen_all():
            if job.running:
                ui.notify("Aguarde a tarefa atual", type="warning")
                return
            job.running = True
            job.i, job.n, job.msg = 0, len(voices), "Pré-gerando amostras…"

            def pcb(i, n):
                job.cb("voice", i, n, f"Amostra {i}/{n}…")

            try:
                ok, fail = await run.io_bound(tts.pregenerate_samples, samples_dir,
                                              engine, lang, pcb)
                ui.notify(f"{ok} amostras prontas" + (f", {fail} falharam" if fail else ""),
                          type="positive")
            except Exception as e:
                ui.notify(f"Erro: {e}", type="negative", multi_line=True, timeout=9000)
            finally:
                job.running = False
                _voice_gallery_body.refresh(engine, lang)

        btn = theme.primary_btn(
            "Gerar todas as amostras" if free else "Gerar todas (pode ter custo/tempo)",
            pregen_all, icon="auto_awesome")
        busy_guard(btn)

    with ui.column().classes("w-full gap-0").style("max-height:52vh;overflow-y:auto"):
        for vid, desc in voices:
            out = tts.sample_path(samples_dir, engine, vid)
            with ui.element("div").classes("syncrow w-full"):
                exists = out.exists()
                theme.pill("pronta" if exists else "gerar", "ok" if exists else "off")
                ui.label(desc).classes("text-sm grow")
                if exists:
                    ui.audio(voice_url(out)).style("height:34px;max-width:230px")
                else:
                    async def gen_one(vid=vid, desc=desc):
                        try:
                            await run.io_bound(tts.ensure_sample, samples_dir, engine,
                                               vid, lang)
                            _voice_gallery_body.refresh(engine, lang)
                        except Exception as e:
                            ui.notify(f"Erro em {desc[:20]}: {e}", type="negative",
                                      multi_line=True, timeout=8000)

                    b = ui.button(icon="play_circle", on_click=gen_one) \
                        .props("flat round dense").classes("ibtn")
                    busy_guard(b)


def voice_gallery_dialog(engine: str, lang: str):
    info = next((e for e in tts.engines_info() if e["id"] == engine), None)
    with ui.dialog() as dlg, ui.card().classes("card gap-3") \
            .style("width:640px;max-width:96vw;max-height:90vh"):
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label(f"Galeria de vozes — {info['label'] if info else engine}") \
                .classes("h-title").style("font-size:18px")
            theme.icon_btn("close", dlg.close)
        if info and not info["available"]:
            theme.pill(f"engine indisponível: {info['hint']}", "warn")
        ui.label("As amostras ficam salvas no software (voices/_samples) — geradas uma "
                 "vez, prontas para sempre.").classes("mut2 text-xs")
        _voice_gallery_body(engine, lang)
    dlg.open()


# --------------------------------------------------------- estúdio de voz
def voice_studio_dialog():
    with ui.dialog() as dlg, ui.card().classes("card gap-3") \
            .style("width:760px;max-width:96vw;max-height:92vh;overflow-y:auto"):
        ui.label("Estúdio de Voz — clone qualquer voz").classes("h-title") \
            .style("font-size:19px")
        ui.label("Envie qualquer áudio (ou vídeo) com a voz desejada. O estúdio separa a "
                 "voz da música, remove ruído e melhora a qualidade (DeepFilterNet3), "
                 "extrai o melhor trecho de fala e salva na biblioteca — depois é só "
                 "selecionar a voz nas engines Qwen3, Coqui XTTS ou Chatterbox, sem "
                 "reprocessar nada.").classes("mut text-sm")

        # ------- biblioteca
        saved = vlib.list_voices()
        if saved:
            ui.label("Vozes salvas").classes("card-h")
            with ui.column().classes("w-full gap-0"):
                for v in saved:
                    with ui.element("div").classes("syncrow w-full"):
                        ui.icon("record_voice_over").style("color:var(--acc)")
                        with ui.column().classes("gap-0").style("min-width:150px"):
                            ui.label(v["name"]).classes("text-sm font-medium")
                            ui.label(f"{v.get('duration', 0):.0f}s · {v.get('created', '')}") \
                                .classes("mut2 text-xs")
                        ui.audio(voice_url(Path(v["file"]))).classes("grow") \
                            .style("max-height:36px")
                        theme.icon_btn("delete", lambda s=v["slug"]: (
                            vlib.delete_voice(s), dlg.close(), voice_studio_dialog()),
                            "Apagar voz")
            ui.separator().classes("bg-white/10")

        # ------- nova clonagem
        ui.label("Clonar nova voz").classes("card-h")
        uploaded: list[Path] = []
        up_label = ui.label("Nenhum arquivo enviado").classes("mut2 text-xs")

        def on_upload(e):
            dest_dir = vlib.VOICES_DIR / "_upload"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / e.name
            dest.write_bytes(e.content.read())
            uploaded.clear()
            uploaded.append(dest)
            up_label.set_text(f"Arquivo: {e.name} ({dest.stat().st_size / 1e6:.1f} MB)")

        with ui.row().classes("w-full items-center gap-4 no-wrap"):
            ui.upload(on_upload=on_upload, auto_upload=True, max_files=1) \
                .props('accept="audio/*,video/*,.mp3,.wav,.m4a,.ogg,.mp4,.mkv" flat dense '
                       'color=dark label="Enviar áudio/vídeo"').classes("w-56")
            sep_sw = ui.switch("Separar voz de música/fundo", value=True) \
                .props("color=negative")
        prog_label = ui.label("").classes("text-sm").style("color:var(--acc)")
        result_box = ui.column().classes("w-full gap-2")

        async def process():
            if not uploaded:
                ui.notify("Envie um arquivo primeiro", type="warning")
                return
            if job.running:
                ui.notify("Aguarde a tarefa atual terminar", type="warning")
                return
            job.running = True
            job.cb("voice", 0, 1, "Preparando amostra de voz…")
            proc_btn.props("loading")
            result_box.clear()

            def pcb(msg: str):
                job.cb("voice", 0, 1, msg)
                prog_label.set_text(msg)

            try:
                res = await run.io_bound(vlib.clean_and_extract, uploaded[0], settings,
                                         bool(sep_sw.value), pcb)
                prog_label.set_text("")
                with result_box:
                    ui.label("Amostra extraída — ouça e confira:").classes("text-sm font-medium")
                    ui.audio(voice_url(res["segment"])).classes("w-full")
                    ref_ta = ui.textarea("Transcrição da amostra (necessária p/ Qwen3)",
                                         value=res["ref_text"]) \
                        .props("outlined dense autogrow").classes("w-full")
                    with ui.row().classes("w-full gap-3 no-wrap items-end"):
                        name_in = ui.input("Nome da voz",
                                           placeholder="Ex.: Narrador Grave João") \
                            .props("outlined dense").classes("grow")

                        def save():
                            if not (name_in.value or "").strip():
                                ui.notify("Dê um nome à voz", type="warning")
                                return
                            slug = vlib.save_voice(name_in.value.strip(), res["segment"],
                                                   ref_ta.value or "",
                                                   source=uploaded[0].name)
                            ui.notify(f"Voz '{name_in.value}' salva na biblioteca",
                                      type="positive")
                            dlg.close()
                            voice_studio_dialog()
                            refresh_all()

                        theme.primary_btn("Salvar na biblioteca", save, icon="save")
            except Exception as e:
                prog_label.set_text("")
                ui.notify(f"Erro no processamento: {e}", type="negative",
                          multi_line=True, timeout=12000)
            finally:
                job.running = False
                proc_btn.props(remove="loading")

        with ui.row().classes("w-full justify-end"):
            proc_btn = theme.primary_btn("Limpar e extrair amostra", process,
                                         icon="auto_fix_high")
        ui.label("Etapas: separação UVR → DeepFilterNet3 → normalização → melhor trecho "
                 "(VAD) → transcrição. Use só vozes que você tem direito de usar.") \
            .classes("mut2 text-xs")
    dlg.open()


# --------------------------------------------------------- central do canal
def _save_channel_asset(prompt: str, filename: str, size: tuple[int, int],
                        aspect: str) -> Path:
    from core import imagen
    from core.config import ROOT_DIR
    from PIL import Image

    out_dir = ROOT_DIR / "channel_kit"
    out_dir.mkdir(exist_ok=True)
    tmp = out_dir / f"_{filename}"
    imagen.generate_image(prompt, tmp, settings, "gemini",
                          dims=(min(size[0], 1920), min(size[1], 1920)), aspect=aspect)
    final = out_dir / filename
    Image.open(tmp).resize(size, Image.LANCZOS).save(final, quality=95)
    tmp.unlink(missing_ok=True)
    return final


def channel_dialog():
    with ui.dialog() as dlg, ui.card().classes("card gap-3") \
            .style("width:860px;max-width:96vw;max-height:92vh;overflow-y:auto"):
        ui.label("Central do Canal").classes("h-title").style("font-size:19px")
        ui.label("A equipe de agentes especializados analisa ou cria seu canal dark: "
                 "auditoria com correções, identidade completa (nome, logo, banner, "
                 "descrição, keywords) e aplicação automática do que a API do YouTube "
                 "permite.").classes("mut text-sm")
        with ui.row().classes("gap-2 wrap"):
            for a in AGENTS.values():
                with ui.row().classes("items-center gap-1 no-wrap") \
                        .style("background:var(--card2);border:1px solid var(--border-soft);"
                               "border-radius:999px;padding:3px 12px"):
                    ui.icon(a["icone"]).classes("text-sm").style("color:var(--acc)")
                    ui.label(a["nome"]).classes("text-xs font-medium")

        crew = Crew(settings)
        if not crew.available:
            theme.pill("os agentes precisam da GEMINI_API_KEY", "warn")

        # ================= A) auditar canal existente =================
        with ui.expansion("Analisar meu canal (correções automáticas)",
                          icon="fact_check").classes("card w-full"):
            ui.label("Passe a URL pública do canal. O Auditor cruza os dados com boas "
                     "práticas de crescimento/monetização e o que puder ser corrigido por "
                     "API (descrição, keywords, banner) é aplicado com 1 clique.") \
                .classes("mut text-sm")
            with ui.row().classes("w-full gap-2 no-wrap items-end"):
                ch_url = ui.input("URL do canal", placeholder="https://youtube.com/@seucanal") \
                    .props("outlined dense").classes("grow")
                audit_btn = theme.primary_btn("Auditar", None, icon="fact_check")
            audit_box = ui.column().classes("w-full gap-2")

            async def audit():
                if not (ch_url.value or "").strip():
                    ui.notify("Informe a URL do canal", type="warning")
                    return
                audit_btn.props("loading")
                audit_box.clear()
                try:
                    data = await run.io_bound(fetch_channel_public, ch_url.value.strip())
                    rep = await run.io_bound(crew.channel_audit, data, "pt-BR")
                    with audit_box:
                        with ui.row().classes("items-center gap-4"):
                            ui.label(str(rep.get("score", "?"))).classes("h-title") \
                                .style("font-size:34px;color:var(--acc)")
                            with ui.column().classes("gap-0"):
                                ui.label(f"{data.get('name')} · "
                                         f"{data.get('subscribers') or '?'} inscritos") \
                                    .classes("text-sm font-medium")
                                ui.label(rep.get("diagnostico", "")).classes("mut text-xs")
                        for f in rep.get("forcas", []):
                            theme.pill(f, "ok")
                        ui.label("Correções priorizadas").classes("card-h mt-2")
                        for c in rep.get("correcoes", []):
                            with ui.element("div").classes("syncrow w-full"):
                                theme.pill("auto" if c.get("automatico") else "manual",
                                           "acc" if c.get("automatico") else "off")
                                with ui.column().classes("gap-0 grow"):
                                    ui.label(f"{c.get('area', '')}: {c.get('problema', '')}") \
                                        .classes("text-sm")
                                    ui.label(c.get("acao", "")).classes("mut2 text-xs")
                        ui.label("Nova descrição do canal").classes("card-h mt-2")
                        desc_ta = ui.textarea(value=rep.get("descricao_otimizada", "")) \
                            .props("outlined dense autogrow").classes("w-full")
                        kw = rep.get("keywords", [])
                        ui.label("Keywords: " + ", ".join(kw)).classes("mut2 text-xs")
                        ui.label("Plano de 30 dias").classes("card-h mt-2")
                        for i, p in enumerate(rep.get("plano_30_dias", []), 1):
                            ui.label(f"{i}. {p}").classes("mut text-sm")

                        async def apply_api():
                            if not youtube.available():
                                ui.notify("Requer client_secret.json (veja README)",
                                          type="warning")
                                return
                            apply_btn.props("loading")
                            try:
                                await run.io_bound(youtube.update_channel_branding,
                                                   desc_ta.value, kw)
                                ui.notify("Descrição e keywords aplicadas no canal "
                                          "conectado!", type="positive", timeout=9000)
                            except Exception as e:
                                ui.notify(f"Erro na API: {e}", type="negative",
                                          multi_line=True, timeout=12000)
                            finally:
                                apply_btn.props(remove="loading")

                        with ui.row().classes("w-full justify-end gap-2 pt-2"):
                            apply_btn = theme.primary_btn(
                                "Aplicar correções automáticas no meu canal (API)",
                                apply_api, icon="cloud_sync")
                            if not youtube.available():
                                theme.pill("requer client_secret.json", "warn")
                except Exception as e:
                    ui.notify(f"Erro na auditoria: {e}", type="negative",
                              multi_line=True, timeout=12000)
                finally:
                    audit_btn.props(remove="loading")

            audit_btn.on_click(audit)

        # ================= B) criar canal do zero =================
        with ui.expansion("Criar canal do zero (kit completo)",
                          icon="brush").classes("card w-full"):
            ui.label("O YouTube não permite criar canais por API — mas a equipe monta TUDO "
                     "para você: nome, logo, banner, descrição, keywords e o passo a passo "
                     "exato (2 min de cliques). Depois conecte o OAuth e o app aplica "
                     "descrição/keywords/banner sozinho.").classes("mut text-sm")
            with ui.row().classes("w-full gap-3 no-wrap items-end"):
                kniche = niche_select()
                kaud = ui.input("Público-alvo (opcional)",
                                placeholder="ex.: homens 25-45 interessados em história") \
                    .props("outlined dense").classes("grow")
                kit_btn = theme.primary_btn("Montar kit", None, icon="auto_awesome")
            kit_box = ui.column().classes("w-full gap-2")

            async def make_kit():
                kit_btn.props("loading")
                kit_box.clear()
                try:
                    kit = await run.io_bound(crew.channel_kit, kniche.value,
                                             kaud.value or "", "pt-BR")
                    from core.config import ROOT_DIR
                    kit_dir = ROOT_DIR / "channel_kit"
                    kit_dir.mkdir(exist_ok=True)
                    import json as _json
                    (kit_dir / "kit.json").write_text(
                        _json.dumps(kit, indent=2, ensure_ascii=False), encoding="utf-8")
                    with kit_box:
                        ui.label("Nomes sugeridos").classes("card-h")
                        for nm in kit.get("nomes", []):
                            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                                theme.icon_btn("content_copy", lambda n=nm: (
                                    ui.clipboard.write(n.get("nome", "")),
                                    ui.notify("Nome copiado")), "Copiar")
                                ui.label(f"{nm.get('nome')} ({nm.get('handle', '')}) — "
                                         f"{nm.get('porque', '')}").classes("text-sm")
                        ui.label("Descrição do canal").classes("card-h mt-2")
                        kd = ui.textarea(value=kit.get("descricao", "")) \
                            .props("outlined dense autogrow").classes("w-full")
                        kws = kit.get("keywords", [])
                        ui.label("Keywords: " + ", ".join(kws)).classes("mut2 text-xs")
                        ui.label("Checklist de configuração + monetização").classes("card-h mt-2")
                        for i, c in enumerate(kit.get("checklist", []), 1):
                            ui.label(f"{i}. {c}").classes("mut text-sm")
                        ui.label(f"Trailer sugerido: {kit.get('trailer_ideia', '')}") \
                            .classes("mut2 text-xs mt-1")
                        assets_row = ui.row().classes("gap-3 items-end")

                        async def gen_assets():
                            assets_btn.props("loading")
                            try:
                                logo = await run.io_bound(
                                    _save_channel_asset, kit.get("logo_prompt", ""),
                                    "logo.png", (800, 800), "1:1")
                                banner = await run.io_bound(
                                    _save_channel_asset, kit.get("banner_prompt", ""),
                                    "banner.png", (2560, 1440), "16:9")
                                with assets_row:
                                    for pth, lbl in [(logo, "logo 800×800"),
                                                     (banner, "banner 2560×1440")]:
                                        with ui.column().classes("items-center gap-1"):
                                            ui.image(str(pth)).style(
                                                "width:180px;border-radius:10px")
                                            ui.label(lbl).classes("mut2 text-xs")
                                theme.ghost_btn("Abrir pasta do kit",
                                                lambda: open_folder(kit_dir),
                                                icon="folder_open")
                                ui.notify("Logo e banner gerados em channel_kit/",
                                          type="positive")
                            except Exception as e:
                                ui.notify(f"Erro nas imagens: {e}", type="negative",
                                          multi_line=True, timeout=12000)
                            finally:
                                assets_btn.props(remove="loading")

                        async def apply_kit():
                            if not youtube.available():
                                ui.notify("Requer client_secret.json (veja README)",
                                          type="warning")
                                return
                            try:
                                await run.io_bound(youtube.update_channel_branding,
                                                   kd.value, kws)
                                from core.config import ROOT_DIR as _R
                                banner_p = _R / "channel_kit" / "banner.png"
                                if banner_p.exists():
                                    await run.io_bound(youtube.set_channel_banner, banner_p)
                                ui.notify("Canal conectado configurado: descrição, keywords "
                                          "e banner aplicados! (logo/avatar: troque em "
                                          "youtube.com/account — a API não permite)",
                                          type="positive", timeout=12000)
                            except Exception as e:
                                ui.notify(f"Erro na API: {e}", type="negative",
                                          multi_line=True, timeout=12000)

                        with ui.row().classes("w-full justify-end gap-2 pt-2"):
                            assets_btn = theme.ghost_btn("Gerar logo + banner (IA)",
                                                         gen_assets, icon="image")
                            theme.primary_btn("Aplicar no canal conectado (API)",
                                              apply_kit, icon="cloud_sync")
                except Exception as e:
                    ui.notify(f"Erro no kit: {e}", type="negative",
                              multi_line=True, timeout=12000)
                finally:
                    kit_btn.props(remove="loading")

            kit_btn.on_click(make_kit)

        ui.label("O que a API do YouTube NÃO permite (o app te guia): criar o canal em si, "
                 "trocar nome e avatar. Tudo o mais — descrição, keywords, banner, uploads, "
                 "agendamentos e metadados dos vídeos — o DarkStudio aplica sozinho.") \
            .classes("mut2 text-xs")
    dlg.open()


# ------------------------------------------------------ agendador de produção
def scheduler_dialog():
    with ui.dialog() as dlg, ui.card().classes("card gap-3") \
            .style("width:820px;max-width:96vw;max-height:92vh;overflow-y:auto"):
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label("Agendador de produção automática").classes("h-title") \
                .style("font-size:19px")
            with ui.row().classes("items-center gap-2 no-wrap"):
                sa_lbl = ui.label("produz tudo até o MP4").classes("mut2 text-xs")
                sched_auto = ui.switch("Automático", value=True).props("color=negative")
                sched_auto.on_value_change(lambda e: sa_lbl.set_text(
                    "produz tudo até o MP4" if e.value
                    else "só cria os roteiros na data"))
        ui.label("Programe ideias para o app produzir no dia e hora marcados. Com o toggle "
                 "Automático LIGADO, produz cada vídeo até o MP4 (+ upload opcional) "
                 "sozinho, avançando por todas as etapas. DESLIGADO, só cria os projetos "
                 "com roteiro na data. O app precisa estar aberto na hora; produções "
                 "atrasadas rodam assim que ele abrir.").classes("mut text-sm")

        # ----- fila atual
        jobs = sched.load_jobs()
        if jobs:
            ui.label("Fila programada").classes("card-h")
            status_pill = {"pending": ("agendado", "off"), "running": ("produzindo", "acc"),
                           "done": ("concluído", "ok"), "error": ("erro", "warn")}
            with ui.column().classes("w-full gap-0"):
                for j in sorted(jobs, key=lambda x: x["run_at"]):
                    with ui.element("div").classes("syncrow w-full"):
                        txt, kind = status_pill.get(j["status"], ("?", "off"))
                        theme.pill(txt, kind)
                        ui.label(j["run_at"].replace("T", " ")).classes("tchip")
                        ui.label(j["idea"][:58]).classes("text-sm grow")
                        if j.get("url"):
                            ui.label(j["url"]).classes("mono text-xs").style("color:var(--ok)")
                        if j.get("error"):
                            with ui.icon("error_outline").classes("text-sm") \
                                    .style("color:var(--warn)"):
                                ui.tooltip(j["error"][:300])
                        if j.get("project") and j["status"] == "done":
                            def open_proj(slug=j["project"]):
                                state.project = Project.load(slug)
                                state.step = "export"
                                dlg.close()
                                refresh_all()
                            theme.icon_btn("open_in_new", open_proj, "Abrir projeto")
                        if j["status"] != "running":
                            theme.icon_btn("delete", lambda jid=j["id"]: (
                                sched.delete_job(jid), dlg.close(), scheduler_dialog()),
                                "Remover")

        ui.separator().classes("bg-white/10")
        ui.label("Programar novos vídeos").classes("card-h")
        ideas_ta = ui.textarea(placeholder="Uma ideia por linha…\nO tesouro perdido dos "
                                           "incas\nA vila que congelou no tempo") \
            .props("outlined autogrow input-style=min-height:90px").classes("w-full")

        def fill_ideas(titles: list[str]):
            cur = (ideas_ta.value or "").strip()
            ideas_ta.set_value((cur + "\n" if cur else "") + "\n".join(titles))

        with ui.row().classes("w-full justify-end"):
            theme.ghost_btn("Sugerir histórias (IA)", lambda: ideas_dialog(fill_ideas),
                            icon="insights")
        with ui.row().classes("w-full gap-3 no-wrap items-end"):
            run_at_in = ui.input("Produzir em (dia e hora)") \
                .props("outlined dense type=datetime-local").classes("w-64")
            ui.label("As configurações abaixo se aplicam a todos os vídeos agendados.") \
                .classes("mut2 text-xs self-center")

        ui.separator().classes("bg-white/10")
        get_cfg = video_config_form()
        ui.separator().classes("bg-white/10")

        yt_ok = youtube.available()
        up_sw = ui.switch("Publicar no YouTube automaticamente ao terminar",
                          value=False).props("color=negative")
        if not yt_ok:
            up_sw.disable()
            theme.pill("upload automático requer client_secret.json (veja README)", "warn")
        up_row = ui.row().classes("w-full gap-3 no-wrap items-end")
        with up_row:
            yt_priv = ui.select({"public": "Público", "unlisted": "Não listado",
                                 "private": "Privado"}, value="public",
                                label="Visibilidade").props("outlined dense").classes("w-36")
            pub_first = ui.input("1ª publicação em (opcional)") \
                .props("outlined dense type=datetime-local").classes("w-56")
            interval = ui.number("Intervalo entre vídeos (horas)", value=24, min=1, max=168) \
                .props("outlined dense").classes("w-52")
        up_row.bind_visibility_from(up_sw, "value")
        ui.label("Com agendamento de publicação, cada vídeo entra como privado e o YouTube "
                 "libera na hora marcada (1º na data acima, os demais a cada intervalo).") \
            .classes("mut2 text-xs").bind_visibility_from(up_sw, "value")

        def save_schedule():
            ideas = [l.strip() for l in (ideas_ta.value or "").splitlines() if l.strip()]
            if not ideas:
                ui.notify("Cole ao menos uma ideia", type="warning")
                return
            if not (run_at_in.value or "").strip():
                ui.notify("Defina dia e hora da produção", type="warning")
                return
            if not settings.gemini_api_key:
                ui.notify("A produção automática precisa da GEMINI_API_KEY", type="warning")
                return
            try:
                run_at = datetime.fromisoformat(run_at_in.value)
            except ValueError:
                ui.notify("Data/hora inválida", type="warning")
                return
            cfg = get_cfg()
            cfg["auto_produce"] = bool(sched_auto.value)
            upload = {"enabled": bool(up_sw.value and yt_ok), "privacy": yt_priv.value,
                      "publish_first_at": pub_first.value or None,
                      "interval_h": interval.value or 24}
            n = sched.add_jobs(ideas, run_at, cfg, upload)
            ui.notify(f"{n} vídeo(s) programado(s) para "
                      f"{run_at.strftime('%d/%m às %H:%M')}", type="positive")
            dlg.close()

        with ui.row().classes("w-full justify-end gap-2"):
            theme.ghost_btn("Fechar", dlg.close)
            theme.primary_btn("Programar produção", save_schedule, icon="event")
    dlg.open()


# ------------------------------------------------------------------- barra
@ui.refreshable
def header_status():
    with ui.row().classes("items-center gap-3 no-wrap"):
        if settings.use_vertex and settings.vertex_project:
            theme.pill("Vertex AI (OAuth)", "ok")
        elif settings.gemini_api_key:
            theme.pill("API conectada", "ok")
        elif settings.deepseek_api_key:
            theme.pill("DeepSeek reserva ativa", "warn")
        else:
            theme.pill("sem chave de API", "warn")
        if state.project:
            theme.icon_btn("folder_open", lambda: open_folder(state.project.dir),
                           "Abrir pasta do projeto")
        theme.icon_btn("settings", settings_dialog, "Configurações")


def header_bar():
    with ui.header().classes("appbar"):
        with ui.row().classes("items-center gap-3 no-wrap w-full"):
            ui.element("div").classes("logo-dot")
            ui.html('<span class="wordmark">DARK<b>STUDIO</b></span>')
            ui.element("div").style("width:1px;height:22px;background:var(--border)")

            projects = Project.list_all()
            options = {p.slug: p.state["name"] for p in projects}
            sel = ui.select(options or {"": "nenhum projeto"},
                            value=state.project.slug if state.project else None) \
                .props("outlined dense options-dense borderless") \
                .style("min-width:220px")

            def change(e):
                if e.value and e.value in options:
                    state.project = Project.load(e.value)
                    app.storage.general["last_project"] = e.value
                    state.step = "script"
                    refresh_all()

            sel.on_value_change(change)
            theme.icon_btn("add_circle_outline", new_project_dialog, "Novo projeto")
            ui.element("div").style("width:1px;height:22px;background:var(--border)")
            theme.icon_btn("change_circle", remodel_dialog,
                           "Remodelar canal do YouTube")
            theme.icon_btn("precision_manufacturing", batch_dialog,
                           "Produção em lote (agora)")
            theme.icon_btn("event", scheduler_dialog,
                           "Agendar produção automática")
            theme.icon_btn("record_voice_over", voice_studio_dialog,
                           "Estúdio de Voz — clonagem")
            theme.icon_btn("tv", channel_dialog,
                           "Central do Canal — auditar/criar")
            ui.element("div").classes("grow")
            header_status()


# ------------------------------------------------------------------ sidebar
@ui.refreshable
def sidebar():
    with ui.column().classes("w-full h-full gap-0 px-3 py-4"):
        ui.label("Pipeline").classes("eyebrow px-3 pb-3")
        with ui.column().classes("stepper w-full gap-1"):
            for i, (sid, label, icon, _) in enumerate(STEPS, 1):
                done = state.project.stage_done(sid) if state.project else False
                unlocked = step_unlocked(sid)
                cls = "stp w-full"
                if state.step == sid:
                    cls += " cur"
                if done:
                    cls += " ok"
                if not unlocked:
                    cls += " lock"
                with ui.element("div").classes(cls) as item:
                    if done:
                        ui.html('<div class="dot"><span class="material-icons" '
                                'style="font-size:15px">check</span></div>')
                    elif not unlocked:
                        ui.html('<div class="dot"><span class="material-icons" '
                                'style="font-size:13px">lock</span></div>')
                    else:
                        ui.html(f'<div class="dot">{i}</div>')
                    ui.label(label).classes("t")
                    cap = step_caption(sid)
                    if cap:
                        ui.label(cap).classes("c")
                if unlocked:
                    item.on("click", lambda sid=sid: goto(sid))

        ui.element("div").classes("grow")
        with ui.column().classes("px-3 gap-1"):
            ui.label("DarkStudio 1.0").classes("mut2 text-xs")
            ui.label("edge-tts · faster-whisper · Gemini · FFmpeg").classes("mut2 text-xs")


# --------------------------------------------------------------- progresso
def job_panel():
    with ui.element("div").classes("jobbar") as bar:
        bar.bind_visibility_from(job, "running")
        ui.linear_progress(show_value=False, size="3px").props("color=negative") \
            .bind_value_from(job, "i", backward=lambda _: job.fraction)
    with ui.row().classes("jobcard w-full items-center gap-4 px-5 py-3 no-wrap") as card:
        card.bind_visibility_from(job, "running")
        ui.spinner("dots", size="30px", color="negative")
        with ui.column().classes("gap-1 grow"):
            ui.label().bind_text_from(job, "msg").classes("text-sm font-medium")
            ui.linear_progress(show_value=False, size="6px").props("rounded color=negative track-color=grey-10") \
                .bind_value_from(job, "i", backward=lambda _: job.fraction).classes("w-full")
        ui.label().bind_text_from(job, "i", backward=lambda _: f"{job.fraction:.0%}") \
            .classes("mono mut text-sm")
        ui.button("Cancelar", on_click=lambda: (pipeline.CANCEL.set(),
                                                ui.notify("Cancelando após a cena atual…"))) \
            .props("outline no-caps size=sm color=negative")


def busy_guard(btn: ui.button) -> ui.button:
    btn.bind_enabled_from(job, "running", backward=lambda r: not r)
    return btn


def wizard_footer():
    idx = STEP_IDS.index(state.step)
    with ui.row().classes("wfooter w-full items-center justify-between px-2 py-3 mt-2"):
        if idx > 0:
            theme.ghost_btn("Voltar", lambda: goto(STEP_IDS[idx - 1]), icon="arrow_back")
        else:
            ui.element("div")
        if idx < len(STEP_IDS) - 1:
            nxt = STEP_IDS[idx + 1]
            b = theme.primary_btn("Continuar", lambda: goto(nxt))
            b.props("icon-right=arrow_forward")
            if not step_unlocked(nxt):
                b.disable()
        else:
            ui.element("div")


# ------------------------------------------------------------------- telas
def panel_welcome():
    with ui.column().classes("w-full items-center gap-8 py-24"):
        with ui.column().classes("items-center gap-3"):
            with ui.row().classes("items-center gap-3"):
                ui.element("div").classes("logo-dot").style("width:14px;height:14px")
                ui.html('<span class="wordmark" style="font-size:22px">DARK<b>STUDIO</b></span>')
            ui.label("Estúdio de vídeos narrados por IA — do roteiro ao MP4 pronto para o YouTube.") \
                .classes("h-sub text-center")
        with ui.row().classes("gap-4"):
            for icon, t, d in [
                ("mic", "Narração neural", "vozes pt-BR realistas, grátis"),
                ("auto_awesome", "Cenas por IA", "uma imagem para cada frase"),
                ("subtitles", "Karaokê exato", "palavra a palavra via whisper"),
            ]:
                with ui.column().classes("card items-start gap-1").style("width:210px;padding:16px 18px"):
                    ui.icon(icon).classes("text-xl").style("color:var(--acc)")
                    ui.label(t).classes("font-semibold text-sm")
                    ui.label(d).classes("mut2 text-xs")
        theme.primary_btn("Criar primeiro projeto", new_project_dialog, icon="add")


def panel_script():
    p = state.project
    st = p.state["script"]

    with theme.card("Gerar roteiro com IA (opcional)"):
        with ui.row().classes("w-full gap-3 no-wrap items-end"):
            idea_in = ui.input("Ideia / tema do vídeo",
                               placeholder="Ex.: o navio que sumiu com 300 pessoas") \
                .props("outlined dense").classes("grow")
            gniche = niche_select("Nicho", classes="w-64")
            gmin = ui.select({1: "~1 min", 3: "~3 min", 5: "~5 min", 8: "~8 min", 12: "~12 min"},
                             value=3, label="Duração").props("outlined dense").classes("w-28")
            gtone = ui.select(TONES, value=TONES[0], label="Tom") \
                .props("outlined dense").classes("w-56")
            theme.icon_btn("insights",
                           lambda: ideas_dialog(
                               lambda ts: idea_in.set_value(ts[0]),
                               preset_niche=gniche.value,
                               preset_extra=f"tom desejado: {gtone.value}"),
                           "Sugerir ideias com base no nicho e tom selecionados")
            gen_btn = theme.primary_btn("Escrever", None, icon="auto_awesome")

        async def gen_script():
            if not (idea_in.value or "").strip():
                ui.notify("Descreva a ideia do vídeo", type="warning")
                return
            if not settings.gemini_api_key:
                ui.notify("O gerador precisa da GEMINI_API_KEY", type="warning")
                return
            gen_btn.props("loading")
            try:
                llm = LLM(settings)
                script = await run.io_bound(llm.generate_script, idea_in.value,
                                            float(gmin.value), gtone.value,
                                            st["language"], gniche.value or "")
                text.set_value(script)
                ui.notify("Roteiro gerado — revise e salve", type="positive")
            except Exception as e:
                ui.notify(f"Erro: {e}", type="negative", multi_line=True, timeout=10000)
            finally:
                gen_btn.props(remove="loading")

        gen_btn.on_click(gen_script)

    with theme.card("Roteiro da narração"):
        text = ui.textarea(value=st["text"],
                           placeholder="Cole aqui o roteiro completo do vídeo…") \
            .classes("w-full").props("outlined autogrow input-style=min-height:280px")
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            info = ui.label().classes("mut2 text-xs")
            with ui.row().classes("items-end gap-3 no-wrap"):
                fmt_sel = ui.select({"16:9": "16:9 — YouTube", "9:16": "9:16 — Shorts/TikTok",
                                     "1:1": "1:1 — quadrado"},
                                    value=p.state.get("format", "16:9"), label="Formato") \
                    .props("outlined dense").classes("w-48")

                def change_format(e):
                    p.state["format"] = e.value
                    for stage in ("images", "animation", "export"):
                        p.state[stage]["done"] = False
                    p.save()
                    ui.notify(f"Formato {e.value} — imagens e render serão refeitos nesse "
                              "quadro", type="info")
                    sidebar.refresh()

                fmt_sel.on_value_change(change_format)
                lang = ui.select(LANGUAGES, value=st["language"], label="Idioma") \
                    .props("outlined dense").classes("w-52")

                async def save_script():
                    if not (text.value or "").strip():
                        ui.notify("O roteiro está vazio", type="warning")
                        return
                    p.set_script(text.value, lang.value)
                    ui.notify(f"Roteiro salvo — {len(p.sentences)} cenas", type="positive")
                    goto("tts")
                    if app.storage.general.get("autopilot"):
                        await _autopilot_next()   # piloto assume a partir daqui

                busy_guard(theme.primary_btn("Salvar roteiro", save_script, icon="save"))

        def update_info():
            from core.textproc import split_sentences
            n = len(split_sentences(text.value or ""))
            words = len((text.value or "").split())
            wpm = 175 if p.state["script"]["language"] in ("pt-BR", "es-ES") else 165
            secs = round(words / wpm * 60)
            info.set_text(f"{words} palavras · {n} cenas · ~{secs // 60}:{secs % 60:02d} "
                          f"de narração (estimado)")

        text.on_value_change(lambda e: update_info())
        update_info()

    if st["sentences"]:
        with theme.card(f"{len(st['sentences'])} cenas detectadas"):
            with ui.column().classes("w-full gap-0"):
                for i, s in enumerate(st["sentences"], 1):
                    with ui.element("div").classes("syncrow"):
                        ui.label(f"{i:02d}").classes("tchip")
                        ui.label(s).classes("text-sm mut")


def panel_tts():
    p = state.project
    st = p.state["tts"]
    lang = p.state["script"]["language"]
    engines = tts.engines_info()

    # sanitiza valores salvos: engine/voz que não existem mais (lista atualizada,
    # voz clonada apagada, idioma trocado) quebravam a montagem da tela
    if st["engine"] not in {e["id"] for e in engines}:
        st["engine"] = "edge"
        p.save()
    voice_opts = {v: d for v, d in tts.voices_for(st["engine"], lang)}
    if st["voice"] not in voice_opts:
        st["voice"] = next(iter(voice_opts), "")
        p.save()
        ui.notify("A voz salva neste projeto não existe mais — troquei para "
                  f"“{voice_opts.get(st['voice'], st['voice'])}”. Gere a narração de novo "
                  "se necessário.", type="warning", timeout=8000)
    cur = next((e for e in engines if e["id"] == st["engine"]), engines[0])

    with theme.card("Voz da narração"):
        def eng_label(e):
            if e["available"]:
                return e["label"]
            return e["label"] + (" — requer chave" if e["needs_key"] else " — não instalado")

        eng_opts = {e["id"]: eng_label(e) for e in engines}
        with ui.row().classes("w-full gap-3 no-wrap"):
            eng = ui.select(eng_opts, value=st["engine"], label="Engine TTS") \
                .props("outlined dense").classes("w-80")
            voice = ui.select(voice_opts, value=st["voice"] or None, label="Voz") \
                .props("outlined dense").classes("grow")

            # diálogo criado ANTES do clique (criar UI depois de await falhava)
            with ui.dialog() as sample_dlg, ui.card().classes("card gap-2") \
                    .style("width:440px"):
                sample_title = ui.label("Amostra de voz").classes("card-h")
                sample_audio = ui.audio("").props("controls autoplay").classes("w-full")
                sample_note = ui.label("").classes("mut2 text-xs")

            async def preview_voice():
                engine, voice = st["engine"], st["voice"]
                style = st.get("style", "") if engine in ("gemini", "openai") else ""
                samples_dir = vlib.VOICES_DIR / "_samples"
                out = tts.sample_path(samples_dir, engine, voice, style)
                slow = engine in ("qwen3", "coqui", "chatterbox")
                prev_btn.props("loading")
                if slow and not out.exists():
                    ui.notify("Gerando amostra (modelo local — pode levar até 1 min "
                              "na 1ª vez)…", type="ongoing", timeout=4000)
                try:
                    if voice.startswith("lib:"):
                        out = Path(vlib.resolve(voice)["path"])
                    else:
                        out = await run.io_bound(tts.ensure_sample, samples_dir, engine,
                                                 voice, lang, style, int(st.get("rate", 0)))
                    label = dict(tts.voices_for(engine, lang)).get(voice, voice)
                    sample_title.set_text(f"Amostra — {label[:46]}")
                    sample_note.set_text("Amostra salva — o próximo play é instantâneo.")
                    sample_audio.set_source(voice_url(out))
                    sample_dlg.open()
                except Exception as e:
                    try:
                        ui.notify(f"Erro na amostra ({engine}): {e}", type="negative",
                                  multi_line=True, timeout=10000, close_button=True)
                    except Exception:
                        pass
                finally:
                    try:
                        prev_btn.props(remove="loading")
                    except Exception:
                        pass

            prev_btn = ui.button(icon="play_circle", on_click=preview_voice) \
                .props("flat round").classes("ibtn self-end")
            with prev_btn:
                ui.tooltip("Ouvir amostra desta voz (fica salva para reuso)")
            gallery_btn = ui.button(icon="library_music",
                                    on_click=lambda: voice_gallery_dialog(st["engine"], lang)) \
                .props("flat round").classes("ibtn self-end")
            with gallery_btn:
                ui.tooltip("Galeria de vozes — ouça e pré-gere todas")

        hint = ui.label(cur["hint"]).classes("mut2 text-xs")
        if not cur["available"] and cur["needs_key"]:
            theme.pill(f"adicione a {cur['needs_key']} nas Configurações", "warn")
        if st["engine"] in tts.LOCAL_ENGINES:
            dev = tts.device_label()
            is_gpu = dev.startswith("GPU")
            theme.pill(("⚡ roda na " if is_gpu else "🐢 roda na ") + dev,
                       "ok" if is_gpu else "warn")
            if st["engine"] in ("coqui", "qwen3", "chatterbox"):
                n_cenas = len(p.sentences)
                # ~10s por bloco de ~2-3 frases + ~30s de carga inicial
                est = 30 + (n_cenas / 2.5) * 10
                if is_gpu:
                    ui.html(f'<span class="pill warn"><i></i>Roteiro de {n_cenas} cenas '
                            f'≈ ~{int(est // 60)} min nesta GPU. Modelo autoregressive '
                            f'(gera fala token a token) — lento por natureza.</span>')
                ui.label("Modelo pesado: a 1ª narração carrega o modelo (~30s); as "
                         "seguintes reaproveitam. Para narração LONGA e rápida, use Edge "
                         "(segundos) — reserve as vozes locais/clonadas para quando a "
                         "identidade da voz é essencial, ou gere em lote de madrugada.") \
                    .classes("mut2 text-xs")
        if st["engine"] in tts.CLONE_ENGINES:
            with ui.row().classes("w-full items-center gap-3"):
                ui.label("Esta engine aceita vozes clonadas da sua biblioteca.") \
                    .classes("mut2 text-xs")
                theme.ghost_btn("Estúdio de Voz", voice_studio_dialog,
                                icon="record_voice_over")

        # instrução de estilo (engines que aceitam direção de atuação)
        if cur.get("style"):
            style_in = ui.input(
                "Instrução de estilo (opcional)", value=st.get("style", ""),
                placeholder='Ex.: "narre em tom sombrio e misterioso, ritmo lento"') \
                .props("outlined dense").classes("w-full")
            style_in.on("blur", lambda: (st.update({"style": style_in.value or ""}), p.save()))

        def engine_changed(e):
            info = next((x for x in engines if x["id"] == e.value), None)
            if info and not info["available"]:
                ui.notify(("Adicione a chave nas Configurações: " + info["needs_key"])
                          if info["needs_key"] else f"Instale no .venv: {info['hint']}",
                          type="warning", timeout=9000)
            vs = tts.voices_for(e.value, lang)
            st["engine"] = e.value
            st["voice"] = vs[0][0] if vs else ""
            p.save()
            refresh_all()

        eng.on_value_change(engine_changed)
        voice.on_value_change(lambda e: (st.update({"voice": e.value}), p.save()))

        with ui.row().classes("w-full items-center gap-4 no-wrap"):
            ui.label("Velocidade").classes("mut text-sm")
            rate = ui.slider(min=-30, max=30, step=5, value=st.get("rate", 0)) \
                .props("label color=negative").classes("w-56")
            rate.on_value_change(lambda e: (st.update({"rate": e.value}), p.save()))
            ui.element("div").classes("grow")
            busy_guard(theme.primary_btn("Gerar narração", lambda: run_stage(
                pipeline.run_tts, success="Narração gerada"), icon="graphic_eq"))

    if st.get("audio") and (p.dir / st["audio"]).exists():
        with theme.card("Narração gerada"):
            with ui.row().classes("w-full items-center gap-4 no-wrap"):
                ui.icon("volume_up").style("color:var(--acc)")
                ui.audio(media_url(st["audio"])).classes("grow")
                ui.label(f"{st.get('duration', 0):.1f}s").classes("mono mut text-sm")


def panel_transcription():
    p = state.project
    st = p.state["transcription"]

    with theme.card("Sincronização por palavra — faster-whisper"):
        ui.label("Detecta o tempo exato de cada frase e palavra da narração. É a base do "
                 "corte de cenas e do efeito karaokê.").classes("mut text-sm")
        with ui.row().classes("w-full items-end gap-4 no-wrap"):
            model = ui.select(["tiny", "base", "small", "medium", "large-v3"],
                              value=st.get("model", settings.whisper_model),
                              label="Modelo whisper").props("outlined dense").classes("w-48")
            model.on_value_change(lambda e: (st.update({"model": e.value}), p.save()))
            ui.label("roda em CPU (int8) · 1ª execução baixa o modelo").classes("mut2 text-xs")
            ui.element("div").classes("grow")
            busy_guard(theme.primary_btn("Sincronizar narração", lambda: run_stage(
                pipeline.run_transcription, success="Sincronização concluída"), icon="av_timer"))

    sents = st.get("sentences") or []
    if sents:
        max_dur = max((s["end"] - s["start"]) for s in sents) or 1
        with theme.card(f"Linha do tempo — {len(sents)} frases"):
            with ui.column().classes("w-full gap-0"):
                for s in sents:
                    dur = s["end"] - s["start"]
                    with ui.element("div").classes("syncrow"):
                        ui.label(f"{s['start']:6.2f}s").classes("tchip")
                        ui.label(f"{s['end']:6.2f}s").classes("tchip")
                        ui.element("div").classes("durbar") \
                            .style(f"width:{max(6, dur / max_dur * 120):.0f}px")
                        ui.label(f"{dur:.1f}s").classes("mono mut2 text-xs").style("min-width:34px")
                        ui.label(s["text"]).classes("text-sm grow")


def panel_style():
    p = state.project
    st = p.state["style"]
    llm_ok = bool(settings.gemini_api_key)

    with theme.card("Escolha o estilo das imagens"):
        with ui.element("div").classes("style-grid"):
            for sid, s in STYLES.items():
                selected = st["id"] == sid
                with ui.element("div").classes("stylecard" + (" sel" if selected else "")) as cardel:
                    ui.html(f'<div class="thumb">'
                            f'{theme.STYLE_THUMBS.get(sid, theme.DEFAULT_THUMB)}</div>')
                    with ui.element("div").classes("meta"):
                        ui.html(f'<div class="n">{s["label"]}</div>'
                                f'<div class="d">{s["desc"]}</div>')
                    if selected:
                        ui.html('<div class="selpin"><span class="material-icons" '
                                'style="font-size:14px">check</span></div>')

                def select_style(sid=sid):
                    changed = st["id"] != sid
                    st["id"] = sid
                    st["done"] = False
                    if changed:
                        # novo estilo → prompts e imagens antigos não valem mais
                        st.update({"prompts": [], "scenes": []})
                        p.clear_images()
                    p.invalidate_after("style")
                    p.save()
                    if changed:
                        ui.notify("Estilo trocado — gere os prompts de cena de novo; "
                                  "as imagens antigas foram limpas", type="info")
                    refresh_all()

                cardel.on("click", select_style)

    if st["id"] == "custom":
        with theme.card("Estilo personalizado"):
            desc = ui.textarea(
                value=(st.get("custom_style") or {}).get("user_desc", ""),
                placeholder="Descreva o estilo: técnica, cores, iluminação, referências… "
                            "Ex.: pintura a óleo renascentista sombria, tons de vinho e dourado, "
                            "luz de vela, pinceladas visíveis") \
                .classes("w-full").props("outlined autogrow")

            async def gen_custom():
                if not (desc.value or "").strip():
                    ui.notify("Descreva o estilo primeiro", type="warning")
                    return
                ui.notify("Gerando super prompt…")
                llm = LLM(settings)
                result = await run.io_bound(llm.custom_style, desc.value)
                result["user_desc"] = desc.value
                st["custom_style"] = result
                p.save()
                refresh_all()
                ui.notify(f"Estilo '{result.get('name')}' criado", type="positive")

            with ui.row().classes("w-full justify-end"):
                busy_guard(theme.primary_btn(
                    "Gerar super prompt com IA" if llm_ok else "Usar descrição como estilo",
                    gen_custom, icon="auto_awesome"))
            cs = st.get("custom_style")
            if cs and cs.get("template"):
                tpl = ui.textarea("Super prompt (editável)", value=cs["template"]) \
                    .classes("w-full").props("outlined autogrow")
                tpl.on("blur", lambda: (cs.update({"template": tpl.value}), p.save()))

    with theme.card("Engenharia de prompt por frase"):
        if llm_ok:
            ui.label("A IA analisa o roteiro, fixa personagens e cenário para manter "
                     "consistência visual e escreve um prompt profissional por frase.") \
                .classes("mut text-sm")
        else:
            theme.pill("sem chave de API — prompts usarão frase literal + estilo", "warn")
        with ui.row().classes("w-full justify-end"):
            busy_guard(theme.primary_btn("Gerar prompts de cena", lambda: run_stage(
                pipeline.run_style_prompts, success="Prompts prontos"), icon="bolt"))

    if st.get("prompts"):
        analysis = st.get("analysis") or {}
        if analysis.get("characters"):
            with theme.card("Consistência real de personagem"):
                ui.label("Gere uma imagem de referência por personagem: ela é enviada junto "
                         "de cada cena para o Nano Banana manter o MESMO rosto, cabelo e "
                         "roupa do início ao fim.").classes("mut text-sm")
                for c in analysis["characters"]:
                    ui.label(f"• {c.get('name')} — {c.get('description', '')[:130]}") \
                        .classes("mut2 text-xs")
                refs = st.get("char_refs") or []
                if refs:
                    with ui.row().classes("gap-3"):
                        for r in refs:
                            if (p.dir / r["file"]).exists():
                                with ui.column().classes("items-center gap-1"):
                                    src = media_url(r["file"])
                                    img = ui.image(src).style(
                                        "width:96px;height:96px;border-radius:10px;"
                                        "object-fit:cover;cursor:zoom-in")
                                    img.on("click", lambda src=src: preview_image(src))
                                    ui.label(r["name"][:16]).classes("mut2 text-xs")
                with ui.row().classes("w-full justify-end"):
                    busy_guard(theme.ghost_btn(
                        "Regenerar referências" if refs else "Gerar referências de personagem",
                        lambda: run_stage(pipeline.run_char_refs,
                                          success="Referências prontas"), icon="face"))
        with ui.expansion(f"Ver e editar os {len(st['prompts'])} prompts", icon="edit_note") \
                .classes("card w-full"):
            for i, prompt in enumerate(st["prompts"]):
                frase = p.sentences[i][:88] if i < len(p.sentences) else ""
                ui.label(f"cena {i + 1:02d} · {frase}").classes("mut2 text-xs mt-2 mono")
                ta = ui.textarea(value=prompt).classes("w-full").props("outlined autogrow dense")

                def save_prompt(i=i, ta=ta):
                    st["prompts"][i] = ta.value
                    p.save()

                ta.on("blur", save_prompt)


def _image_grid_view():
    p = state.project
    st = p.state["images"]
    prompts = p.state["style"].get("prompts") or []
    files = st.get("files") or []
    if not prompts:
        return

    elements = []
    with ui.element("div").classes("img-grid"):
        for i in range(len(prompts)):
            rel = files[i] if i < len(files) else None
            with ui.element("div").classes("imgcard"):
                src = media_url(rel) if (rel and (p.dir / rel).exists()) else ""
                
                img = ui.image(src).props("no-spinner fit=cover")
                if not src:
                    img.classes("hidden")
                    
                skel = ui.html('<div class="img-skel">aguardando geração</div>')
                if src:
                    skel.classes("hidden")
                    
                img.on("click", lambda e, idx=i: image_detail(idx))
                
                ui.html(f'<div class="idx">{i + 1:02d}</div>')
                with ui.element("div").classes("acts"):
                    b = ui.button(icon="refresh", on_click=lambda i=i: run_stage(
                        pipeline.run_images, [i], success=f"Cena {i + 1} regenerada"))
                    b.props("round dense unelevated size=sm color=dark")
                    busy_guard(b)
                
                elements.append((img, skel))

    def update_grid():
        current_files = p.state["images"].get("files") or []
        for i, (img, skel) in enumerate(elements):
            rel = current_files[i] if i < len(current_files) else None
            if rel and (p.dir / rel).exists():
                src = media_url(rel)
                if img.source != src:
                    img.set_source(src)
                    img.classes(remove="hidden")
                    skel.classes("hidden")

    if job.running and state.step == "images":
        ui.timer(1.0, update_grid)


def panel_images():
    p = state.project
    st = p.state["images"]
    prompts = p.state["style"].get("prompts") or []
    files = st.get("files") or []
    done_count = sum(1 for f in files if f)

    with theme.card(f"Geração de imagens — {done_count}/{len(prompts)}"):
        async def gen(indices, label):
            n = len(indices) if indices else len(prompts)
            if st.get("provider") == "gemini" and n > 8:
                if not await confirm_cost(n, settings.image_cost_usd, label):
                    return
            await run_stage(pipeline.run_images, indices, success="Imagens geradas")

        with ui.row().classes("w-full items-end gap-3 no-wrap"):
            prov = ui.select(PROVIDERS, value=st.get("provider", "gemini"),
                             label="Provedor").props("outlined dense").classes("w-72")
            prov.on_value_change(lambda e: (st.update({"provider": e.value}), p.save(),
                                            refresh_all()))
            # modelo local escolhido AQUI (não mais escondido nas Configurações)
            if st.get("provider") == "local":
                from core.imagen import LOCAL_IMAGE_MODELS
                lm = ui.select({k: v[1].split(" — ")[0] + " — " + v[1].split(" — ")[1][:28]
                                for k, v in LOCAL_IMAGE_MODELS.items()},
                               value=settings.local_image_model, label="Modelo (GPU)") \
                    .props("outlined dense").classes("w-72")
                lm.on_value_change(lambda e: (setattr(settings, "local_image_model", e.value),
                                              settings.save(),
                                              ui.notify(f"Modelo local: {e.value}",
                                                        type="positive")))
            elif st.get("provider") == "sdwebui":
                sdurl = ui.input("URL do SD WebUI", value=settings.sdwebui_url) \
                    .props("outlined dense").classes("w-72")
                sdurl.on("blur", lambda: (setattr(settings, "sdwebui_url",
                                                  sdurl.value or settings.sdwebui_url),
                                          settings.save()))
            refs = p.state["style"].get("char_refs") or []
            if refs:
                use_refs = ui.switch("Usar referências de personagem",
                                     value=st.get("use_refs", True)).props("color=negative")
                use_refs.on_value_change(lambda e: (st.update({"use_refs": e.value}), p.save()))
            ui.element("div").classes("grow")
            missing = [i for i in range(len(prompts)) if i >= len(files) or not files[i]]
            if missing and done_count:
                busy_guard(theme.ghost_btn(
                    f"Gerar {len(missing)} faltantes",
                    lambda: gen(missing, "Imagens faltantes")))
            busy_guard(theme.ghost_btn("Whisk (navegador)", browser_whisk_dialog,
                                       icon="public"))
            busy_guard(theme.primary_btn(
                "Gerar todas", lambda: gen(None, "Imagens do roteiro"), icon="image"))
        with ui.row().classes("w-full items-center gap-2"):
            ui.label("Geração sequencial (1 por vez).").classes("mut2 text-xs")
            if st.get("provider") != "pollinations":
                ui.button("Sem créditos? Trocar para grátis (Pollinations)",
                          on_click=lambda: (st.update({"provider": "pollinations"}),
                                            p.save(), refresh_all(),
                                            ui.notify("Provedor: Pollinations (grátis)",
                                                      type="positive"))) \
                    .props("flat dense no-caps size=sm").classes("ibtn")
        if st.get("provider") == "gemini" and not settings.gemini_ready:
            theme.pill("Gemini sem chave/créditos — use Pollinations, HF ou Together (grátis)",
                       "warn")
        if st.get("provider") == "higgsfield" and not settings.higgsfield_api_key:
            theme.pill("configure a HIGGSFIELD_API_KEY nas Configurações", "warn")
        if st.get("provider") == "local":
            dev = tts.device_label()
            gpu = dev.startswith("GPU")
            theme.pill(("⚡ " if gpu else "🐢 CPU — ") + (dev if gpu else "sem GPU, muito lento"),
                       "ok" if gpu else "warn")
            n = len(prompts)
            mdl = settings.local_image_model
            secs = {"sd15": 12, "sdxl": 55, "zimage": 25, "flux-schnell": 180}.get(mdl, 55)
            ui.label(f"{n} cenas × ~{secs}s ≈ ~{int(n * secs / 60)} min na sua GPU. "
                     f"SDXL e SD 1.5 já testados e prontos; Z-Image/FLUX baixam na 1ª vez.") \
                .classes("mut2 text-xs")
        if st.get("provider") == "sdwebui":
            theme.pill("requer o AUTOMATIC1111/Forge aberto com --api (porta 7860)", "warn")

    _image_grid_view()


def preview_image(src: str):
    with ui.dialog() as dlg, ui.card().classes("p-1").style("background:#000;max-width:94vw"):
        ui.image(src).style("max-width:90vw;max-height:84vh;object-fit:contain")
    dlg.open()


def image_detail(idx: int):
    """Modal da cena: imagem ampliada + frase + prompt (editável) + regenerar + baixar."""
    p = state.project
    st = p.state["images"]
    files = st.get("files") or []
    prompts = p.state["style"].get("prompts") or []
    rel = files[idx] if idx < len(files) else None
    if not (rel and (p.dir / rel).exists()):
        ui.notify("Esta cena ainda não tem imagem gerada", type="warning")
        return
    frase = p.sentences[idx] if idx < len(p.sentences) else ""

    with ui.dialog() as dlg, ui.card().classes("card gap-3") \
            .style("width:920px;max-width:96vw;max-height:94vh;overflow-y:auto"):
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label(f"Cena {idx + 1:02d}").classes("h-title").style("font-size:18px")
            theme.icon_btn("close", dlg.close)
        src = media_url(rel)
        ui.image(src).style("width:100%;max-height:60vh;object-fit:contain;"
                            "border-radius:10px;background:#000") \
            .on("click", lambda: preview_image(src))
        if frase:
            ui.label(f"“{frase}”").classes("mut text-sm")
        ui.label("Prompt desta cena (edite e regenere para ajustar)").classes("card-h")
        prompt_ta = ui.textarea(value=prompts[idx] if idx < len(prompts) else "") \
            .props("outlined dense autogrow").classes("w-full")

        async def regen(more_detail=False):
            new_prompt = (prompt_ta.value or "").strip()
            if more_detail:
                new_prompt += (" Highly detailed, intricate details, sharp focus, "
                               "ultra-detailed textures, 4k, masterpiece quality.")
            if idx < len(prompts):
                p.state["style"]["prompts"][idx] = new_prompt
                p.save()
            dlg.close()
            await run_stage(pipeline.run_images, [idx],
                            success=f"Cena {idx + 1} regenerada")

        with ui.row().classes("w-full justify-end gap-2 pt-1"):
            theme.ghost_btn("Abrir pasta", lambda: open_folder((p.dir / rel).parent),
                            icon="folder_open")
            theme.ghost_btn("Regenerar com mais detalhes",
                            lambda: regen(more_detail=True), icon="auto_awesome")
            busy_guard(theme.primary_btn("Regenerar esta cena",
                                         lambda: regen(False), icon="refresh"))
    dlg.open()


def panel_animation():
    p = state.project
    st = p.state["animation"]

    with theme.card("Movimento das cenas"):
        sw = ui.switch("Animar as imagens", value=st.get("enabled", False)) \
            .props("color=negative")
        sw.on_value_change(lambda e: (st.update({"enabled": e.value, "done": False}),
                                      p.save(), refresh_all()))
        if st.get("enabled"):
            from core.animate import ANIM_PROVIDERS
            anim_labels = dict(ANIM_PROVIDERS)
            cur_prov = st.get("provider", "kenburns")
            if cur_prov not in anim_labels:
                cur_prov = "kenburns"
            provider = ui.radio(anim_labels, value=cur_prov).props("color=negative")
            provider.on_value_change(lambda e: (st.update({"provider": e.value, "done": False}),
                                                p.save(), refresh_all()))
            if st.get("provider") == "veo":
                theme.pill("o Veo cobra por vídeo gerado — confira o preço antes de rodar "
                           "roteiros longos", "warn")
            ui.label("A IA analisa cada frase e imagem e escolhe o movimento que reforça a "
                     "narrativa — zoom dramático, pan de revelação, respiro no ambiente.") \
                .classes("mut text-sm")

            if st.get("provider") == "ltx":
                ui.label("LTX-Video local: 100% grátis e offline na sua GPU — "
                         "~2-5 min por clipe na RTX 2060 (1ª vez baixa ~9GB).") \
                    .classes("mut2 text-xs")
            if st.get("provider") == "hf_video":
                if not settings.hf_token:
                    theme.pill("requer HF_TOKEN (grátis) nas Configurações", "warn")
                ui.label("Hugging Face i2v: grátis com token, mas modelos de vídeo são "
                         "grandes — pode ter fila/cold start e limite mensal. Se falhar, "
                         "o LTX local ou Ken Burns são alternativas grátis confiáveis.") \
                    .classes("mut2 text-xs")
            if st.get("provider") == "pollinations_video":
                ui.label("Pollinations vídeo: usa créditos Pollen (tier grátis limitado) — "
                         "experimental. Cai para aviso se indisponível.").classes("mut2 text-xs")

            # quantos clipes já existem (disco = fonte da verdade p/ retomar)
            n_cenas = len(p.timed_sentences)
            feitos = sum(1 for i in range(n_cenas) if p.clip_rel(i))
            gera_clipe = st.get("provider") in ("ltx", "hf_video",
                                                "pollinations_video", "veo", "higgsfield")
            if gera_clipe and feitos:
                theme.pill(f"{feitos}/{n_cenas} cenas já animadas — o resto continua "
                           "de onde parou", "ok")

            async def plan(force_all=False):
                if force_all:   # reanimar tudo → apaga todos os clipes do disco
                    clip_dir = p.dir / "clips"
                    if clip_dir.exists():
                        for f in clip_dir.glob("clip_*.mp4"):
                            f.unlink(missing_ok=True)
                    st["clips"] = []
                    p.save()
                falta = n_cenas - (0 if force_all else feitos)
                if st.get("provider") in ("veo", "higgsfield") and falta > 0:
                    if not await confirm_cost(falta, settings.veo_cost_usd,
                                              "Clipes de vídeo"):
                        return
                await run_stage(pipeline.run_animation, success="Animação planejada")

            def import_clips_dialog():
                with ui.dialog() as d2, ui.card().classes("card gap-3") \
                        .style("width:520px"):
                    ui.label("Importar clipes de uma pasta").classes("card-h")
                    ui.label("Gerou vídeos fora do app (ComfyUI/Wan/LTX)? Aponte a pasta: "
                             "os vídeos (ordenados por nome) entram nas cenas sem clipe, "
                             "em ordem.").classes("mut text-sm")
                    pth = ui.input("Caminho da pasta",
                                   placeholder=r"C:\Users\voce\ComfyUI\output") \
                        .props("outlined dense").classes("w-full")

                    def do_import():
                        folder = Path((pth.value or "").strip('" '))
                        if not folder.is_dir():
                            ui.notify("Pasta não encontrada", type="warning")
                            return
                        vids = sorted([f for f in folder.iterdir()
                                       if f.suffix.lower() in (".mp4", ".webm", ".mov")])
                        files = p.state["images"].get("files") or []
                        clips = p.state["animation"].get("clips") or [None] * len(files)
                        clips = (clips + [None] * len(files))[:len(files)]
                        vi = 0
                        for i in range(len(files)):
                            if not clips[i] and vi < len(vids):
                                out = p.path("clips", f"clip_{i:03d}.mp4")
                                shutil.copy2(vids[vi], out)
                                clips[i] = p.rel(out)
                                vi += 1
                        p.state["animation"]["clips"] = clips
                        if vi:
                            p.state["animation"]["provider"] = "veo"  # usa clipes
                        p.save()
                        d2.close()
                        refresh_all()
                        ui.notify(f"{vi} clipes importados", type="positive")

                    with ui.row().classes("w-full justify-end gap-2"):
                        theme.ghost_btn("Cancelar", d2.close)
                        theme.primary_btn("Importar", do_import, icon="download")
                d2.open()

            with ui.row().classes("w-full justify-end gap-2"):
                busy_guard(theme.ghost_btn("Importar clipes de pasta",
                                           import_clips_dialog, icon="drive_folder_upload"))
                busy_guard(theme.ghost_btn("Flow/Veo 3 (navegador, sua conta)",
                                           browser_flow_dialog, icon="public"))
                if gera_clipe and feitos:
                    busy_guard(theme.ghost_btn("Reanimar tudo",
                                               lambda: plan(force_all=True), icon="restart_alt"))
                    busy_guard(theme.primary_btn(
                        f"Continuar ({n_cenas - feitos} faltantes)",
                        lambda: plan(), icon="movie_filter"))
                else:
                    busy_guard(theme.primary_btn("Planejar animação com IA", plan,
                                                 icon="movie_filter"))
        else:
            ui.label("Desligado: imagens estáticas em tela (estilo clássico de canal dark). "
                     "Dá para ativar quando quiser.").classes("mut text-sm")

            def skip():
                st["done"] = True
                p.save()
                goto("export")

            with ui.row().classes("w-full justify-end"):
                theme.ghost_btn("Seguir sem animação", skip, icon="skip_next")

    # grade de vídeos (só p/ provedores que geram clipes) — logo abaixo do card
    if st.get("enabled") and st.get("provider") in ("ltx", "hf_video",
                                                    "pollinations_video", "veo",
                                                    "higgsfield"):
        _clip_grid_view()

    plans = st.get("plans") or []
    if st.get("enabled") and plans:
        labels = CAMERA_LABELS
        clips = st.get("clips") or []
        with theme.card("Plano de movimento (editável)"):
            with ui.column().classes("w-full gap-0"):
                for plan in plans:
                    i = plan["i"]
                    with ui.element("div").classes("syncrow"):
                        ui.label(f"{i + 1:02d}").classes("tchip")
                        ui.label(p.sentences[i][:70] if i < len(p.sentences) else "") \
                            .classes("text-sm grow")
                        if st.get("provider") == "veo":
                            ok = i < len(clips) and clips[i]
                            theme.pill("clipe ok" if ok else "sem clipe", "ok" if ok else "off")
                        cam = ui.select(labels, value=plan.get("camera", "zoom_in")) \
                            .props("outlined dense options-dense").classes("w-44")

                        def save_cam(e, plan=plan):
                            plan["camera"] = e.value
                            p.save()

                        cam.on_value_change(save_cam)


def _clip_grid_view():
    """Grade de vídeos animados — aparecem/atualizam conforme são gerados."""
    p = state.project
    st = p.state["animation"]
    files = p.state["images"].get("files") or []
    n = len(files)
    if not n:
        return
    clips = st.get("clips") or []
    with theme.card("Vídeos animados — aparecem conforme são gerados"):
        vids = []
        with ui.element("div").classes("img-grid"):
            for i in range(n):
                with ui.element("div").classes("imgcard"):
                    # disco é a fonte da verdade: mostra o clipe se o arquivo existe
                    crel = p.clip_rel(i) or (clips[i] if i < len(clips) else None)
                    has = bool(crel and (p.dir / crel).exists())
                    vid = ui.video(media_url(crel) if has else "").props("controls")
                    if not has:
                        vid.classes("hidden")
                    poster = files[i] if i < len(files) and files[i] else None
                    ph = ui.html('<div class="img-skel">aguardando animação</div>')
                    if has:
                        ph.classes("hidden")
                    elif poster and (p.dir / poster).exists():
                        ui.image(media_url(poster)).props("fit=cover").style("opacity:.3")
                    ui.html(f'<div class="idx">{i + 1:02d}</div>')
                    vids.append((vid, ph))

        def refresh_clips():
            for i, (vid, ph) in enumerate(vids):
                crel = p.clip_rel(i)
                if crel:
                    src = media_url(crel)
                    if vid.source != src:
                        vid.set_source(src)
                        vid.classes(remove="hidden")
                        ph.classes("hidden")

        if job.running and state.step == "animation":
            ui.timer(2.0, refresh_clips)


def panel_export():
    p = state.project
    st = p.state["export"]

    with ui.row().classes("w-full gap-4 no-wrap items-start"):
        # coluna de configurações
        with ui.column().classes("grow gap-4"):
            with theme.card("Legendas"):
                with ui.row().classes("w-full gap-3 no-wrap items-end"):
                    preset_sel = ui.select({k: v["label"] for k, v in KARAOKE_PRESETS.items()},
                                           value=st.get("sub_preset", "classic"),
                                           label="Preset de estilo") \
                        .props("outlined dense").classes("w-52")

                    def apply_p(e):
                        _apply_preset(st, e.value)
                        p.save()
                        content.refresh()

                    preset_sel.on_value_change(apply_p)
                    ui.label("o preset preenche fonte, cores e efeitos — ajuste livre depois") \
                        .classes("mut2 text-xs")
                with ui.row().classes("gap-8"):
                    subs = ui.switch("Queimar legendas", value=st.get("subtitles_on", True)) \
                        .props("color=negative")
                    subs.on_value_change(lambda e: (st.update({"subtitles_on": e.value}),
                                                    p.save(), kprev.refresh()))
                    kar = ui.switch("Efeito karaokê", value=st.get("karaoke", True)) \
                        .props("color=negative")
                    kar.on_value_change(lambda e: (st.update({"karaoke": e.value}),
                                                   p.save(), kprev.refresh()))
                    kmode = ui.select({"kf": "Varredura suave", "k": "Bloco por palavra"},
                                      value=st.get("karaoke_mode", "kf"),
                                      label="Modo do karaokê") \
                        .props("outlined dense").classes("w-44")
                    kmode.on_value_change(lambda e: (st.update({"karaoke_mode": e.value}),
                                                     p.save()))
                    upc = ui.switch("MAIÚSCULAS", value=st.get("sub_uppercase", False)) \
                        .props("color=negative")
                    upc.on_value_change(lambda e: (st.update({"sub_uppercase": e.value}),
                                                   p.save(), kprev.refresh()))
                    grw = ui.switch("Pop de entrada", value=st.get("sub_grow", False)) \
                        .props("color=negative")
                    grw.on_value_change(lambda e: (st.update({"sub_grow": e.value}), p.save()))
                with ui.row().classes("w-full gap-3 items-center no-wrap"):
                    font = ui.select(["Arial", "Arial Black", "Impact", "Verdana",
                                      "Segoe UI", "Trebuchet MS"],
                                     value=st.get("sub_font", "Arial"), label="Fonte") \
                        .props("outlined dense").classes("grow")
                    font.on_value_change(lambda e: (st.update({"sub_font": e.value}),
                                                    p.save(), kprev.refresh()))
                    size = ui.number("Tamanho", value=st.get("sub_size", 64), min=36, max=110) \
                        .props("outlined dense").classes("w-28")
                    size.on_value_change(lambda e: (st.update({"sub_size": int(e.value or 64)}),
                                                    p.save(), kprev.refresh()))
                    pos = ui.select({"bottom": "Embaixo", "center": "Centro", "top": "Topo"},
                                    value=st.get("sub_position", "bottom"), label="Posição") \
                        .props("outlined dense").classes("w-36")
                    pos.on_value_change(lambda e: (st.update({"sub_position": e.value}), p.save()))
                with ui.row().classes("w-full gap-3 no-wrap"):
                    c1 = ui.color_input("Cor base", value=st.get("sub_color", "#FFFFFF")) \
                        .props("dense outlined").classes("grow")
                    c1.on_value_change(lambda e: (st.update({"sub_color": e.value}),
                                                  p.save(), kprev.refresh()))
                    c2 = ui.color_input("Cor do destaque", value=st.get("sub_highlight", "#FFD400")) \
                        .props("dense outlined").classes("grow")
                    c2.on_value_change(lambda e: (st.update({"sub_highlight": e.value}),
                                                  p.save(), kprev.refresh()))
                kprev()

            with theme.card("Montagem"):
                with ui.row().classes("w-full gap-4 items-center no-wrap"):
                    tr = ui.select(TRANSITIONS, value=st.get("transition", "fade")
                                   if st.get("transition") in TRANSITIONS else "fade",
                                   label="Transição entre cenas") \
                        .props("outlined dense").classes("w-56")
                    tr.on_value_change(lambda e: (st.update({"transition": e.value}), p.save()))
                    ui.label("duração").classes("mut2 text-xs")
                    td = ui.slider(min=0.2, max=0.8, step=0.05,
                                   value=st.get("transition_dur", 0.4)) \
                        .props("color=negative label").classes("w-32")
                    td.on_value_change(lambda e: (st.update({"transition_dur": e.value}),
                                                  p.save()))
                    flt = ui.select({k: v[0] for k, v in FILTERS.items()},
                                    value=st.get("filter", "none")
                                    if st.get("filter") in FILTERS else "none",
                                    label="Filtro de cor") \
                        .props("outlined dense").classes("w-52")
                    flt.on_value_change(lambda e: (st.update({"filter": e.value}), p.save()))
                ui.label("15 transições (inclui 🎲 aleatória por corte) · 12 filtros de cor "
                         "aplicados antes das legendas · render incremental reaproveita "
                         "cenas sem mudanças.").classes("mut2 text-xs")

            with theme.card("Trilha sonora de fundo (opcional)"):
                has_bgm = st.get("bgm") and (p.dir / st["bgm"]).exists()
                with ui.row().classes("w-full items-center gap-4 no-wrap"):
                    if has_bgm:
                        ui.icon("music_note").style("color:var(--acc)")
                        ui.label(Path(st["bgm"]).name).classes("text-sm mut")
                        theme.icon_btn("delete", lambda: (st.update({"bgm": None}), p.save(),
                                                          refresh_all()), "Remover trilha")
                    else:
                        def on_upload(e):
                            dest = p.path("assets", f"bgm{Path(e.name).suffix or '.mp3'}")
                            dest.write_bytes(e.content.read())
                            st["bgm"] = p.rel(dest)
                            p.save()
                            refresh_all()

                        ui.upload(on_upload=on_upload, auto_upload=True, max_files=1) \
                            .props('accept=".mp3,.wav,.m4a,.ogg" flat dense color=dark '
                                   'label="Enviar áudio"').classes("w-60")
                    ui.element("div").classes("grow")
                    ui.label("volume").classes("mut2 text-xs")
                    vol = ui.slider(min=0.05, max=0.5, step=0.01,
                                    value=st.get("bgm_volume", 0.18)) \
                        .props("color=negative").classes("w-36")
                    vol.on_value_change(lambda e: (st.update({"bgm_volume": e.value}), p.save()))
                ui.label("A música abaixa sozinha quando a narração fala (ducking automático).") \
                    .classes("mut2 text-xs")
                mood = (p.state["style"].get("analysis") or {}).get("mood") or ""
                if mood and not has_bgm:
                    ui.label(f"Clima detectado: “{mood[:100]}” — trilha sugerida: "
                             f"{_bgm_suggestion(mood)}.").classes("mut2 text-xs") \
                        .style("color:var(--warn)")

        # resumo do render
        with ui.column().classes("gap-4").style("width:300px;flex-shrink:0"):
            with theme.card("Resumo do render"):
                timed = p.timed_sentences
                dur = timed[-1]["end"] if timed else 0
                anim = p.state["animation"]
                anim_txt = ("Veo 3.1" if anim.get("provider") == "veo" else "Ken Burns") \
                    if anim.get("enabled") else "estático"
                fmt = p.state.get("format", "16:9")
                fw, fh = FORMATS.get(fmt, FORMATS["16:9"])
                for k, v in [
                    ("Cenas", str(len(timed))),
                    ("Duração", f"{int(dur // 60)}:{int(dur % 60):02d}"),
                    ("Formato", f"{fmt} · {fw}×{fh}"),
                    ("Codec", "H.264 + AAC · 30fps"),
                    ("Animação", anim_txt),
                    ("Transição", {"none": "corte seco", "fade": "crossfade",
                                   "fadeblack": "fade preto"}.get(st.get("transition"), "corte")),
                    ("Legendas", ("karaokê" if st.get("karaoke") else "simples")
                        if st.get("subtitles_on", True) else "desligadas"),
                ]:
                    with ui.row().classes("w-full justify-between no-wrap"):
                        ui.label(k).classes("mut2 text-xs")
                        ui.label(v).classes("text-xs font-medium mono")
            busy_guard(theme.primary_btn("Renderizar vídeo", lambda: run_stage(
                pipeline.run_export, success="Vídeo renderizado"), icon="rocket_launch")) \
                .classes("w-full").style("height:44px")

    if st.get("file") and (p.dir / st["file"]).exists() and st["done"]:
        final = p.dir / st["file"]
        with theme.card("Vídeo pronto para publicar"):
            ui.video(media_url(st["file"])).classes("w-full").style("border-radius:10px")
            with ui.row().classes("w-full items-center gap-4 no-wrap"):
                theme.pill("render concluído", "ok")
                ui.label(f"{final.name} · {final.stat().st_size / 1e6:.1f} MB") \
                    .classes("mut text-sm mono grow")
                theme.ghost_btn("Abrir pasta", lambda: open_folder(final.parent),
                                icon="folder_open")
            ui.label("legenda.srt incluída na pasta — suba como CC no YouTube.") \
                .classes("mut2 text-xs")

    # ------------------------------------------------- kit de publicação
    pub = p.state.get("publish") or {}
    kit = pub.get("kit") or {}
    with theme.card("Kit de publicação — títulos · descrição · tags · thumbnails"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("A IA gera 5 títulos de alto CTR, descrição com hashtags, tags e "
                     "3 thumbnails com texto de impacto.").classes("mut text-sm grow")
            busy_guard(theme.primary_btn("Gerar kit", lambda: run_stage(
                pipeline.run_publish_kit, success="Kit de publicação pronto"),
                icon="auto_awesome"))
        if not settings.gemini_api_key:
            theme.pill("requer GEMINI_API_KEY", "warn")
        if kit.get("titles"):
            ui.label("Títulos (clique para copiar)").classes("card-h mt-2")
            for t in kit["titles"][:5]:
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    theme.icon_btn("content_copy", lambda t=t: (
                        ui.clipboard.write(t), ui.notify("Título copiado")), "Copiar")
                    ui.label(t).classes("text-sm")
            with ui.row().classes("w-full gap-4 no-wrap items-start mt-2"):
                with ui.column().classes("grow gap-1"):
                    ui.label("Descrição").classes("card-h")
                    desc_ta = ui.textarea(value=kit.get("description", "")) \
                        .classes("w-full").props("outlined autogrow dense readonly")
                    theme.ghost_btn("Copiar descrição", lambda: (
                        ui.clipboard.write(kit.get("description", "")),
                        ui.notify("Descrição copiada")), icon="content_copy")
                with ui.column().classes("grow gap-1"):
                    ui.label("Tags").classes("card-h")
                    tags_txt = ", ".join(kit.get("tags", []))
                    ui.label(tags_txt).classes("mut text-xs")
                    theme.ghost_btn("Copiar tags", lambda: (
                        ui.clipboard.write(tags_txt), ui.notify("Tags copiadas")),
                        icon="content_copy")
        thumbs = [t for t in (pub.get("thumbs") or []) if (p.dir / t).exists()]
        if thumbs:
            ui.label("Thumbnails").classes("card-h mt-2")
            with ui.row().classes("gap-3"):
                for t in thumbs:
                    src = media_url(t)
                    img = ui.image(src).style("width:200px;border-radius:10px;cursor:zoom-in")
                    img.on("click", lambda src=src: preview_image(src))

    # ---------------------------------------------------------- YouTube
    with theme.card("Publicar no YouTube"):
        if not youtube.available():
            ui.label("Para ativar o upload direto: crie no Google Cloud um OAuth "
                     "\"App para computador\" com a YouTube Data API v3 ativada e salve o "
                     "client_secret.json na pasta do DarkStudio (passo a passo no README).") \
                .classes("mut text-sm")
            theme.pill("client_secret.json não encontrado", "warn")
        else:
            titles = kit.get("titles") or []
            yt_title = ui.input("Título", value=titles[0] if titles else p.state["name"]) \
                .props("outlined dense maxlength=100").classes("w-full")
            yt_desc = ui.textarea("Descrição", value=kit.get("description", "")) \
                .props("outlined autogrow dense").classes("w-full")
            with ui.row().classes("w-full gap-3 no-wrap items-end"):
                yt_priv = ui.select({"public": "Público", "unlisted": "Não listado",
                                     "private": "Privado"}, value="private",
                                    label="Visibilidade").props("outlined dense").classes("w-40")
                yt_sched = ui.input("Agendar publicação (opcional)") \
                    .props("outlined dense type=datetime-local").classes("w-60")
                thumb_opts = {"": "sem thumbnail"}
                thumb_opts.update({t: f"thumbnail {i + 1}" for i, t in enumerate(thumbs)})
                yt_thumb = ui.select(thumb_opts, value=thumbs[0] if thumbs else "",
                                     label="Thumbnail").props("outlined dense").classes("w-44")
                ui.element("div").classes("grow")
                up_btn = theme.primary_btn("Enviar vídeo", None, icon="upload")
            yt_result = ui.label().classes("text-sm mono").style("color:var(--ok)")

            async def do_upload():
                final = p.dir / (st.get("file") or "")
                if not st.get("file") or not final.exists():
                    ui.notify("Renderize o vídeo antes de enviar", type="warning")
                    return
                publish_at = None
                if (yt_sched.value or "").strip():
                    try:
                        publish_at = datetime.fromisoformat(yt_sched.value).astimezone()
                    except ValueError:
                        ui.notify("Data de agendamento inválida", type="warning")
                        return
                up_btn.props("loading")
                try:
                    tags_list = [t.strip() for t in (kit.get("tags") or [])][:30]
                    thumb = (p.dir / yt_thumb.value) if yt_thumb.value else None
                    url = await run.io_bound(
                        youtube.upload_video, final, yt_title.value or p.state["name"],
                        yt_desc.value or "", tags_list, yt_priv.value, publish_at, thumb)
                    yt_result.set_text(f"Publicado: {url}"
                                       + (" (agendado)" if publish_at else ""))
                    ui.notify("Upload concluído!", type="positive", timeout=10000)
                except Exception as e:
                    ui.notify(f"Erro no upload: {e}", type="negative",
                              multi_line=True, timeout=12000)
                finally:
                    up_btn.props(remove="loading")

            up_btn.on_click(do_upload)
            ui.label("Agendamento usa visibilidade privada até a data (regra do YouTube). "
                     "Na primeira vez o navegador abre para autorizar sua conta.") \
                .classes("mut2 text-xs")


@ui.refreshable
def kprev():
    """Preview ao vivo do estilo de legenda/karaokê."""
    p = state.project
    st = p.state["export"]
    if not st.get("subtitles_on", True):
        with ui.element("div").classes("kprev"):
            ui.label("legendas desligadas").classes("mut2 text-xs self-center mx-auto")
        return
    base, hi = st.get("sub_color", "#FFFFFF"), st.get("sub_highlight", "#FFD400")
    fsize = int(st.get("sub_size", 64)) * 0.42
    font = st.get("sub_font", "Arial")
    words = "esta é a história que tentaram esconder".split()
    if st.get("sub_uppercase"):
        words = [w.upper() for w in words]
    cut = 3 if st.get("karaoke", True) else 0
    spans = "".join(
        f'<span style="color:{hi if i < cut else base}">{w} </span>'
        for i, w in enumerate(words))
    with ui.element("div").classes("kprev"):
        ui.html(f'<div class="line" style="font-family:\'{font}\',sans-serif;'
                f'font-size:{fsize:.0f}px">{spans}</div>')


PANELS = {
    "script": panel_script,
    "tts": panel_tts,
    "transcription": panel_transcription,
    "style": panel_style,
    "images": panel_images,
    "animation": panel_animation,
    "export": panel_export,
}


@ui.refreshable
def content():
    with ui.column().classes("w-full items-center"):
        with ui.column().classes("w-full gap-4 px-10 py-7").style("max-width:1120px"):
            if state.project is None:
                job_panel()
                panel_welcome()
                return
            info = next(s for s in STEPS if s[0] == state.step)
            idx = STEP_IDS.index(state.step) + 1

            def trailing():
                with ui.row().classes("items-center gap-3 no-wrap"):
                    auto = ui.switch("Automático", value=bool(
                        app.storage.general.get("autopilot"))).props("color=negative dense")
                    with auto:
                        ui.tooltip("Ao terminar cada etapa, avança e executa a próxima "
                                   "sozinho, até o vídeo final")
                    auto.on_value_change(lambda e: _toggle_autopilot(e.value))
                    theme.pill(f"etapa {idx} de {len(STEPS)}", "off")

            theme.page_header(info[1], info[3], trailing)
            job_panel()
            PANELS[state.step]()
            wizard_footer()


@ui.page("/")
def index():
    theme.apply()
    last = app.storage.general.get("last_project")
    if last and state.project is None:
        state.project = Project.load(last)
    header_bar()
    with ui.left_drawer(value=True, fixed=True).props('width=268 :breakpoint="0"').classes("side"):
        sidebar()
    content()


if __name__ in {"__main__", "__mp_main__"}:
    import multiprocessing

    multiprocessing.freeze_support()  # necessário para o executável (PyInstaller)
    web_mode = "--web" in sys.argv

    if not web_mode:
        try:
            app.native.window_args["min_size"] = (1220, 760)
        except Exception:
            pass

    ui.run(
        title="DarkStudio",
        dark=True,
        reload=False,
        show=False,
        favicon="🌑",
        native=not web_mode,
        window_size=None if web_mode else (1480, 930),
        port=8420 if web_mode else 8471,
    )
