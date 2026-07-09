"""Equipe de agentes especializados do DarkStudio.

Cada agente é um papel de IA com prompt e critérios próprios, usado nas
etapas certas do fluxo (sugestão de histórias, auditoria e criação de canal).
Os demais especialistas já atuam dentro do pipeline (roteirista em
llm.generate_script, diretor de arte em scene_prompts, SEO em publication_kit).
"""
from __future__ import annotations

from .config import Settings
from .llm import LLM

AGENTS = {
    "estrategista": {"nome": "Estrategista de Conteúdo", "icone": "insights",
                     "faz": "garimpa histórias com potencial viral no nicho"},
    "roteirista": {"nome": "Roteirista Dark", "icone": "edit_note",
                   "faz": "escreve e reescreve roteiros com retenção"},
    "diretor_arte": {"nome": "Diretor de Arte", "icone": "palette",
                     "faz": "prompts de cena, personagens e identidade visual"},
    "seo": {"nome": "Especialista SEO/CTR", "icone": "trending_up",
            "faz": "títulos, descrição, tags e thumbnails que atraem cliques"},
    "auditor": {"nome": "Auditor de Canal", "icone": "fact_check",
                "faz": "analisa canais e aponta correções priorizadas"},
    "brand": {"nome": "Designer de Marca", "icone": "brush",
              "faz": "nome, logo, banner e posicionamento do canal"},
}

from .niches import NICHE_CATALOG, all_niches, niche_count  # noqa: F401

# compatibilidade: lista plana completa (185+ nichos, com busca nos selects)
NICHES = all_niches()


