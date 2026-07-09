# Guia de Instalação e Execução do DarkStudio

Bem-vindo ao guia passo a passo para instalar e rodar o **DarkStudio** na sua máquina. O sistema é um aplicativo desktop 100% Python focado em automatizar canais Dark, e foi projetado para ser muito simples de configurar.

## 1. Pré-requisitos

Antes de iniciar, certifique-se de ter os seguintes programas instalados no seu computador:

- **Python**: É necessário ter a versão **3.11, 3.12 ou 3.13** (recomendado 3.12). 
  - *Atenção:* Não utilize o Python 3.10.0 devido a problemas conhecidos de compatibilidade com o empacotador PyInstaller.
  - Baixe e instale pelo site oficial: [python.org/downloads](https://www.python.org/downloads/).
- **Git**: (Opcional, porém muito recomendado) Para clonar o repositório facilmente e receber atualizações. Baixe em [git-scm.com](https://git-scm.com/).
- **FFmpeg**: Essencial para a manipulação de vídeo/áudio e sincronia de legendas avançadas (como efeito karaokê) geradas pelo app.
  - **Windows**: Abra o PowerShell ou Prompt de Comando e rode: `winget install ffmpeg`
  - **macOS**: Abra o Terminal e rode: `brew install ffmpeg`
  - **Linux (Ubuntu/Debian)**: No terminal, rode: `sudo apt install ffmpeg`

---

## 2. Obtendo o código-fonte (Baixando o projeto)

Você precisa baixar os arquivos do DarkStudio para a sua máquina local:

1. Abra o Terminal ou Prompt de Comando.
2. Clone o repositório via Git:
   ```bash
   git clone https://github.com/MaikeSouzaL/DarkStudio.git
   cd DarkStudio
   ```
3. *(Alternativa sem Git):* Você pode baixar o código como `.zip` diretamente do botão verde "Code" no GitHub. Após baixar, descompacte a pasta, abra o terminal e navegue até a pasta descompactada.

---

## 3. Configurando a Chave de API (Google Gemini)

O aplicativo precisa de uma chave de API para funcionar em seu motor principal de Inteligência Artificial.

1. Dentro da pasta principal do projeto clonado, localize o arquivo `.env.example`.
2. Renomeie esse arquivo para `.env` (remova a parte `.example`).
3. Abra o novo arquivo `.env` usando o Bloco de Notas ou qualquer editor de texto.
4. Você verá a seguinte linha: `GEMINI_API_KEY=`
5. Acesse o [Google AI Studio](https://aistudio.google.com/apikey) logado em sua conta Google, crie uma chave gratuita (Create API Key) e cole-a após o sinal de igual no arquivo. 
   - *Exemplo de como deve ficar:* `GEMINI_API_KEY=AIzaSyA_ExemploDeChaveSua...`
6. Salve e feche o arquivo. 
*(Nota: você também poderá informar ou alterar essa chave depois diretamente pela engrenagem de configurações ⚙️ dentro do próprio app).*

---

## 4. Executando o Sistema pela primeira vez

A primeira execução irá configurar **automaticamente** um ambiente virtual Python (`.venv`) isolado da sua máquina e instalará todas as bibliotecas necessárias. **Isso pode demorar alguns minutos**, pois as dependências podem ser pesadas. Fique tranquilo, tudo fica contido dentro da pasta `.venv` sem sujar seu sistema operacional.

### No Windows:
Basta dar um duplo-clique no arquivo `run.bat` que está na raiz do projeto, ou abri-lo pelo terminal:
```bat
run.bat
```

### No Linux / macOS:
Abra o terminal, acesse a pasta do projeto, dê permissão de execução e rode o script:
```bash
chmod +x run.sh
./run.sh
```
> *Nota para usuários de Linux:* O aplicativo rodará como uma janela nativa do desktop. Caso ocorram erros visuais de dependência gráfica no Linux, instale os pacotes base: `sudo apt install gir1.2-webkit2-4.1 python3-gi`.

Pronto! Assim que as dependências forem concluídas, o aplicativo carregará na sua tela inicial!

---

## 5. Como gerar um Executável (Opcional)

Se você desejar gerar um arquivo `.exe` autônomo (Windows) ou executável Linux/macOS para poder distribuir o aplicativo pronto para outras máquinas (sem a necessidade de instalar Python nelas), utilize os scripts de build fornecidos:

1. Abra o terminal na pasta do projeto.
2. Certifique-se de já ter rodado o sistema pelo menos uma vez com sucesso, para que a pasta `.venv` esteja criada.
3. Rode o script da sua plataforma:
   - **No Windows:**
     ```bat
     scripts\build_windows.bat
     ```
     Após alguns minutos, o executável final estará pronto e disponível na pasta `dist\DarkStudio\DarkStudio.exe`.
   - **No Linux / macOS:**
     ```bash
     bash scripts/build_unix.sh
     ```
     O aplicativo ficará salvo na pasta `dist/DarkStudio/` (Linux) ou `dist/DarkStudio.app` (macOS).

---

## 6. Recursos Avançados: Rodar localmente usando placa de vídeo

Se você possuir uma placa de vídeo NVIDIA dedicada em seu computador (ex: linha RTX), poderá gerar vídeos, áudios clonados e imagens 100% de forma offline e acelerada.
1. Abra o DarkStudio normalmente.
2. Vá nas Configurações (ícone de Engrenagem ⚙️).
3. Na seção **"Geração local"**, clique no botão para baixar os modelos locais automaticamente (incluindo modelos Whisper de transcrição, IA para vídeos locais e FLUX/SDXL para imagens).
4. O sistema processará suas futuras demandas gratuitamente de forma otimizada utilizando sua GPU.
