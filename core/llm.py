"""LLM (Gemini) — engenharia de prompt do pipeline.

Responsável por:
  * analisar o roteiro (personagens, cenário, clima) p/ consistência visual
  * transformar cada frase em uma descrição de cena no estilo escolhido
  * gerar o "super prompt" do estilo personalizado
  * planejar a animação de cada cena (Ken Burns ou prompt p/ Veo)

Sem chave de API tudo continua funcionando com fallbacks determinísticos.
"""
from __future__ import annotations

import json
import re
import time

from .config import Settings

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    # ------------------------------------------------------------- infra
    @property
    def available(self) -> bool:
        return self.settings.gemini_ready or bool(self.settings.deepseek_api_key)

    def _get_client(self):
        if self._client is None:
            from .config import genai_client
            self._client = genai_client(self.settings)
        return self._client

    def _deepseek(self, prompt: str, json_mode: bool) -> str:
        """LLM reserva (OpenAI-compatível) quando o Gemini esgota cota/créditos."""
        import httpx
        body = {"model": self.settings.deepseek_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=180) as client:
            r = client.post("https://api.deepseek.com/chat/completions",
                            headers={"Authorization":
                                     f"Bearer {self.settings.deepseek_api_key}"},
                            json=body)
            if r.status_code != 200:
                raise RuntimeError(f"DeepSeek {r.status_code}: {r.text[:200]}")
            return r.json()["choices"][0]["message"]["content"].strip()

    def _models(self) -> list[str]:
        models = [self.settings.text_model] + list(self.settings.text_model_fallbacks)
        seen, out = set(), []
        for m in models:
            if m and m not in seen:
                seen.add(m)
                out.append(m)
        return out

    def _generate(self, prompt: str, json_mode: bool = True, image_path: str | None = None) -> str:
        # sem Gemini configurado → direto para o DeepSeek (se houver chave)
        if not self.settings.gemini_ready:
            if self.settings.deepseek_api_key and not image_path:
                return self._deepseek(prompt, json_mode)
            raise RuntimeError("Configure a GEMINI_API_KEY (ou DeepSeek) nas Configurações.")
        from google.genai import types
        client = self._get_client()
        contents: list = [prompt]
        if image_path:
            with open(image_path, "rb") as f:
                contents.insert(0, types.Part.from_bytes(data=f.read(), mime_type="image/jpeg"))
        config = types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json" if json_mode else None,
        )
        last_err: Exception | None = None
        for model in self._models():
            for attempt in range(2):
                try:
                    resp = client.models.generate_content(model=model, contents=contents, config=config)
                    text = (resp.text or "").strip()
                    if text:
                        return text
                    raise RuntimeError("resposta vazia")
                except Exception as e:  # modelo inexistente/cota → tenta próximo
                    last_err = e
                    msg = str(e).lower()
                    if "not found" in msg or "404" in msg or "permission" in msg:
                        break  # próximo modelo
                    time.sleep(1.5 * (attempt + 1))
        # Gemini esgotado (cota/créditos/erro) → reserva DeepSeek
        if self.settings.deepseek_api_key and not image_path:
            try:
                return self._deepseek(prompt, json_mode)
            except Exception as e:
                last_err = e
        raise RuntimeError(f"LLM falhou em todos os modelos: {last_err}")

    def _gen_json(self, prompt: str, image_path: str | None = None):
        text = self._generate(prompt, json_mode=True, image_path=image_path)
        text = _JSON_FENCE.sub("", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
            if m:
                return json.loads(m.group(0))
            raise

    # ------------------------------------------------------------- etapas
    def analyze_script(self, script: str, language: str) -> dict:
        """Extrai personagens/cenário/clima para manter consistência entre cenas."""
        if not self.available:
            return {"summary": script[:400], "setting": "", "mood": "", "characters": []}
        prompt = f"""Você é diretor de arte de vídeos narrados para YouTube.
Analise o roteiro abaixo (idioma: {language}) e devolva APENAS JSON com este formato:
{{
  "summary": "resumo da história em 2 frases, em inglês",
  "setting": "descrição visual do cenário/época predominante, em inglês",
  "mood": "clima emocional e paleta de cores sugerida, em inglês",
  "characters": [
    {{"name": "nome ou papel", "description": "descrição visual COMPLETA e específica em inglês (idade, corpo, rosto, cabelo, roupa, cores) para repetir em todas as cenas"}}
  ]
}}
Liste só personagens recorrentes (máx. 4). Se não houver personagens, lista vazia.

ROTEIRO:
{script[:12000]}"""
        try:
            data = self._gen_json(prompt)
            data.setdefault("characters", [])
            return data
        except Exception:
            return {"summary": script[:400], "setting": "", "mood": "", "characters": []}

    def scene_prompts(self, analysis: dict, sentences: list[str], style: dict,
                      language: str, progress=None) -> list[str]:
        """Uma descrição de cena (em inglês) por frase, com continuidade visual."""
        if not self.available:
            # Fallback: usa a própria frase como cena
            return [s for s in sentences]

        chars = "\n".join(f"- {c.get('name')}: {c.get('description')}"
                          for c in analysis.get("characters", [])) or "nenhum"
        out: list[str] = []
        chunk_size = 20
        for start in range(0, len(sentences), chunk_size):
            chunk = sentences[start:start + chunk_size]
            numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(chunk))
            prev_context = out[-1] if out else "primeira cena"
            prompt = f"""Você cria prompts de imagem para um vídeo narrado (idioma da narração: {language}).

CONTEXTO DA HISTÓRIA:
Resumo: {analysis.get('summary', '')}
Cenário: {analysis.get('setting', '')}
Clima: {analysis.get('mood', '')}
Personagens (use SEMPRE estas descrições exatas quando aparecerem):
{chars}

ESTILO VISUAL: {style.get('label', '')} — {style.get('style_hint', '')}
Cena anterior (para continuidade): {prev_context}

Para CADA frase numerada abaixo, escreva UMA descrição de cena EM INGLÊS (1-2 frases, concreta e
visualizável: quem, onde, ação, enquadramento, luz). Repita a descrição física dos personagens
recorrentes em toda cena onde aparecem. Não inclua o estilo (será adicionado depois), não invente
texto escrito na imagem.

FRASES:
{numbered}

Devolva APENAS JSON: {{"scenes": ["cena 1", "cena 2", ...]}} com exatamente {len(chunk)} itens."""
            try:
                data = self._gen_json(prompt)
                scenes = data.get("scenes", [])
            except Exception:
                scenes = []
            while len(scenes) < len(chunk):
                scenes.append(chunk[len(scenes)])
            out.extend(str(s) for s in scenes[:len(chunk)])
            if progress:
                progress(min(start + chunk_size, len(sentences)), len(sentences))
        return out

    def auto_pick(self, idea: str, tone: str, styles: dict, presets: dict) -> dict:
        """Escolhe o estilo visual e o preset de legenda que mais combinam com
        a história (usado quando a seção está em modo automático)."""
        if not self.available:
            return {}
        prompt = f"""Para um vídeo dark de YouTube sobre "{idea}" (tom: {tone}), escolha o
que MAIS combina:
- estilo visual, entre estas chaves: {list(styles)}
- preset de legenda, entre estas chaves: {list(presets)}
Devolva APENAS JSON {{"style": "chave", "preset": "chave"}} usando exatamente as chaves."""
        try:
            return self._gen_json(prompt)
        except Exception:
            return {}

    def custom_style(self, user_description: str) -> dict:
        """Gera o super prompt do estilo personalizado descrito pelo usuário."""
        if not self.available:
            return {
                "name": "Personalizado",
                "template": user_description.strip().rstrip(".") + ". Scene: {scene}",
                "style_hint": user_description.strip(),
            }
        prompt = f"""O usuário quer um estilo visual personalizado para as imagens de um vídeo narrado.

DESCRIÇÃO DO USUÁRIO:
"{user_description}"

Crie um super prompt de estilo reutilizável. Devolva APENAS JSON:
{{
  "name": "nome curto do estilo em português",
  "template": "prompt EM INGLÊS rico e específico (técnica, materiais, paleta, iluminação, "
              "composição, referências artísticas) que termina com 'Scene: {{scene}}'",
  "style_hint": "instruções em português de como descrever cenas nesse estilo"
}}
O template DEVE conter o placeholder {{scene}} exatamente uma vez."""
        try:
            data = self._gen_json(prompt)
            if "{scene}" not in data.get("template", ""):
                data["template"] = data.get("template", "").rstrip(". ") + ". Scene: {scene}"
            return data
        except Exception:
            return {
                "name": "Personalizado",
                "template": user_description.strip().rstrip(".") + ". Scene: {scene}",
                "style_hint": user_description.strip(),
            }

    # ------------------------------------------------------ fábrica de conteúdo
    def generate_script(self, idea: str, minutes: float, tone: str, language: str,
                        niche: str = "", progress=None) -> str:
        """Ideia → roteiro completo pronto para narrar."""
        if not self.available:
            raise RuntimeError("O gerador de roteiro precisa da GEMINI_API_KEY.")
        # taxa real de fala de narração TTS (palavras/min), calibrada por medição:
        # vozes variam ~150-190; usamos um valor alto para NÃO gerar curto demais,
        # já que é melhor sobrar do que faltar tempo.
        wpm = {"pt-BR": 175, "es-ES": 175}.get(language, 165)
        target = int(minutes * wpm)
        lo, hi = int(target * 0.95), int(target * 1.15)
        niche_line = f"- Nicho do canal: {niche} (respeite os códigos e o público desse nicho)\n" \
            if niche else ""
        prompt = f"""Você é roteirista profissional de canais dark de YouTube (vídeos narrados).
Escreva um roteiro em {language} sobre: "{idea}"

REGRAS:
{niche_line}- Tom: {tone}
- COMPRIMENTO CRÍTICO: o roteiro é narrado e precisa durar ~{minutes:g} minutos falados.
  Escreva ENTRE {lo} E {hi} PALAVRAS. Ficar abaixo de {lo} é ERRO GRAVE — conte e cumpra.
  Para atingir o tamanho, desenvolva a história com mais detalhes, contexto, tensão e
  reviravoltas (NUNCA com enrolação ou repetição).
- HOOK devastador nas 2 primeiras frases (retenção dos 5 primeiros segundos)
- Frases curtas e visuais (8-20 palavras) — cada frase vira UMA cena ilustrada
- Crie tensão crescente, mini-cliffhangers a cada ~5 frases, final que fecha a história
- Texto corrido de narração: SEM títulos, marcações, emojis ou instruções de câmera
- Não invente fatos verificáveis falsos sobre pessoas reais

Devolva APENAS JSON: {{"script": "texto completo do roteiro"}}"""
        # Roteiro longo (>~550 palavras) o modelo tende a RESUMIR se gerado de uma
        # vez. Então geramos por PARTES a partir de um esqueleto — garante o tempo.
        if target > 550:
            return self._script_in_parts(idea, tone, language, niche_line, target,
                                         lo, hi, minutes, progress)

        data = self._gen_json(prompt)
        script = str(data.get("script", "")).strip()
        if len(script) < 100:
            raise RuntimeError("Roteiro gerado veio vazio/curto — tente novamente")

        # LLMs não acertam a contagem — se veio curto, mandamos EXPANDIR até 2x
        for _ in range(2):
            wc = len(script.split())
            if wc >= lo:
                break
            expand = f"""O roteiro abaixo tem {wc} palavras, mas precisa ter ENTRE {lo} e
{hi} para durar ~{minutes:g} min narrado. EXPANDA a MESMA história (mesmo tom {tone},
mesmas frases curtas de narração), adicionando mais detalhes, contexto sensorial, tensão
e desenvolvimento — sem repetir nem enrolar, sem mudar o final. Devolva APENAS JSON
{{"script": "roteiro expandido completo"}}.

ROTEIRO ATUAL:
{script}"""
            try:
                script = str(self._gen_json(expand).get("script", script)).strip() or script
            except Exception:
                break
        return script

    def _script_in_parts(self, idea, tone, language, niche_line, target, lo, hi,
                         minutes, progress=None) -> str:
        """Roteiro longo por partes: esqueleto → cada parte com alvo de palavras.
        Partes menores (~260 palavras) são muito mais confiáveis de atingir."""
        n_parts = max(3, round(target / 260))
        per_part = round(target / n_parts)
        data = self._gen_json(f"""Você é roteirista de canais dark. Crie o ESQUELETO de um
vídeo narrado de ~{minutes:g} min sobre "{idea}".
{niche_line}Tom: {tone}. Divida a história em EXATAMENTE {n_parts} partes sequenciais que,
juntas, formam um arco completo (hook forte no início, tensão crescente, final que fecha).
Cada parte deve ter um foco DIFERENTE que avança a história (nada de repetir).
Devolva APENAS JSON {{"partes": [{{"foco": "o que acontece nesta parte (1-2 frases)"}}]}}
com {n_parts} itens.""")
        partes = data.get("partes") or [{"foco": idea}] * n_parts

        blocks: list[str] = []
        for i, parte in enumerate(partes):
            if progress:
                progress(f"Escrevendo parte {i + 1}/{len(partes)}…")
            prev = (" Continue diretamente de onde a parte anterior parou, sem repetir."
                    if i else " Abra com um HOOK devastador nas 2 primeiras frases.")
            fim = (" Esta é a ÚLTIMA parte: dê um desfecho que fecha a história."
                   if i == len(partes) - 1 else "")
            block = ""
            try:
                pj = self._gen_json(f"""Escreva a PARTE {i + 1} de {len(partes)} de um roteiro
narrado dark em {language}, tom {tone}. Foco desta parte: {parte.get('foco', '')}.
Escreva NO MÍNIMO {per_part} PALAVRAS (crítico — não seja breve, desenvolva com detalhes
sensoriais e tensão).{prev}{fim}
Frases curtas e visuais (8-20 palavras), texto corrido de narração, SEM títulos/marcações.
Devolva APENAS JSON {{"texto": "..."}}.

Contexto (parte anterior, para continuidade): {blocks[-1][-500:] if blocks else '(início)'}""")
                block = str(pj.get("texto", "")).strip()
                # parte curta demais → uma expansão dela
                if len(block.split()) < per_part * 0.8:
                    ej = self._gen_json(f"""Este trecho tem {len(block.split())} palavras mas
precisa de pelo menos {per_part}. EXPANDA-O mantendo a história e o tom {tone}, adicionando
detalhes e tensão, sem repetir. Devolva APENAS JSON {{"texto": "..."}}.

TRECHO:
{block}""")
                    block = str(ej.get("texto", block)).strip() or block
            except Exception:
                pass
            if block:
                blocks.append(block)
        script = " ".join(blocks).strip()
        if len(script.split()) < target * 0.55:
            raise RuntimeError("Roteiro longo veio curto — tente de novo ou reduza a duração")
        return script

    def rewrite_script(self, transcript: str, language: str, tone: str) -> str:
        """Remodelagem: transcrição de vídeo de sucesso → roteiro novo e mais forte."""
        if not self.available:
            raise RuntimeError("A remodelagem precisa da GEMINI_API_KEY.")
        source = transcript[:24000]
        outline = ""
        if len(transcript) > 24000:  # roteiros muito longos: extrai a espinha dorsal antes
            data = self._gen_json(
                "Extraia da transcrição a história completa em tópicos detalhados "
                "(fatos, sequência, reviravoltas). Devolva APENAS JSON "
                '{"beats": ["tópico 1", ...]}.\n\nTRANSCRIÇÃO:\n' + transcript[:60000])
            outline = "\n".join(f"- {b}" for b in data.get("beats", []))
            source = transcript[:8000]
        outline_block = f"ESPINHA DORSAL DA HISTÓRIA:\n{outline}\n" if outline else ""
        prompt = f"""Você é roteirista de canais dark. Abaixo está a TRANSCRIÇÃO de um vídeo
que fez muito sucesso (pode estar sem pontuação, com erros de reconhecimento e vinhetas).

Sua missão: REESCREVER do zero esta história/narrativa em {language}, deixando-a AINDA mais
envolvente — sem copiar frases do original.

REGRAS:
- Tom: {tone}
- NÃO copie frases literais: reconte com estrutura, ritmo e palavras próprias
- Hook novo e mais forte nas 2 primeiras frases
- Remova CTAs ("se inscreva", "deixa o like"), patrocínios e vinhetas
- Corrija pontuação; frases curtas e visuais (8-20 palavras) — cada frase vira uma cena
- Mantenha os fatos e a sequência real da história; melhore transições e suspense
- Tamanho similar ao original (±20%)

{outline_block}TRANSCRIÇÃO ORIGINAL:
{source}

Devolva APENAS JSON: {{"script": "roteiro novo completo"}}"""
        data = self._gen_json(prompt)
        script = str(data.get("script", "")).strip()
        if len(script) < 100:
            raise RuntimeError("Reescrita veio vazia — tente novamente")
        return script

    def publication_kit(self, analysis: dict, script: str, language: str) -> dict:
        """Título/descrição/tags otimizados para o YouTube."""
        if not self.available:
            raise RuntimeError("O kit de publicação precisa da GEMINI_API_KEY.")
        prompt = f"""Você é estrategista de crescimento de canais dark no YouTube — seu
trabalho é maximizar CTR, retenção e descoberta na busca para monetizar.

História: {analysis.get('summary', script[:400])}
Clima: {analysis.get('mood', '')}
Idioma do canal: {language}

TÁTICAS OBRIGATÓRIAS:
- Títulos (≤70 chars): curiosity gap real (prometa a pergunta, não a resposta),
  emoção + especificidade (números, datas, lugares), palavra-chave principal no início.
  Varie os 5: 1 pergunta, 1 com número, 1 declaração chocante, 1 "ninguém explica…",
  1 curto e agressivo. Nada de clickbait mentiroso (mata retenção e o canal).
- Descrição: as 2 PRIMEIRAS linhas decidem busca e cliques — resuma com as
  palavras-chave principais. Depois: parágrafo expandindo a história (SEO natural),
  CTA de inscrição curto, e 3-5 hashtags relevantes na última linha.
- Tags: mix de cauda longa (frases de busca reais) + termos amplos do nicho +
  variações com erro comum de grafia se fizer sentido. 15-20 itens.

Devolva APENAS JSON:
{{
  "titles": ["5 títulos"],
  "description": "descrição completa",
  "tags": ["tags"]
}}"""
        return self._gen_json(prompt)

    def thumbnail_prompts(self, analysis: dict, style_label: str, n: int = 3) -> list[dict]:
        """Prompts de thumbnail com texto de impacto (o Nano Banana renderiza texto)."""
        if not self.available:
            return [{"prompt": analysis.get("summary", "dramatic scene"), "text": "SEGREDO"}] * n
        prompt = f"""Crie {n} conceitos de thumbnail de YouTube para este vídeo dark.
História: {analysis.get('summary', '')}
Clima: {analysis.get('mood', '')}
Estilo visual do vídeo: {style_label}

Devolva APENAS JSON: {{"thumbs": [{{"prompt": "cena dramática em inglês, 1 sujeito grande,
composição de thumbnail, cores contrastantes", "text": "TEXTO DE IMPACTO ≤3 palavras em
português"}}]}} com exatamente {n} itens."""
        try:
            data = self._gen_json(prompt)
            return (data.get("thumbs") or [])[:n]
        except Exception:
            return [{"prompt": analysis.get("summary", "dramatic scene"), "text": "SEGREDO"}] * n

    # camadas de movimento válidas p/ Ken Burns
    CAMERAS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down",
               "diag_dr", "diag_ur", "zoom_pan_right", "zoom_pan_left",
               "pulse", "handheld"]

    def motion_plan(self, sentence: str, scene_prompt: str, image_path: str | None = None) -> dict:
        """Analisa frase+imagem e decide como animar (Ken Burns e/ou prompt Veo)."""
        fallback = {"camera": "zoom_in", "intensity": 0.10,
                    "veo_prompt": f"Slow cinematic camera move, subtle natural motion. {scene_prompt[:300]}"}
        if not self.available:
            return fallback
        prompt = f"""Você é diretor de fotografia. A imagem (se anexada) ilustra a frase narrada:
"{sentence}"
Descrição da cena: {scene_prompt[:400]}

Decida o movimento que reforça a narrativa. Devolva APENAS JSON:
{{
  "camera": "um de: zoom_in | zoom_out | pan_left | pan_right | pan_up | pan_down | "
            "diag_dr | diag_ur | zoom_pan_right | zoom_pan_left | pulse (respiração "
            "sutil, cenas contemplativas) | handheld (tensão, câmera na mão)",
  "intensity": 0.06 a 0.18 (sutil→forte),
  "veo_prompt": "prompt EM INGLÊS para animar esta imagem em vídeo: movimento de câmera + o que se move na cena (vento, água, luz, gesto), fiel à imagem, sem cortes"
}}"""
        try:
            data = self._gen_json(prompt, image_path=image_path)
            if data.get("camera") not in self.CAMERAS:
                data["camera"] = "zoom_in"
            data["intensity"] = min(0.18, max(0.05, float(data.get("intensity", 0.1))))
            data.setdefault("veo_prompt", fallback["veo_prompt"])
            return data
        except Exception:
            return fallback
