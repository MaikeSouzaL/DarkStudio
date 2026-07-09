"""Testes das peças críticas do DarkStudio (sem dependências de teste).

Rode:  .venv\\Scripts\\python -m tests.test_core
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.editor import (KARAOKE_PRESETS, _ass_color, _fmt_time, build_ass,  # noqa: E402
                         build_srt, segment_hash)
from core.textproc import normalize_token, slugify, split_sentences, tokenize  # noqa: E402
from core.transcribe import align_sentences  # noqa: E402
from core.tts import _chunk_text  # noqa: E402

PASS = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS
    assert cond, f"FALHOU: {name} {detail}"
    PASS += 1
    print(f"  ok  {name}")


def test_split_sentences():
    s = split_sentences("O Dr. João sumiu. Ninguém sabe onde! Será que voltou?")
    check("split básico", len(s) == 3, str(s))
    check("abreviação Dr. não corta", s[0] == "O Dr. João sumiu.", s[0])
    s = split_sentences("Uma frase longa termina aqui. Fim.")
    check("frase curta é fundida na anterior", len(s) == 1, str(s))
    check("texto vazio", split_sentences("   ") == [])


def test_normalize():
    check("normaliza acentos", normalize_token("Ávido,") == "avido")
    check("normaliza caixa/pontuação", normalize_token("NÃO!") == "nao")
    check("slugify", slugify("Vídeo Épico #1!") == "video-epico-1")


def _mk_words(text: str, start: float = 0.0, dur: float = 0.4):
    words, t = [], start
    for w in text.split():
        words.append({"w": w, "s": round(t, 2), "e": round(t + dur, 2)})
        t += dur
    return words


def test_align_perfect():
    sents = ["A cidade sumiu de repente.", "Ninguém sabe explicar o caso."]
    words = _mk_words("A cidade sumiu de repente. Ninguém sabe explicar o caso.")
    out = align_sentences(sents, words, total=4.0)
    check("alinhamento: 2 frases", len(out) == 2)
    check("frase 1 começa em 0", out[0]["start"] == 0.0, str(out[0]))
    check("fronteira monotônica", out[1]["start"] >= out[0]["start"])
    check("fim ≥ início", all(s["end"] > s["start"] for s in out))
    check("palavras têm tempos", all(w["e"] > w["s"] for s in out for w in s["words"]))


def test_align_ruido():
    # whisper errou palavras do meio — âncoras + interpolação seguram o resultado
    sents = ["O navio partiu à meia noite.", "Nunca mais foi visto no oceano."]
    words = _mk_words("O navio partiu XYZ meia noite nunca QQQ foi visto no oceano")
    out = align_sentences(sents, words, total=4.4)
    check("ruído: 2 frases", len(out) == 2)
    check("ruído: monotônico", out[1]["start"] >= out[0]["start"])
    check("ruído: cobre o áudio", out[-1]["end"] >= 4.4)


def test_align_fallback():
    # reconhecimento inútil → distribuição proporcional por tamanho
    sents = ["Primeira frase do roteiro aqui.", "Segunda frase um pouco maior que a outra."]
    words = _mk_words("blá blé bli blo blu")
    out = align_sentences(sents, words, total=10.0)
    check("fallback: 2 frases", len(out) == 2)
    check("fallback: proporcional", out[1]["start"] > 3.0, str(out[1]["start"]))
    check("fallback: termina no áudio", abs(out[-1]["end"] - 10.0) < 0.01)


def test_ass():
    check("cor ASS", _ass_color("#FFD400") == "&H0000D4FF")
    check("tempo ASS", _fmt_time(61.5) == "0:01:01.50")
    timed = [{"i": 0, "text": "Olá mundo cruel", "start": 0.0, "end": 2.0,
              "words": [{"w": "Olá", "s": 0.0, "e": 0.5},
                        {"w": "mundo", "s": 0.5, "e": 1.2},
                        {"w": "cruel", "s": 1.2, "e": 2.0}]}]
    opts = {"sub_font": "Arial", "sub_size": 64, "sub_color": "#FFFFFF",
            "sub_highlight": "#FFD400", "sub_position": "bottom",
            "sub_outline": 3, "sub_shadow": 1, "sub_uppercase": True, "sub_grow": True}
    ass = build_ass(timed, opts, karaoke=True, dims=(1080, 1920))
    check("ASS: PlayRes 9:16", "PlayResX: 1080" in ass and "PlayResY: 1920" in ass)
    check("ASS: tags karaokê", "\\k" in ass)
    check("ASS: maiúsculas", "MUNDO" in ass)
    check("ASS: pop de entrada", "\\fscx86" in ass)
    check("ASS: fonte escala com a altura", "Sub,Arial,114" in ass, ass[:400])
    check("ASS: varredura suave (kf) é o padrão", "\\kf" in ass)
    opts2 = dict(opts, karaoke_mode="k", sub_box=True)
    ass2 = build_ass(timed, opts2, karaoke=True, dims=(1920, 1080))
    check("ASS: modo bloco usa \\k", "\\kf" not in ass2 and "\\k" in ass2)
    check("ASS: preset caixa usa BorderStyle 3", ",3," in ass2.split("Style: Sub,")[1][:80])
    from core.editor import FILTERS, TRANSITIONS, pick_transitions
    check("transições curadas", len(TRANSITIONS) >= 15 and "random" in TRANSITIONS)
    check("random gera lista válida", all(t in TRANSITIONS for t in
                                          pick_transitions("random", 8)))
    check("filtros com cadeia vf", len(FILTERS) >= 12 and FILTERS["noir"][1])
    from core import tts
    check("sample_filename determinístico",
          tts.sample_filename("edge", "pt-BR-AntonioNeural")
          == tts.sample_filename("edge", "pt-BR-AntonioNeural"))
    check("sample_filename separa por estilo",
          tts.sample_filename("gemini", "Charon", "sombrio")
          != tts.sample_filename("gemini", "Charon", ""))
    check("sample_path extensão por engine",
          tts.sample_path(Path("."), "edge", "x").suffix == ".mp3"
          and tts.sample_path(Path("."), "coqui", "y").suffix == ".wav")
    from core.styles import STYLES
    from ui.theme import STYLE_THUMBS
    check("todos os estilos têm thumbnail",
          all(s in STYLE_THUMBS for s in STYLES), str([s for s in STYLES if s not in STYLE_THUMBS]))
    check("25+ estilos visuais", len(STYLES) >= 25, str(len(STYLES)))
    srt = build_srt(timed)
    check("SRT: formato", "00:00:00,000 --> 00:00:02,000" in srt)
    check("presets completos", all(
        {"font", "size", "color", "highlight", "outline", "shadow", "uppercase", "grow"}
        <= set(v) for v in KARAOKE_PRESETS.values()))


def test_chunk_e_hash(tmp: Path):
    chunks = _chunk_text("Primeira frase. Segunda frase maior. Terceira aqui.", 30)
    check("chunk TTS respeita limite", all(len(c) <= 40 for c in chunks) and len(chunks) >= 2,
          str(chunks))
    f = tmp / "img.jpg"
    f.write_bytes(b"x" * 100)
    h1 = segment_hash("image", f, 2.0, None, (1920, 1080), 0.0, 30)
    h2 = segment_hash("image", f, 2.0, None, (1920, 1080), 0.0, 30)
    h3 = segment_hash("image", f, 2.5, None, (1920, 1080), 0.0, 30)
    h4 = segment_hash("image", f, 2.0, None, (1080, 1920), 0.0, 30)
    check("hash determinístico", h1 == h2)
    check("hash muda com duração", h1 != h3)
    check("hash muda com formato", h1 != h4)


def test_script_reset():
    """Roteiro novo NÃO pode herdar imagens/áudio/tempos do vídeo anterior."""
    import shutil
    from core.project import Project

    p = Project.create("teste-reset-interno-xyz")
    try:
        p.set_script("Primeira história completa aqui narrada. Segunda frase dela.", "pt-BR")
        # simula um vídeo anterior totalmente produzido
        p.state["tts"].update({"audio": "audio/narration.mp3", "duration": 10})
        p.state["transcription"]["sentences"] = [{"i": 0}]
        p.state["style"].update({"prompts": ["a", "b"], "scenes": ["a", "b"]})
        p.state["images"]["files"] = ["images/scene_000.jpg", "images/scene_001.jpg"]
        p.state["animation"]["plans"] = [{"i": 0}]
        p.state["export"]["file"] = "export/final.mp4"
        # roteiro NOVO → tudo derivado deve zerar
        p.set_script("Outra história totalmente diferente agora. Nada do antigo serve.",
                     "pt-BR")
        check("reset: imagens zeradas", p.state["images"]["files"] == [])
        check("reset: narração zerada", p.state["tts"]["audio"] is None)
        check("reset: sincronia zerada", p.state["transcription"]["sentences"] == [])
        check("reset: prompts zerados", p.state["style"]["prompts"] == [])
        check("reset: animação zerada", p.state["animation"]["plans"] == [])
        check("reset: export zerado", p.state["export"]["file"] is None)
        # salvar o MESMO roteiro de novo não pode apagar nada
        p.state["images"]["files"] = ["images/scene_000.jpg"]
        p.set_script("Outra história totalmente diferente agora. Nada do antigo serve.",
                     "pt-BR")
        check("idempotente: mesmo texto preserva dados",
              p.state["images"]["files"] == ["images/scene_000.jpg"])
    finally:
        shutil.rmtree(p.dir, ignore_errors=True)


def main():
    import tempfile
    tests = [test_split_sentences, test_normalize, test_align_perfect,
             test_align_ruido, test_align_fallback, test_ass, test_script_reset]
    for t in tests:
        print(f"» {t.__name__}")
        t()
    with tempfile.TemporaryDirectory() as td:
        print("» test_chunk_e_hash")
        test_chunk_e_hash(Path(td))
    print(f"\n{PASS} verificações passaram ✔")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
