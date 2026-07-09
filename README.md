# DarkStudio — Estúdio Desktop de Vídeos IA para Canais Dark

Aplicativo **desktop** (Windows · Linux · macOS), 100% Python, da **ideia** ao **vídeo
publicado no YouTube**:

```
Ideia/Remodelagem → Roteiro (IA) → Narração TTS → Sincronia (faster-whisper)
→ Estilo visual + consistência de personagem → Imagens IA (paralelo)
→ Animação (IA) → Edição: transições + karaokê com presets + trilha com ducking
→ Kit de publicação (títulos/descrição/tags/thumbnails) → Upload agendado no YouTube
```

**Formatos**: 16:9 (YouTube) · 9:16 (Shorts/TikTok/Reels) · 1:1 — o seletor atravessa
todo o pipeline (imagens, movimento, legendas, render).

**Fábrica**: produção em lote (cole N ideias e deixe rodando) e **remodelagem de canal**
(URL do canal → top vídeos por views → legenda extraída → IA reescreve a história do zero).

## 🚀 Como rodar (sempre em .venv)

**Windows** — duplo clique em `run.bat` (ou no terminal):

```bat
run.bat
```

**Linux / macOS**:

```bash
chmod +x run.sh && ./run.sh
```

Na primeira execução o script cria o `.venv` e instala todas as dependências **dentro dele**
— nada é instalado no sistema. O app abre em **janela desktop nativa** (sem navegador).

> Use **Python 3.11–3.13** (recomendado 3.12). O 3.10.0 tem um bug no CPython que quebra o
> empacotamento com PyInstaller, e o yt-dlp está abandonando o 3.10.

Modos extras:

```bash
.venv\Scripts\python app.py --web       # modo navegador (desenvolvimento), em :8420
.venv\Scripts\python cli.py --demo      # pipeline completo por linha de comando (teste)
.venv\Scripts\python cli.py --name "Meu vídeo" --script roteiro.txt --style pixar3d --karaoke
```

> Linux: a janela nativa usa GTK/WebKit → `sudo apt install gir1.2-webkit2-4.1 python3-gi`.
> FFmpeg: se não houver no sistema, o app usa o binário embutido do `imageio-ffmpeg`
> (fallback). Para karaokê com fontes do sistema, recomenda-se FFmpeg completo
> (`winget install ffmpeg` / `brew install ffmpeg` / `apt install ffmpeg`).

## 📦 Gerar o instalável (executável)

Rode **no sistema alvo** (PyInstaller não cruza plataformas):

```bat
scripts\build_windows.bat      → dist\DarkStudio\DarkStudio.exe
```

```bash
bash scripts/build_unix.sh     → dist/DarkStudio/ (Linux) · dist/DarkStudio.app (macOS)
```

Distribua a pasta `dist/DarkStudio` inteira (ou empacote com Inno Setup / .dmg / AppImage).

> Com todas as engines locais instaladas (torch etc.) o executável fica com vários GB.
> Para um instalador enxuto (~500MB), gere o build num `.venv` só com as libs do topo do
> requirements (sem o bloco de engines locais) — as engines de API continuam todas
> funcionando. Atenção também à licença GPL do piper-tts em builds distribuídos.

## 🔑 Chave de API