class Crew:
    def __init__(self, settings: Settings):
        self.llm = LLM(settings)

    @property
    def available(self) -> bool:
        return self.llm.available

    # ------------------------------------------------ estrategista
    def suggest_ideas(self, niche: str, n: int = 10, language: str = "pt-BR",
                      extra: str = "") -> list[dict]:
        """Ideias de vídeo com potencial de audiência no nicho."""
        prompt = f"""Você é o Estrategista de Conteúdo de um canal dark no YouTube.
Nicho: {niche}. {f'Direcionamento extra: {extra}.' if extra else ''}
Idioma: {language}.

Gere {n} ideias de vídeo com ALTO potencial de views. Critérios:
- histórias/temas REAIS e verificáveis (nada inventado sobre pessoas vivas)
- curiosity gap forte: a pergunta que o espectador PRECISA responder
- mix: 40% clássicos comprovados do nicho, 40% ângulos pouco explorados,
  20% ganchos em eventos atemporais
- título provisório ≤70 caracteres

Devolva APENAS JSON:
{{"ideas": [{{"title": "título provisório", "hook": "gancho de 1 frase que abre o vídeo",
"why": "por que tende a performar (1 frase)"}}]}} com exatamente {n} itens."""
        data = self.llm._gen_json(prompt)
        return (data.get("ideas") or [])[:n]

    # ---------------------------------------------------- auditor
    def channel_audit(self, data: dict, language: str = "pt-BR") -> dict:
        """Auditoria completa de um canal existente com correções priorizadas."""
        vids = "\n".join(f"- {v['views']:,} views · {v['duration']}s · {v['title']}"
                         for v in data.get("top_videos", [])[:12])
        prompt = f"""Você é o Auditor de Canais dark do YouTube (crescimento + monetização).

DADOS PÚBLICOS DO CANAL:
Nome: {data.get('name')}
Inscritos: {data.get('subscribers', 'desconhecido')}
Descrição atual: {data.get('description') or '(vazia)'}
Total de vídeos analisados: {data.get('video_count', 0)}
Top vídeos:
{vids or '(nenhum)'}

Produza uma auditoria em {language}. Devolva APENAS JSON:
{{
  "score": 0 a 100 (saúde do canal p/ crescer e monetizar),
  "diagnostico": "resumo direto em 2-3 frases",
  "forcas": ["até 4 pontos fortes"],
  "correcoes": [{{"area": "ex.: descrição/frequência/títulos/nicho/thumbnails",
                 "problema": "o que está errado", "acao": "o que fazer exatamente",
                 "automatico": true se o DarkStudio pode aplicar via API
                 (descrição do canal, palavras-chave, banner) senão false}}],
  "descricao_otimizada": "nova descrição de canal pronta (SEO nas 2 primeiras linhas, "
                         "proposta de valor, cadência de postagem, CTA)",
  "keywords": ["12-18 palavras-chave de canal"],
  "plano_30_dias": ["5-7 passos priorizados p/ acelerar monetização"]
}}"""
        return self.llm._gen_json(prompt)

    # ---------------------------------------------- estudo p/ remodelagem
    def channel_study(self, data: dict, language: str = "pt-BR") -> dict:
        """Estudo profundo do canal: nicho, RPM estimado, fórmula e prioridades."""
        vids = "\n".join(
            f"{i + 1}. {v['views']:,} views · {v['duration'] // 60}min"
            f"{' · ' + str(v.get('views_month', '')) + ' views/mês' if v.get('views_month') else ''}"
            f" · {v['title']}"
            for i, v in enumerate(data.get("top_videos", [])))
        prompt = f"""Você é analista de canais dark do YouTube (monetização e formato).

CANAL: {data.get('name')} · {data.get('subscribers') or '?'} inscritos
Descrição: {(data.get('description') or '')[:400]}
TOP VÍDEOS:
{vids}

Estude TUDO que dá para inferir dos dados públicos. Devolva APENAS JSON:
{{
  "nicho": "nicho principal detectado",
  "rpm_min": RPM mínimo realista do nicho em US$ (número),
  "rpm_max": RPM máximo realista (número),
  "rpm_justificativa": "1 frase: por que essa faixa para esse nicho/idioma",
  "formato": "o que o canal usa: duração típica, long-form/shorts, narração, tipo de visual",
  "cadencia": "ritmo de postagem percebido",
  "formula_titulos": "a fórmula dos títulos que mais performam (padrões concretos)",
  "o_que_usa": ["4-6 elementos que o canal claramente utiliza: estilo visual, gancho, estrutura…"],
  "forcas": ["3-4 pontos fortes"],
  "prioridade_remodelagem": [{{"indice": nº do vídeo (1-based), "porque": "1 frase"}}]
    com os 3 melhores candidatos a remodelar
}}"""
        return self.llm._gen_json(prompt)

    # ------------------------------------------------------ brand
    def channel_kit(self, niche: str, audience: str, language: str = "pt-BR") -> dict:
        """Kit completo para criar um canal do zero."""
        prompt = f"""Você é o Designer de Marca + Estrategista de canais dark no YouTube.
Nicho: {niche}. Público-alvo: {audience or 'geral do nicho'}. Idioma: {language}.

Monte o kit de lançamento do canal. Devolva APENAS JSON:
{{
  "nomes": [{{"nome": "nome do canal (memorável, ≤20 chars)", "handle": "@sugestao",
             "porque": "1 frase"}}] com 5 opções,
  "descricao": "descrição de canal pronta (SEO nas 2 primeiras linhas, proposta de valor, "
               "cadência, CTA de inscrição)",
  "keywords": ["12-18 palavras-chave de canal"],
  "logo_prompt": "prompt EM INGLÊS para gerar o avatar/logo: ícone simbólico do nicho, "
                 "flat/minimal, alto contraste, legível em 98x98px, fundo escuro, SEM texto",
  "banner_prompt": "prompt EM INGLÊS para o banner: cena atmosférica do nicho, área central "
                   "limpa para texto, cinematográfico, cores da identidade",
  "trailer_ideia": "ideia de vídeo-trailer de 30s do canal",
  "checklist": ["10-12 passos EXATOS para configurar e monetizar rápido: criação do canal, "
                "handle, uploads padrão, playlists, cadência, requisitos YPP (1000 inscritos "
                "+ 4000h ou 10M views Shorts), AdSense, etc."]
}}"""
        return self.llm._gen_json(prompt)


# --------------------------------------------------- dados públicos de canal
def fetch_channel_public(channel_url: str) -> dict:
    """Coleta dados públicos do canal via yt-dlp (sem chave)."""
    import yt_dlp

    from .remodel import top_videos

    vids = top_videos(channel_url, limit=12)
    info = {}
    try:
        with yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True, "no_warnings": True,
                               "playlistend": 1}) as ydl:
            raw = ydl.extract_info(channel_url.rstrip("/") + "/videos", download=False)
        info = {"name": raw.get("channel") or raw.get("uploader") or raw.get("title"),
                "subscribers": raw.get("channel_follower_count"),
                "description": (raw.get("description") or "")[:1200],
                "video_count": raw.get("playlist_count") or len(vids)}
    except Exception:
        pass
    info["top_videos"] = vids
    info.setdefault("name", channel_url)
    return info
