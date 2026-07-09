"""Catálogo de nichos do YouTube — organizado por categoria.

Usado no sugestor de histórias, na Central do Canal e na produção em
lote/agendada. Os selects permitem DIGITAR qualquer nicho fora da lista
(new-value-mode), então isto é um mapa dos territórios mais fortes — não um limite.
"""
from __future__ import annotations

NICHE_CATALOG: dict[str, list[str]] = {
    "Mistérios & Inexplicado": [
        "Mistérios não resolvidos", "Casos de desaparecimento", "Lugares proibidos",
        "Arquivos desclassificados", "Sociedades secretas", "Mistérios da internet",
        "Tesouros perdidos", "Civilizações perdidas", "OVNIs e UAPs",
        "Criptídeos e criaturas", "Paranormal e assombrações", "Mistérios do oceano",
        "Mistérios da aviação", "Coincidências impossíveis", "Símbolos e códigos secretos",
    ],
    "True Crime": [
        "Casos criminais históricos", "Golpes e fraudes famosos", "Assaltos lendários",
        "Crimes cibernéticos", "Máfia e crime organizado", "Casos resolvidos por DNA",
        "Detetives e grandes investigações", "Fugas de prisão", "Erros judiciais",
        "Crimes corporativos", "Falsificadores famosos",
    ],
    "Terror & Creepypasta": [
        "Histórias de terror originais", "Creepypastas clássicas", "Relatos de terror reais",
        "Lendas urbanas", "Folclore sombrio mundial", "Terror psicológico narrado",
        "Casas e lugares assombrados", "Terror espacial", "Analog horror",
        "Rituais e ocultismo (educativo)", "Terror rural brasileiro",
    ],
    "Histórias Bíblicas & Fé": [
        "Histórias bíblicas narradas", "Personagens da Bíblia", "Profecias e apocalipse",
        "Arqueologia bíblica", "Parábolas explicadas", "Anjos e demônios na tradição",
        "História da Igreja", "Salmos e orações narradas", "Histórias de santos",
        "Milagres documentados", "Reis e reinos do Antigo Testamento",
    ],
    "História": [
        "História antiga (Egito, Roma, Grécia)", "História medieval", "Primeira Guerra Mundial",
        "Segunda Guerra Mundial", "Guerra Fria e espionagem", "Batalhas decisivas",
        "Impérios e dinastias", "História do Brasil", "Piratas e grandes navegações",
        "Desastres históricos", "Pandemias da história", "Arqueologia e descobertas",
        "Vida cotidiana em outras épocas", "Rainhas e mulheres na história",
    ],
    "Guerra & Militar": [
        "Histórias de soldados", "Operações especiais", "Armas e tecnologia militar",
        "Estratégia militar explicada", "Aviação de combate", "Submarinos e guerra naval",
        "Espiões e agências secretas", "Sobrevivência em guerra", "Mercenários e legiões",
    ],
    "Ciência & Espaço": [
        "Curiosidades científicas", "Astronomia e cosmos", "Buracos negros e paradoxos",
        "Física quântica acessível", "Biologia bizarra", "Experimentos históricos",
        "Grandes cientistas", "Futuro da humanidade", "Exploração espacial",
        "Inteligência artificial", "Matemática curiosa", "Química do dia a dia",
    ],
    "Dinheiro & Negócios": [
        "Histórias de bilionários", "Ascensão e queda de empresas", "Golpes financeiros",
        "Economia explicada", "Mentalidade de riqueza", "Investimentos (educativo)",
        "Histórias de marcas famosas", "Empreendedores improváveis", "Bastidores de indústrias",
        "Falências espetaculares", "Dinheiro na história",
    ],
    "Motivacional & Mente": [
        "Estoicismo", "Disciplina e hábitos", "Histórias de superação",
        "Filosofia prática", "Conselhos dos mais velhos", "Alta performance",
        "Mindset e foco", "Reflexões narradas", "Sabedoria oriental",
        "Propósito e sentido da vida",
    ],
    "Curiosidades & Listas": [
        "Fatos surpreendentes", "Top 10 e rankings", "Comparações de escala",
        "E se…? (hipóteses)", "Recordes mundiais", "Geografia curiosa",
        "Coisas que você não sabia", "Curiosidades de países", "Objetos com histórias absurdas",
        "Leis estranhas pelo mundo",
    ],
    "Biografias & Vidas": [
        "Celebridades: ascensão e queda", "Gênios incompreendidos", "Vidas trágicas",
        "Pessoas que mudaram o mundo", "Herdeiros e dinastias", "Atletas lendários",
        "Artistas malditos", "Impostores famosos", "Crianças prodígio: e depois?",
    ],
    "Psicologia & Comportamento": [
        "Psicologia sombria", "Manipulação e persuasão (defesa)", "Linguagem corporal",
        "Transtornos na história", "Comportamento humano curioso", "Dilemas morais",
        "Experimentos psicológicos famosos", "Histórias de traição", "Sonhos e subconsciente",
    ],
    "Sobrevivência & Aventura": [
        "Sobrevivência real", "Desastres e resgates", "Grandes exploradores",
        "Tragédias no montanhismo", "Naufrágios", "Perdidos na selva",
        "Sobrevivência no ártico", "Pessoas isoladas do mundo", "Travessias impossíveis",
    ],
    "Tecnologia & Internet": [
        "Histórias da internet", "Hackers famosos", "Dark web (educativo)",
        "Startups que faliram", "Vazamentos e privacidade", "Mistérios de videogames",
        "História dos videogames", "Tecnologia retrô", "Golpes digitais",
        "Inteligência artificial no cotidiano",
    ],
    "Esportes": [
        "Histórias do futebol", "Lendas do esporte", "Escândalos esportivos",
        "Bastidores olímpicos", "Lutas e UFC", "Automobilismo e F1",
        "Times que desapareceram", "Viradas históricas",
    ],
    "Animais & Natureza": [
        "Animais mais mortais", "Comportamento animal curioso", "Oceano profundo",
        "Natureza extrema", "Predadores pré-históricos", "Animais heróis",
        "Florestas e lugares intocados", "Fenômenos naturais raros",
    ],
    "Mitologia & Folclore": [
        "Mitologia grega", "Mitologia nórdica", "Mitologia egípcia",
        "Mitologia japonesa", "Folclore brasileiro", "Deuses e monstros",
        "Lendas indígenas", "Mitologia eslava e celta", "Criaturas da mitologia mundial",
    ],
    "Luxo & Lifestyle": [
        "Vida dos ultra-ricos", "Iates, jatos e mansões", "Relógios e carros raros",
        "Hotéis impossíveis", "Objetos mais caros do mundo", "Bastidores do luxo",
    ],
    "Saúde & Casos Médicos": [
        "Casos médicos misteriosos", "Neurociência curiosa", "Sono e sonhos",
        "Doenças raras na história", "Medicina antiga e bizarra", "Superações médicas",
    ],
    "Infantil & Contos": [
        "Fábulas narradas", "Contos clássicos recontados", "Histórias de ninar",
        "Histórias educativas", "Contos do mundo",
    ],
}


def all_niches() -> list[str]:
    """Lista plana 'Subnicho (Categoria)' para selects com busca."""
    out = []
    for cat, subs in NICHE_CATALOG.items():
        out.extend(f"{s} ({cat})" for s in subs)
    return out


def niche_count() -> int:
    return sum(len(v) for v in NICHE_CATALOG.values())