Uma única chave alimenta toda a IA generativa: **GEMINI_API_KEY**
([Google AI Studio](https://aistudio.google.com/apikey)) — configure na engrenagem ⚙ do app
(fica no `.env`).

| Uso | Modelo padrão |
|---|---|
| Imagens (Nano Banana) | `gemini-3.1-flash-image` |
| Engenharia de prompts / análise de roteiro | `gemini-2.5-flash` |
| Animação image-to-video (opcional, pago) | `veo-3.1-fast-generate-preview` |

Sem chave o app segue funcionando: imagens via **Pollinations** (grátis) e prompts por template.
Ids de modelo são editáveis nas Configurações.

### Mais provedores (redundância e opções grátis)

- **Imagens grátis**: além do Pollinations (sem chave), **Hugging Face FLUX** (`HF_TOKEN`
  grátis) e **Together AI FLUX** (`TOGETHER_API_KEY` grátis) — troque no select "Provedor"
  da tela Imagens (há um botão "Trocar para grátis" quando o Gemini estiver sem créditos).
- **Higgsfield** (pago): provedor que agrega **Sora 2, Kling 3, Veo 3.1, Seedance** para
  imagem e vídeo — configure `HIGGSFIELD_API_KEY` e escolha "Higgsfield" no provedor de
  imagens ou na animação.
- Cada campo de chave nas Configurações tem um link **"obter chave ↗"** direto para a
  página do provedor.
- **🌐 Piloto de Navegador (experimental)**: gera pelas ferramentas web do Google com a
  **sua conta logada** (sem API): botão **"Whisk (navegador)"** na tela Imagens — o piloto
  digita cada prompt no Whisk/Flow, captura a imagem e coloca na cena; e **"Flow/Veo 3
  (navegador)"** na Animação — modo assistido: prompt de movimento no Ctrl+V, você clica
  gerar/baixar e o clipe é importado na cena certa. Login fica salvo em `browser_profile/`.
  Sites mudam de layout: quando a automação falhar, baixe manualmente que o app importa.
- **LLM reserva**: com `DEEPSEEK_API_KEY`, se a cota do Gemini acabar, roteiros e prompts
  **continuam sozinhos** no DeepSeek (fallback automático).
- **Google via OAuth (Vertex AI)**: em Configurações → "Google via OAuth", ligue o Vertex,
  informe o ID do projeto Cloud e rode `gcloud auth application-default login`. Dá acesso a
  Gemini + Imagen + **Veo** cobrando no seu projeto Cloud.
  > ⚠️ A assinatura **Google AI Pro/Ultra** (app Gemini) é do *produto consumidor* e **não**
  > libera cota de API/Veo para código. O acesso programático exige API key do AI Studio
  > **ou** Vertex AI com billing ativo — são trilhos separados.

### Vozes e amostras

Cada engine traz **muitas vozes** (Gemini 30, Coqui 18, Kokoro 18/en, ElevenLabs 16, OpenAI
11, Qwen3 9, Edge 7pt/12en, Piper 8…). Dois botões ao lado da voz:
- **▶** ouve a amostra da voz atual (fica salva);
- **🎵 Galeria de vozes** lista TODAS as vozes do engine com player em cada uma e um botão
  **"Gerar todas as amostras"** — as amostras ficam guardadas em `voices/_samples/`, geradas
  uma vez e prontas para sempre. As vozes **Edge (grátis) são pré-geradas automaticamente**
  ao abrir o app, então já vêm prontas de fábrica.

## 🧠 Pipeline

**Piloto automático**: o toggle **"Automático"** no topo de cada etapa encadeia o pipeline
— ao terminar uma etapa, ele avança e executa a próxima sozinho, até o MP4 final. Trocar a
voz e regerar a narração **reaproveita** imagens, estilo e animação já prontos (só a
sincronia e o vídeo final são refeitos).

1. **Roteiro** — cada frase vira uma cena.
2. **Narração** — 9 engines plugáveis (troque no select da tela Narração):

   | Engine | Tipo | O que é |
   |---|---|---|
   | `edge` *(padrão)* | API grátis | Vozes neurais Microsoft — melhor custo/qualidade pt-BR |
   | `gemini` | API (mesma chave do app) | Aceita **instrução de estilo** ("tom sombrio, ritmo lento") |
   | `qwen3` | local, Apache 2.0 | Qwen3-TTS (jan/2026): 10 idiomas c/ pt, clonagem 3s — `pip install qwen-tts torch soundfile` |
   | `elevenlabs` | API paga | Referência comercial em pt-BR (ELEVENLABS_API_KEY) |
   | `openai` | API paga | gpt-4o-mini-tts, barato, aceita estilo (OPENAI_API_KEY) |
   | `coqui` | local | XTTS-v2 (17 idiomas, clonagem — **licença NÃO comercial CPML!**) e VITS pt — `pip install coqui-tts` |
   | `kokoro` | local leve | Apache 2.0, CPU — `pip install kokoro soundfile` |
   | `chatterbox` | local GPU | Clonagem MIT — `pip install chatterbox-tts` |
   | `piper` | local levíssimo | MIT, CPU instantâneo, qualidade média — `pip install piper-tts` |
3. **Sincronia** — **faster-whisper** (CTranslate2, int8, CPU ou GPU) extrai timestamps por
   palavra; alinhador casa com as frases originais do roteiro.
4. **Estilo visual** — **25 estilos** + personalizado, cada um com engenharia de prompt
   própria ([core/styles.py](core/styles.py)): Doodle, Storybook, Pixar 3D, Realista,
   Anime, Aquarela, Flat, HQ/Comic, Noir P&B, Cyberpunk, Óleo, Lápis/Carvão, Foto Antiga,
   Dark Fantasy, Pixel Art, Low Poly, Massinha, Papel Recortado, Isométrico, **Ghibli**,
   **Cel Shaded**, **Boneco de Lã (Feltro)**, **Analog Horror (VHS)** e **Anime Retrô 90s**
   (estilos de maior retenção no YouTube em 2026). A IA fixa personagens/cenário p/
   consistência (com imagem de referência).
   **Animação**: 12 movimentos de câmera decididos pela IA (zooms, pans, diagonais,
   zoom+pan, pulsar, câmera na mão).
5. **Imagens** — Gemini Nano Banana, Pollinations ou mock; normalizadas p/ 1920×1080.
6. **Animação** — IA decide o movimento por cena: **Ken Burns** local (grátis) ou **Veo 3.1**.
7. **Exportação** — FFmpeg: 1 segmento por frase com **cache incremental**,
   **15 transições** (crossfade, dissolver, deslizar, círculo, radial, zoom-através,
   pixelizar, borrão… e 🎲 **aleatória a cada corte**) sem perder o sincronismo,
   **12 filtros de cor** (teal & orange, noir P&B, vintage, VHS, glow, grão de filme,
   vinheta…), narração + trilha com ducking, fades, e legendas **ASS karaokê** com
   **9 presets** (Clássico, Impacto, Alerta Vermelho, Minimal, Neon, Ember, Dourado,
   Caixa TikTok, Caixa Escura) + modo **varredura suave (\\kf)** ou bloco por palavra,
   MAIÚSCULAS, pop de entrada e caixa de fundo. Sai `final.mp4` + `legenda.srt`.
8. **Publicação** — kit gerado por IA (5 títulos de CTR, descrição, tags, 3 thumbnails com
   texto de impacto) e **upload direto para o YouTube** com agendamento.

## 🏭 Fábrica de conteúdo

- **Gerar roteiro com IA**: na tela Roteiro — ideia + duração + tom → roteiro pronto.
- **Produção em lote** (ícone 🏭 no topo): uma ideia por linha; o app escreve o roteiro e
  produz cada vídeo até o MP4, em sequência. Botão *Cancelar* interrompe com segurança.
  O painel traz **TODAS as configurações de todas as etapas** (Conteúdo, Narração, Produção,
  Legendas e edição) — engine/voz TTS, whisper, provedor de imagem, tipo de animação,
  preset e modo de karaokê, transição, filtro de cor, etc. Configure **uma vez** e vale para
  todos os vídeos do lote/agenda ([core/vconfig.py](core/vconfig.py) aplica ao projeto).
- **Agendador automático** (ícone 📅 no topo): programe ideias para produzir em dia/hora
  marcados (ex.: madrugada) e, opcionalmente, **publicar sozinho no YouTube** — 1ª
  publicação na data escolhida e as demais espaçadas por N horas (ex.: 1 vídeo/dia às 19h).
  Jobs ficam em `schedule.json`; produções atrasadas rodam quando o app abre. Para rodar
  sem interface (servidor/PC ligado): `python cli.py --scheduler`.
- **Estudar & Remodelar canal** (ícone 🔄 no topo): passe a URL de um canal que já dá
  resultado e os agentes fazem um **dossiê completo**: nicho detectado, formato/cadência,
  fórmula dos títulos, o que o canal usa, e uma **tabela de todos os top vídeos** com views,
  **velocidade (views/mês)** e **ganho estimado por vídeo** (US$), além de marcar os melhores
  candidatos a remodelar. Escolha um vídeo → extraímos a legenda → a IA **reescreve a
  narrativa do zero** (novo hook, sem frases copiadas, sem CTAs) → vira um projeto pronto.
  > ⚠️ **Ganhos são ESTIMATIVAS** (views ÷ 1000 × RPM típico do nicho, estimado por IA) — a
  > receita real é privada e o YouTube não a expõe nem por API; nenhuma ferramenta do
  > mercado tem o número exato. Use como pesquisa criativa e confira direitos de histórias.

## 🖥️ Geração 100% local na sua GPU (grátis e offline)

Com uma GPU NVIDIA (a partir de ~6GB, ex.: RTX 2060), o DarkStudio gera **imagens e
vídeos no seu próprio computador**, sem APIs:

**Imagens** — provedor **"Local na sua GPU"** (tela Imagens). Modelos curados
(Configurações → Geração local):

| Modelo | Licença | Na RTX 2060 6GB | Quando usar |
|---|---|---|---|
| **SDXL** *(padrão)* | openrail++ (comercial OK) | ~45s/imagem | equilíbrio qualidade/compatibilidade |
| **Z-Image-Turbo** | **Apache 2.0** | melhor com 8GB+ | o TOP de 2026 — qualidade de FLUX.2 em 8 passos |
| **SD 1.5** | openrail | ~10s/imagem | rascunhos rápidos |
| **FLUX.1 schnell** | Apache 2.0 | 2-5 min (offload) | máxima qualidade Apache, com paciência |

Há também o provedor **"SD WebUI local"**: aponte para o seu AUTOMATIC1111/Forge
(`--api`, porta 7860) e use **qualquer modelo do CivitAI** que você já tenha.

**Vídeo (imagem→vídeo)** — na tela Animação, provedor **"🖥️ LTX-Video na sua GPU"**: anima
cada cena localmente (~2-5 min/clipe na 2060, 704×416 reescalado no render).

**Pré-download**: Configurações → Geração local → **"⬇ Baixar modelos locais agora"** baixa
de uma vez o modelo de imagens escolhido, o LTX-Video e o Whisper — tudo fica no cache e
**nenhuma geração espera download**. Alternativas de
ponta para quem tem mais VRAM (rodando no ComfyUI + botão **"Importar clipes de pasta"**):
**Wan 2.2 TI2V-5B** (melhor com 8GB+, GGUF Q4 roda em 6GB a 480p) e **HunyuanVideo/LTX-2**
(12GB+). A 1ª geração baixa o modelo do Hugging Face e fica em cache.

> Bônus da GPU: os TTS locais (Qwen3/XTTS/Chatterbox) e o whisper também aceleram
> automaticamente (o app injeta as DLLs cuBLAS/cuDNN dos wheels pip — sem instalar CUDA).

## 🤖 Equipe de agentes + Central do Canal

O DarkStudio trabalha com **agentes de IA especializados** por etapa: Estrategista de
Conteúdo (sugere histórias por nicho — botão 💡 no roteiro, lote e agendador), Roteirista
Dark, Diretor de Arte, Especialista SEO/CTR, **Auditor de Canal** e **Designer de Marca**.

**Catálogo de nichos** ([core/niches.py](core/niches.py)): **193 nichos em 20 categorias**
— de Histórias Bíblicas a True Crime, Terror/Creepypasta, História, Guerra, Ciência,
Dinheiro, Motivacional, Mitologia, Curiosidades, Sobrevivência, Esportes, Infantil e mais.
Todos os selects de nicho têm **busca por digitação** e aceitam **nicho personalizado**
(digite o seu e Enter) — o nicho alimenta o sugestor de histórias, o gerador de roteiro,
o lote, o agendador e a criação de canal, então dá para produzir no nicho de **qualquer
canal que você queira modelar ou criar**.

Na **Central do Canal** (ícone 📺 no topo):

- **Analisar meu canal**: passe a URL → o Auditor cruza dados públicos (yt-dlp) e devolve
  nota, correções priorizadas, descrição otimizada, keywords e plano de 30 dias. Com o
  OAuth conectado, o app **aplica sozinho** o que a API permite (descrição, keywords,
  banner).
- **Criar canal do zero**: a API do YouTube **não cria canais** — mas os agentes montam
  tudo: 5 nomes+handles, descrição, keywords, **logo e banner gerados por IA** (salvos em
  `channel_kit/`), ideia de trailer e checklist exato de configuração + monetização
  (1.000 inscritos + 4.000h / 10M views Shorts). Você cria o canal em 2 min de cliques e
  o app aplica o resto via API.

> Limites da API (o app te guia nesses): criar o canal, trocar nome e avatar. O escopo
> OAuth agora é o completo (`youtube`) — se você já tinha um `youtube_token.json` antigo,
> apague-o para reautorizar.

## 🎤 Estúdio de Voz — clone qualquer voz

Ícone 🎙 no topo (ou botão na tela Narração). Envie **qualquer áudio ou vídeo** com a voz:

1. **Separação**: a voz é isolada de música/efeitos ([audio-separator](https://github.com/nomadkaraoke/python-audio-separator), modelos UVR MDX-NET);
2. **Limpeza + melhora**: ruído removido e qualidade elevada a 48kHz com
   [DeepFilterNet3](https://github.com/Rikorose/DeepFilterNet) (SOTA em speech enhancement);
3. **Normalização** broadcast (highpass + loudnorm);
4. **Melhor trecho**: VAD acha o segmento de fala mais limpo (8–15s) e o whisper o
   transcreve (a transcrição é exigida pela clonagem do Qwen3);
5. **Biblioteca**: a amostra fica salva em `voices/` — nos próximos vídeos é só
   **selecionar a voz** no select (marcada com ⭐) nas engines **Qwen3**, **Coqui XTTS**
   ou **Chatterbox**. Nada de reenviar/reprocessar.

> Clone apenas vozes que você tem direito de usar (a sua, de dubladores contratados,
> ou com autorização expressa).

## ▶️ Upload direto no YouTube

1. [console.cloud.google.com](https://console.cloud.google.com) → novo projeto → ativar
   **YouTube Data API v3**;
2. Tela de consentimento OAuth (app de desktop; adicione sua conta como usuária de teste);
3. Credenciais → **ID do cliente OAuth → App para computador** → baixar JSON;
4. Salvar como `client_secret.json` na pasta do DarkStudio. O card "Publicar no YouTube"
   (tela Exportar) libera título/descrição/tags do kit, thumbnail, visibilidade e
   **agendamento**. Na 1ª vez o navegador abre para autorizar (token fica salvo local).

## 📁 Estrutura

```
run.bat / run.sh       # inicia (cria .venv sozinho na 1ª vez)
app.py                 # janela desktop (NiceGUI nativo) — ui/theme.py = design system
cli.py                 # pipeline headless
scripts/               # build dos executáveis (PyInstaller)
core/                  # pipeline: tts, transcribe, styles, llm, imagen, animate, editor
projects/<slug>/       # cada vídeo: audio/, images/, clips/, export/, project.json
```

## ⚠️ Notas

- 1ª sincronização baixa o modelo whisper (75MB–1.5GB conforme o tamanho escolhido).
- Nano Banana cobra por imagem; Veo por vídeo — teste roteiros longos com Pollinations.
- App desenhado para 1 usuário por vez (estado único de janela).
