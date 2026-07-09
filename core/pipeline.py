"""Orquestração das etapas do pipeline.

Cada função roda de forma síncrona (thread worker da UI ou CLI), atualiza o
project.json e reporta progresso via callback(stage, atual, total, msg).
CANCEL é um Event global: a UI liga para interromper tarefas com segurança.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import animate, editor, imagen, transcribe, tts
from .config import FORMATS, Settings
from .llm import LLM
from .project import Project
from .styles import build_image_prompt, get_style

CANCEL = threading.Event()


class Cancelled(RuntimeError):
    pass


def _check_cancel():
    if CANCEL.is_set():
        raise Cancelled("Cancelado pelo usuário")


def _noop(stage: str, i: int, n: int, msg: str = "") -> None:
    pass


def _dims(project: Project) -> tuple[int, int]:
    return FORMATS.get(project.state.get("format", "16:9"), FORMATS["16:9"])


def _aspect(project: Project) -> str:
    return project.state.get("format", "16:9")


# ------------------------------------------------------------------ 2. TTS
def run_tts(project: Project, settings: Settings, progress=_noop) -> Path:
    st = project.state["tts"]
    sentences = project.sentences
    if not sentences:
        raise RuntimeError("Escreva o roteiro antes de gerar a narração.")
    progress("tts", 0, len(sentences), "Preparando narração…")

    def pcb(done: int, total: int):
        _check_cancel()      # torna o Cancelar responsivo (checa entre blocos)
        progress("tts", done, total, f"Narrando… {done}/{total} blocos de frases")

    audio = tts.synthesize_narration(
        sentences, st["engine"], st["voice"], int(st.get("rate", 0)),
        project.path("audio"), project.state["script"]["language"],
        style=st.get("style", ""), progress=pcb, cancel=CANCEL.is_set)
    st["audio"] = project.rel(audio)
    st["duration"] = editor.probe_duration(audio, settings)
    st["done"] = True
    # Nova narração: a SINCRONIA (tempos) e o VÍDEO FINAL precisam refazer.
    # Estilo, prompts, IMAGENS e planos de animação NÃO dependem da voz — preservados.
    project.state["transcription"].update({"sentences": [], "done": False})
    project.state["export"].update({"file": None, "done": False})
    project.save()
    progress("tts", 1, 1, "Narração pronta")
    return audio


# -------------------------------------------------------- 3. transcrição
def run_transcription(project: Project, settings: Settings, progress=_noop) -> list[dict]:
    st = project.state["transcription"]
    audio_rel = project.state["tts"].get("audio")
    if not audio_rel:
        raise RuntimeError("Gere a narração antes de sincronizar.")
    audio = project.dir / audio_rel
    progress("transcription", 0, 100, "Carregando Whisper…")

    def wp(done: float, total: float):
        _check_cancel()
        progress("transcription", int(done / max(total, 0.1) * 100), 100, "Transcrevendo…")

    sentences = transcribe.transcribe_and_align(
        audio, project.sentences, st.get("model", settings.whisper_model),
        settings.whisper_compute, project.state["script"]["language"], progress=wp)
    st["sentences"] = sentences
    st["done"] = True
    # novos tempos → só o vídeo final refaz; imagens e planos de animação ficam
    project.state["export"].update({"file": None, "done": False})
    project.save()
    progress("transcription", 100, 100, f"{len(sentences)} frases sincronizadas")
    return sentences


# ------------------------------------------------------ 4. estilo/prompts
def run_style_prompts(project: Project, settings: Settings, progress=_noop) -> list[str]:
    llm = LLM(settings)
    style = get_style(project.state)
    st = project.state["style"]
    sentences = project.sentences
    if not sentences:
        raise RuntimeError("Roteiro vazio.")

    progress("style", 0, len(sentences), "Analisando roteiro (personagens/cenário)…")
    analysis = llm.analyze_script(project.state["script"]["text"],
                                  project.state["script"]["language"])
    st["analysis"] = analysis

    def pp(i: int, n: int):
        _check_cancel()
        progress("style", i, n, f"Criando prompts de cena… {i}/{n}")

    scenes = llm.scene_prompts(analysis, sentences, style,
                               project.state["script"]["language"], progress=pp)
    st["prompts"] = [build_image_prompt(style, s) for s in scenes]
    st["scenes"] = scenes
    st["done"] = True
    # prompts novos (novo estilo) ⇒ APAGA imagens/clipes antigos do disco também,
    # senão sobra imagem do estilo anterior misturada
    project.clear_images()
    project.state["style"]["char_refs"] = []   # refs de personagem seguem o estilo
    project.invalidate_after("style")
    project.save()
    progress("style", len(sentences), len(sentences), "Prompts prontos")
    return st["prompts"]


# --------------------------------------- 4b. referências de personagem
def run_char_refs(project: Project, settings: Settings, progress=_noop) -> list[dict]:
    """Gera uma imagem de referência por personagem — consistência visual real."""
    st = project.state["style"]
    analysis = st.get("analysis") or {}
    chars = (analysis.get("characters") or [])[:3]
    if not chars:
        raise RuntimeError("Nenhum personagem detectado — gere os prompts de cena antes.")
    style = get_style(project.state)
    provider = project.state["images"].get("provider", "gemini")
    refs = []
    for i, c in enumerate(chars):
        _check_cancel()
        progress("style", i, len(chars), f"Referência de {c.get('name', f'personagem {i+1}')}…")
        scene = (f"Character reference of {c.get('name')}: {c.get('description')}. "
                 f"Full body, centered, standing, facing the camera, neutral studio "
                 f"background, clear lighting")
        prompt = build_image_prompt(style, scene)
        out = project.path("images", "refs", f"char_{i}.jpg")
        imagen.generate_image(prompt, out, settings, provider,
                              dims=(1024, 1024), aspect="1:1")
        refs.append({"name": c.get("name", f"personagem {i+1}"), "file": project.rel(out)})
        st["char_refs"] = refs
        project.save()
    progress("style", len(chars), len(chars), "Referências prontas")
    return refs


# ----------------------------------------------------------- 5. imagens
def run_images(project: Project, settings: Settings, progress=_noop,
               only: list[int] | None = None, workers: int = 1) -> list[str]:
    st = project.state["images"]
    prompts = project.state["style"].get("prompts") or []
    if not prompts:
        raise RuntimeError("Gere os prompts de cena antes das imagens.")

    files: list = st.get("files") or [None] * len(prompts)
    files = (files + [None] * len(prompts))[:len(prompts)]
    todo = only if only is not None else list(range(len(prompts)))
    dims, aspect = _dims(project), _aspect(project)

    ref_paths: list[Path] = []
    if st.get("use_refs", True):
        for r in (project.state["style"].get("char_refs") or []):
            p = project.dir / r["file"]
            if p.exists():
                ref_paths.append(p)

    lock = threading.Lock()
    done_count = [0]
    errors: list[str] = []
    fatal = threading.Event()

    def gen_one(i: int):
        if CANCEL.is_set() or fatal.is_set():
            return
        out = project.path("images", f"scene_{i:03d}.jpg")
        try:
            imagen.generate_image(prompts[i], out, settings, st.get("provider", "gemini"),
                                  dims=dims, aspect=aspect,
                                  ref_images=ref_paths or None,
                                  cancel=CANCEL.is_set)   # interrompe no meio (local)
            with lock:
                files[i] = project.rel(out)
                st["files"] = files
                project.save()
        except Exception as e:
            if not CANCEL.is_set():     # cancelamento não conta como erro
                with lock:
                    errors.append(f"Cena {i + 1}: {e}")
                if "GEMINI_API_KEY" in str(e):
                    fatal.set()
        finally:
            with lock:
                if not CANCEL.is_set():
                    done_count[0] += 1
                    progress("images", done_count[0], len(todo),
                             f"Imagens: {done_count[0]}/{len(todo)} concluídas")

    progress("images", 0, len(todo), f"Gerando {len(todo)} imagens (sequencial)…")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(gen_one, i) for i in todo]
        for f in as_completed(futures):
            f.result()
            if CANCEL.is_set():         # cancela as pendentes (nem começam)
                for fut in futures:
                    fut.cancel()
                break

    _check_cancel()
    st["done"] = all(f for f in files)
    project.invalidate_after("images")
    project.save()
    progress("images", len(todo), len(todo),
             "Imagens concluídas" if st["done"] else "Concluído com pendências")
    if errors and not any(files):
        raise RuntimeError(errors[0])
    return files


# ---------------------------------------------------------- 6. animação
def run_animation(project: Project, settings: Settings, progress=_noop) -> None:
    st = project.state["animation"]
    if not st.get("enabled"):
        st["done"] = True
        project.save()
        return
    timed = project.timed_sentences
    if not timed:
        raise RuntimeError("Sincronize a narração antes de animar.")
    llm = LLM(settings)
    scenes = project.state["style"].get("scenes") or project.sentences
    files = project.state["images"].get("files") or []

    def pp(i: int, n: int):
        _check_cancel()
        progress("animation", i, n, f"Planejando movimento {i}/{n}…")

    # reusa os planos de movimento já calculados (não re-planeja à toa ao retomar)
    plans = st.get("plans") or []
    if len(plans) != len(timed):
        plans = animate.plan_motions(llm, timed, scenes, files, project.dir,
                                     use_ai=True, progress=pp)
        st["plans"] = plans
        project.save()

    _CLIP_PROVIDERS = {
        "veo": ("Veo", animate.render_veo_clip),
        "higgsfield": ("Higgsfield", animate.render_higgsfield_clip),
        "ltx": ("LTX local", animate.render_ltx_clip),
        "hf_video": ("HuggingFace", animate.render_hf_video_clip),
        "pollinations_video": ("Pollinations", animate.render_pollinations_video_clip),
    }
    if st.get("provider") in _CLIP_PROVIDERS:
        provider = st["provider"]
        pname, render_fn = _CLIP_PROVIDERS[provider]
        clips: list = st.get("clips") or [None] * len(timed)
        clips = (clips + [None] * len(timed))[:len(timed)]
        # o disco é a fonte da verdade: recupera clipes já gerados que
        # sumiram da lista (evita regerar o que já existe)
        for i in range(len(timed)):
            if not clips[i]:
                cr = project.clip_rel(i)
                if cr:
                    clips[i] = cr
        st["clips"] = clips
        project.save()
        for i, plan in enumerate(plans):
            _check_cancel()
            if clips[i]:
                continue
            img_rel = files[i] if i < len(files) else None
            if not img_rel:
                continue
            progress("animation", i, len(plans),
                     f"{pname}: animando cena {i + 1}/{len(plans)}…")
            out = project.path("clips", f"clip_{i:03d}.mp4")
            try:
                if provider == "ltx":
                    dur = max(2.0, min(6.0, timed[i]["end"] - timed[i]["start"]))
                    render_fn(project.dir / img_rel, plan["veo_prompt"], out, settings,
                              seconds=dur)
                else:
                    render_fn(project.dir / img_rel, plan["veo_prompt"], out, settings)
                clips[i] = project.rel(out)
            except Exception as e:
                progress("animation", i, len(plans), f"{pname} falhou na cena {i + 1}: {e}")
            st["clips"] = clips
            project.save()
    st["done"] = True
    project.invalidate_after("animation")
    project.save()
    progress("animation", len(plans), len(plans), "Animação planejada")


# ------------------------------------------------------------ 7. export
def run_export(project: Project, settings: Settings, progress=_noop) -> Path:
    st = project.state["export"]
    timed = project.timed_sentences
    files = project.state["images"].get("files") or []
    if not timed:
        raise RuntimeError("Sincronize a narração antes de exportar.")
    if not any(files):
        raise RuntimeError("Gere as imagens antes de exportar.")
    audio = project.dir / project.state["tts"]["audio"]
    anim = project.state["animation"]
    plans = {p["i"]: p for p in (anim.get("plans") or [])}
    clips = anim.get("clips") or []
    dims = _dims(project)

    transition = st.get("transition", "none")
    trans_dur = float(st.get("transition_dur", 0.4)) if transition != "none" else 0.0

    seg_dir = project.path("export", "segments")
    segments: list[Path] = []
    durations: list[float] = []
    reused = 0
    n = len(timed)
    last_img: str | None = next((f for f in files if f), None)
    for i, sent in enumerate(timed):
        _check_cancel()
        progress("export", i, n + 3, f"Renderizando cena {i + 1}/{n}…")
        dur = max(0.35, sent["end"] - sent["start"])
        tail = trans_dur if (trans_dur and i < n - 1) else 0.0
        clip_rel = clips[i] if i < len(clips) else None
        img_rel = files[i] if i < len(files) and files[i] else last_img
        last_img = img_rel or last_img
        if anim.get("enabled") and clip_rel and (project.dir / clip_rel).exists():
            kind, src = "video", project.dir / clip_rel
        elif anim.get("enabled"):
            kind, src = "kenburns", project.dir / img_rel
        else:
            kind, src = "image", project.dir / img_rel
        seg, cached = editor.render_segment_cached(i, kind, src, dur, seg_dir, settings,
                                                   motion=plans.get(i), dims=dims, tail=tail)
        reused += int(cached)
        segments.append(seg)
        durations.append(dur)

    progress("export", n, n + 3,
             f"Unindo cenas… ({reused} reaproveitadas do cache)" if reused else "Unindo cenas…")
    base_path = project.path("export", "base.mp4")
    if trans_dur:
        trans_list = editor.pick_transitions(transition, len(segments) - 1)
        base = editor.xfade_concat(segments, durations, trans_dur, trans_list,
                                   base_path, settings)
    else:
        base = editor.concat_segments(segments, base_path, settings)

    progress("export", n + 1, n + 3, "Gerando legendas…")
    ass_path = None
    if st.get("subtitles_on", True):
        ass_path = project.path("export", "subs.ass")
        ass_path.write_text(editor.build_ass(timed, st, karaoke=bool(st.get("karaoke")),
                                             dims=dims), encoding="utf-8")
    srt = project.path("export", "legenda.srt")
    srt.write_text(editor.build_srt(timed), encoding="utf-8")

    progress("export", n + 2, n + 3, "Mixando áudio e finalizando…")
    bgm_rel = st.get("bgm")
    bgm = (project.dir / bgm_rel) if bgm_rel and (project.dir / bgm_rel).exists() else None
    color_filter = editor.FILTERS.get(st.get("filter", "none"), ("", ""))[1]
    final = editor.final_mux(base, audio, project.path("export", "final.mp4"), settings,
                             ass_file=ass_path, bgm=bgm,
                             bgm_volume=float(st.get("bgm_volume", 0.18)),
                             color_filter=color_filter)
    st["file"] = project.rel(final)
    st["done"] = True
    project.save()
    progress("export", n + 3, n + 3, "Vídeo pronto!")
    return final


# ----------------------------------------------------- kit de publicação
def run_publish_kit(project: Project, settings: Settings, progress=_noop) -> dict:
    llm = LLM(settings)
    analysis = project.state["style"].get("analysis") or {}
    script = project.state["script"]["text"]
    lang = project.state["script"]["language"]
    pub = project.state.setdefault("publish", {"kit": None, "thumbs": []})

    progress("export", 0, 5, "Gerando títulos, descrição e tags…")
    pub["kit"] = llm.publication_kit(analysis, script, lang)
    project.save()

    style = get_style(project.state)
    concepts = llm.thumbnail_prompts(analysis, style.get("label", ""), n=3)
    provider = project.state["images"].get("provider", "gemini")
    thumbs = []
    for i, c in enumerate(concepts):
        _check_cancel()
        progress("export", i + 1, 5, f"Gerando thumbnail {i + 1}/3…")
        prompt = (f"YouTube thumbnail, {c.get('prompt', '')}. Huge bold impactful text "
                  f"overlay reading \"{c.get('text', '')}\" integrated into the design, "
                  f"extreme contrast, vivid dramatic colors, expressive emotion, "
                  f"click-worthy professional composition, sharp focus.")
        out = project.path("export", "thumbs", f"thumb_{i}.jpg")
        try:
            imagen.generate_image(prompt, out, settings, provider,
                                  dims=(1280, 720), aspect="16:9")
            thumbs.append(project.rel(out))
        except Exception as e:
            progress("export", i + 1, 5, f"Thumbnail {i + 1} falhou: {e}")
    pub["thumbs"] = thumbs
    project.save()
    progress("export", 5, 5, "Kit de publicação pronto")
    return pub


# ------------------------------------------------------- pipeline completo
def run_full(project: Project, settings: Settings, progress=_noop) -> Path:
    """Roda todas as etapas pendentes de uma vez (usado pelo lote)."""
    if not project.stage_done("tts"):
        run_tts(project, settings, progress)
    _check_cancel()
    if not project.stage_done("transcription"):
        run_transcription(project, settings, progress)
    _check_cancel()
    if not project.stage_done("style"):
        run_style_prompts(project, settings, progress)
    _check_cancel()
    # consistência de personagem automática (se ligada e houver personagens)
    if (project.state["images"].get("use_refs")
            and project.state["images"].get("provider") == "gemini"
            and not project.state["style"].get("char_refs")
            and (project.state["style"].get("analysis") or {}).get("characters")):
        try:
            run_char_refs(project, settings, progress)
        except Exception:
            pass  # sem refs ainda funciona (consistência textual)
    _check_cancel()
    if not project.stage_done("images"):
        run_images(project, settings, progress)
    _check_cancel()
    if not project.stage_done("animation"):
        run_animation(project, settings, progress)
    _check_cancel()
    return run_export(project, settings, progress)
