"""Estilos visuais — cada um carrega sua engenharia de prompt.

`template` recebe {scene} (descrição da cena gerada pela IA a partir da frase).
`style_hint` orienta o LLM ao descrever a cena naquele estilo.
"""
from __future__ import annotations

# Sufixo global anti-texto/anti-marca d'água aplicado a toda imagem
GLOBAL_SUFFIX = (
    " Absolutely no text, no letters, no words, no captions, no subtitles, "
    "no logos, no watermarks. Clean cinematic composition, high detail, "
    "coherent anatomy and perspective."
)

STYLES: dict[str, dict] = {
    "doodle": {
        "label": "Boneco Palito (Doodle)",
        "emoji": "✏️",
        "desc": "Traço de quadro branco, bonecos palito expressivos — estilo whiteboard.",
        "gradient": "linear-gradient(135deg,#e2e8f0,#94a3b8)",
        "template": (
            "Whiteboard doodle illustration: expressive stick figure characters with round "
            "heads and simple faces, drawn with bold black marker strokes on a pure white "
            "background, occasional red marker accents for emphasis, minimal hand-drawn props "
            "and simple motion lines, educational whiteboard-animation aesthetic. Scene: {scene}"
        ),
        "style_hint": "cena simples com poucos elementos, ações claras de bonecos palito, sem fundos complexos",
    },
    "storybook": {
        "label": "Storybook Cinematográfico",
        "emoji": "📖",
        "desc": "Ilustração de livro infantil com luz dramática e atmosfera de cinema.",
        "gradient": "linear-gradient(135deg,#f59e0b,#b45309)",
        "template": (
            "Cinematic storybook illustration: painterly children's book artwork with rich "
            "textured brushwork, warm golden-hour palette, dramatic volumetric lighting, "
            "whimsical detailed environments, wide cinematic framing like a film still from "
            "an animated fairy tale. Scene: {scene}"
        ),
        "style_hint": "atmosfera mágica e acolhedora, ambientes detalhados, enquadramento amplo",
    },
    "pixar3d": {
        "label": "3D Pixar",
        "emoji": "🎬",
        "desc": "Render 3D de animação moderna: personagens expressivos, luz suave.",
        "gradient": "linear-gradient(135deg,#3b82f6,#8b5cf6)",
        "template": (
            "High-quality 3D animated movie still in the style of a modern Pixar film: "
            "stylized expressive characters with large emotive eyes, soft subsurface "
            "scattering skin, rounded appealing shapes, cinematic depth of field, warm "
            "bounce lighting, polished octane-quality render. Scene: {scene}"
        ),
        "style_hint": "personagens carismáticos e expressivos, emoção clara no rosto, cores vibrantes",
    },
    "cinematic": {
        "label": "Realista Cinematográfico",
        "emoji": "🎥",
        "desc": "Fotorrealismo de cinema: 35mm, grão de filme, luz dramática.",
        "gradient": "linear-gradient(135deg,#7f1d1d,#111827)",
        "template": (
            "Photorealistic cinematic film still: shot on 35mm anamorphic lens, shallow "
            "depth of field, dramatic volumetric lighting with strong contrast, subtle film "
            "grain, moody teal-and-orange color grade, ultra-detailed textures, "
            "professional movie cinematography. Scene: {scene}"
        ),
        "style_hint": "realismo total, iluminação dramática, composição de cinema, clima tenso/misterioso quando couber",
    },
    "anime": {
        "label": "Anime / Mangá",
        "emoji": "⛩️",
        "desc": "Key visual de anime: lineart nítido, cel shading, perspectiva dramática.",
        "gradient": "linear-gradient(135deg,#ec4899,#8b5cf6)",
        "template": (
            "Detailed anime key visual: crisp clean lineart, vibrant cel shading, dramatic "
            "perspective and dynamic composition, expressive anime characters, detailed "
            "painted backgrounds, high-budget anime film production quality. Scene: {scene}"
        ),
        "style_hint": "composição dinâmica, emoções intensas estilo anime, fundos pintados detalhados",
    },
    "watercolor": {
        "label": "Aquarela / Pintura",
        "emoji": "🎨",
        "desc": "Pintura em aquarela: pigmento suave, papel texturizado, clima etéreo.",
        "gradient": "linear-gradient(135deg,#14b8a6,#0e7490)",
        "template": (
            "Delicate watercolor painting: soft washes of translucent pigment on textured "
            "cold-press paper, loose expressive brushstrokes, gentle color bleeding and "
            "blooming edges, artistic use of negative space, dreamy atmospheric light. "
            "Scene: {scene}"
        ),
        "style_hint": "leveza e poesia visual, cores translúcidas, atmosfera sonhadora",
    },
    "flat": {
        "label": "Minimalista (Flat)",
        "emoji": "🔷",
        "desc": "Vetor flat moderno: formas geométricas, paleta limitada, muito espaço.",
        "gradient": "linear-gradient(135deg,#84cc16,#059669)",
        "template": (
            "Minimalist flat vector illustration: simple bold geometric shapes, limited "
            "palette of 3-4 harmonious colors, generous negative space, clean modern "
            "editorial design style, no gradients, crisp sharp edges, conceptual and "
            "symbolic representation. Scene: {scene}"
        ),
        "style_hint": "representação conceitual/simbólica da ideia, poucos elementos, composição limpa",
    },
    "comic": {
        "label": "HQ / Comic",
        "emoji": "💥",
        "desc": "Quadrinhos: tinta forte, retícula, cores chapadas dramáticas.",
        "template": (
            "Comic book panel illustration: bold ink outlines, halftone dot shading, "
            "flat dramatic colors, dynamic comic composition with strong perspective, "
            "graphic novel noir energy. Scene: {scene}"
        ),
        "style_hint": "composição de quadrinho, ação congelada dramática, sem balões de fala",
    },
    "noir": {
        "label": "Noir P&B",
        "emoji": "🕵️",
        "desc": "Film noir: preto e branco, sombras duras, fumaça e mistério.",
        "template": (
            "Black and white film noir still: hard chiaroscuro lighting, deep shadows with "
            "venetian blind light patterns, cigarette smoke haze, 1940s atmosphere, "
            "high contrast dramatic monochrome photography. Scene: {scene}"
        ),
        "style_hint": "silhuetas, contraluz, clima de suspense investigativo",
    },
    "cyberpunk": {
        "label": "Cyberpunk Neon",
        "emoji": "🌆",
        "desc": "Futuro neon: magenta e ciano, chuva, cidade high-tech.",
        "template": (
            "Cyberpunk digital artwork: neon magenta and cyan lighting, rain-slicked "
            "streets with glowing reflections, dense futuristic megacity, holograms, "
            "moody blade-runner atmosphere, cinematic sci-fi detail. Scene: {scene}"
        ),
        "style_hint": "tecnologia onipresente, luz neon refletida, escala urbana opressora",
    },
    "oil": {
        "label": "Óleo Clássico",
        "emoji": "🖼️",
        "desc": "Pintura a óleo barroca: dramática, texturizada, museu.",
        "template": (
            "Classical baroque oil painting: rich impasto brushwork, dramatic Caravaggio "
            "chiaroscuro lighting, deep burgundy and gold palette, museum masterpiece "
            "quality, canvas texture visible. Scene: {scene}"
        ),
        "style_hint": "drama renascentista, gesto teatral, luz de vela",
    },
    "sketch": {
        "label": "Lápis / Carvão",
        "emoji": "✏️",
        "desc": "Desenho a lápis e carvão: traço expressivo em papel.",
        "template": (
            "Expressive pencil and charcoal sketch on textured paper: loose confident "
            "strokes, crosshatching shadows, smudged charcoal depth, unfinished artistic "
            "edges, dramatic monochrome drawing. Scene: {scene}"
        ),
        "style_hint": "traço solto e emocional, foco no essencial da cena",
    },
    "vintage": {
        "label": "Foto Antiga",
        "emoji": "📜",
        "desc": "Fotografia de arquivo: sépia, grão, memória de outra época.",
        "template": (
            "Authentic vintage archival photograph from the early 1900s: sepia tones, "
            "film grain and scratches, soft focus edges, period-accurate clothing and "
            "environment, haunting historical documentary feel. Scene: {scene}"
        ),
        "style_hint": "verossimilhança histórica, poses de época, leve deterioração",
    },
    "dark_fantasy": {
        "label": "Dark Fantasy",
        "emoji": "🐉",
        "desc": "Fantasia sombria: castelos, névoa, épico grimdark.",
        "template": (
            "Dark fantasy concept art: grimdark epic atmosphere, gothic castles and "
            "twisted landscapes, volumetric fog, ominous red-and-ash palette, "
            "souls-like intricate detail, dramatic scale contrast. Scene: {scene}"
        ),
        "style_hint": "escala épica, ameaça iminente, beleza sombria",
    },
    "pixel": {
        "label": "Pixel Art",
        "emoji": "👾",
        "desc": "Retrô 16-bit: pixels nítidos, paleta limitada nostálgica.",
        "template": (
            "Detailed 16-bit pixel art scene: crisp pixels, limited retro palette, "
            "parallax-style depth, SNES-era adventure game aesthetic, atmospheric "
            "dithering. Scene: {scene}"
        ),
        "style_hint": "leitura clara em blocos, nostalgia de videogame",
    },
    "lowpoly": {
        "label": "Low Poly 3D",
        "emoji": "🔺",
        "desc": "3D facetado: triângulos, gradientes suaves, minimal moderno.",
        "template": (
            "Low poly 3D render: faceted geometric shapes, soft gradient lighting, "
            "clean minimal composition, stylized flat-shaded triangles, modern indie "
            "game art direction. Scene: {scene}"
        ),
        "style_hint": "formas simplificadas, poucas cores harmônicas",
    },
    "claymation": {
        "label": "Massinha (Clay)",
        "emoji": "🧱",
        "desc": "Stop motion de massinha: fofo, tátil, artesanal.",
        "template": (
            "Claymation stop-motion style: handcrafted plasticine characters with visible "
            "fingerprints, soft studio lighting, miniature set with tactile textures, "
            "charming Aardman-inspired look. Scene: {scene}"
        ),
        "style_hint": "personagens fofos e expressivos, cenário de miniatura",
    },
    "papercut": {
        "label": "Papel Recortado",
        "emoji": "📄",
        "desc": "Camadas de papel: profundidade, sombras suaves, artesanal.",
        "template": (
            "Layered paper cutout art: stacked colored paper with soft drop shadows "
            "between layers, handcrafted depth, clean silhouettes, diorama-like "
            "storybook composition. Scene: {scene}"
        ),
        "style_hint": "silhuetas em camadas, profundidade teatral",
    },
    "isometric": {
        "label": "Isométrico 3D",
        "emoji": "🏗️",
        "desc": "Mundo em miniatura isométrico: diorama limpo e detalhado.",
        "template": (
            "Isometric 3D diorama: clean miniature world viewed at 45 degrees, soft "
            "ambient occlusion, cute detailed props, pastel-accented palette, "
            "polished game-art rendering. Scene: {scene}"
        ),
        "style_hint": "cena como maquete, tudo visível de cima em ângulo",
    },
    "ghibli": {
        "label": "Ghibli / Aquarela Anime",
        "emoji": "🌿",
        "desc": "Anime nostálgico estilo Ghibli: aquarela suave, natureza viva.",
        "template": (
            "Studio Ghibli inspired anime scene: soft hand-painted watercolor backgrounds, "
            "lush detailed nature, warm nostalgic lighting, gentle pastel palette, "
            "whimsical cozy atmosphere, painterly clouds and foliage, cinematic wide shot, "
            "hayao miyazaki aesthetic. Scene: {scene}"
        ),
        "style_hint": "clima nostálgico e acolhedor, natureza exuberante, luz suave dourada",
    },
    "cel_shaded": {
        "label": "Cel Shaded",
        "emoji": "🎌",
        "desc": "Anime moderno cel shading: sombras chapadas, contornos limpos.",
        "template": (
            "Modern cel-shaded anime illustration: clean bold outlines, flat two-tone "
            "cel shading with hard shadow edges, vibrant saturated colors, crisp digital "
            "anime rendering, dynamic 90s-meets-modern anime look, sharp highlights. "
            "Scene: {scene}"
        ),
        "style_hint": "cores vibrantes, sombras em blocos duros, energia de anime de ação",
    },
    "felt": {
        "label": "Boneco de Lã (Feltro)",
        "emoji": "🧶",
        "desc": "Feltro agulhado: personagens fofos de lã, textura tátil artesanal.",
        "template": (
            "Needle-felted wool art scene: adorable handmade characters crafted from "
            "soft felted wool, visible fuzzy fiber texture, tactile miniature handmade "
            "set, warm soft studio lighting, cozy stop-motion craft aesthetic, "
            "charming and cuddly. Scene: {scene}"
        ),
        "style_hint": "personagens fofinhos de lã, texturas macias, cenário de miniatura",
    },
    "analog_horror": {
        "label": "Analog Horror (VHS)",
        "emoji": "📼",
        "desc": "Terror analógico: VHS degradado, ruído, clima perturbador.",
        "template": (
            "Analog horror still: degraded VHS videotape aesthetic, chromatic aberration "
            "and scanlines, heavy grain and tracking distortion, washed desaturated "
            "colors with sickly greens, eerie liminal atmosphere, found-footage dread, "
            "unsettling shadows. Scene: {scene}"
        ),
        "style_hint": "clima perturbador e liminar, sensação de gravação antiga e proibida",
    },
    "retro_anime": {
        "label": "Anime Retrô 90s",
        "emoji": "📺",
        "desc": "Anime dos anos 90: grão de filme, cores desbotadas, cel vintage.",
        "template": (
            "Retro 1990s anime screencap: hand-painted cel animation, muted vintage film "
            "colors, visible film grain and slight VHS softness, nostalgic dramatic "
            "lighting, classic 90s anime character design, analog charm. Scene: {scene}"
        ),
        "style_hint": "nostalgia dos anos 90, drama contido, paleta desbotada de filme",
    },
    "custom": {
        "label": "Personalizado",
        "emoji": "✨",
        "desc": "Descreva o estilo que quiser — a IA cria um super prompt exclusivo.",
        "gradient": "linear-gradient(135deg,#f43f5e,#f59e0b,#84cc16,#06b6d4,#8b5cf6)",
        "template": "{scene}",  # substituído pelo super prompt gerado
        "style_hint": "",
    },
}


def get_style(project_state: dict) -> dict:
    """Resolve o estilo efetivo do projeto (inclui custom gerado pela IA)."""
    sid = project_state["style"]["id"]
    style = dict(STYLES.get(sid, STYLES["cinematic"]))
    if sid == "custom":
        custom = project_state["style"].get("custom_style") or {}
        if custom.get("template"):
            style["template"] = custom["template"]
            style["style_hint"] = custom.get("style_hint", "")
            style["label"] = custom.get("name", "Personalizado")
    return style


def build_image_prompt(style: dict, scene: str) -> str:
    template = style.get("template") or "{scene}"
    if "{scene}" not in template:
        template = template.rstrip(". ") + ". Scene: {scene}"
    return template.format(scene=scene.strip()) + GLOBAL_SUFFIX
