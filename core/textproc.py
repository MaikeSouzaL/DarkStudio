"""Processamento de texto: divisão em frases, normalização e slugs."""
from __future__ import annotations

import re
import unicodedata

# Abreviações comuns que não terminam frase (pt/en)
_ABBREV = {
    "sr", "sra", "srta", "dr", "dra", "prof", "profa", "eng", "exmo", "exma",
    "av", "r", "km", "kg", "etc", "obs", "pág", "pag", "tel", "cel",
    "mr", "mrs", "ms", "st", "jr", "inc", "ltd", "vs", "no", "art",
}

_SENT_END = re.compile(r'([.!?…]+["\')\]]?)\s+')


def split_sentences(text: str) -> list[str]:
    """Divide o roteiro em frases completas, respeitando abreviações e números."""
    text = re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()
    if not text:
        return []

    parts: list[str] = []
    start = 0
    for m in _SENT_END.finditer(text):
        end = m.end()
        chunk = text[start:end].strip()
        # não corta depois de abreviação ("Dr. João") nem número decimal ("1. 5" já protegido pelo \s)
        last_word = re.findall(r"[\wÀ-ÿ]+", chunk[-12:].lower())
        if last_word and last_word[-1] in _ABBREV:
            continue
        if len(last_word) == 1 and last_word[-1].isdigit() and len(last_word[-1]) <= 2 and chunk[-1] == ".":
            # provável lista numerada "1." — mantém junto
            continue
        if chunk:
            parts.append(chunk)
        start = end
    tail = text[start:].strip()
    if tail:
        parts.append(tail)

    # junta frases muito curtas (< 3 palavras) à anterior para não gerar cena de 0.5s
    merged: list[str] = []
    for p in parts:
        if merged and len(p.split()) < 3:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    return merged


def normalize_token(word: str) -> str:
    """Normaliza palavra para alinhamento fonético-textual (minúscula, sem acento/pontuação)."""
    w = unicodedata.normalize("NFD", word.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", w)


def tokenize(text: str) -> list[str]:
    """Palavras visíveis (com pontuação anexada), na ordem."""
    return [w for w in text.split() if w.strip()]


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "projeto"
