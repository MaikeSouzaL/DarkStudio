"""Upload direto para o YouTube (Data API v3) com agendamento.

Requer um `client_secret.json` na raiz do projeto:
  1. console.cloud.google.com → criar projeto → ativar "YouTube Data API v3"
  2. Tela de consentimento OAuth (tipo: app de desktop, usuário de teste = sua conta)
  3. Credenciais → ID do cliente OAuth → tipo "App para computador" → baixar JSON
  4. Salvar como client_secret.json na pasta do DarkStudio

No primeiro upload o navegador abre para autorizar; o token fica salvo localmente.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT_DIR

CLIENT_SECRET = ROOT_DIR / "client_secret.json"
TOKEN_FILE = ROOT_DIR / "youtube_token.json"
# escopo completo: upload + gerenciamento do canal (descrição, keywords, banner)
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def available() -> bool:
    return CLIENT_SECRET.exists()


def _get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent",
                                          authorization_prompt_message="")
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def upload_video(video_path: Path, title: str, description: str, tags: list[str],
                 privacy: str = "private", publish_at: datetime | None = None,
                 thumbnail: Path | None = None, progress=None) -> str:
    """Sobe o vídeo e retorna a URL. publish_at (com tz) agenda a publicação."""
    from googleapiclient.http import MediaFileUpload

    if not available():
        raise RuntimeError("client_secret.json não encontrado na pasta do DarkStudio — "
                           "veja o passo a passo no README.")
    service = _get_service()

    status: dict = {"selfDeclaredMadeForKids": False}
    if publish_at:
        status["privacyStatus"] = "private"  # exigido pelo YouTube p/ agendar
        status["publishAt"] = publish_at.astimezone(timezone.utc).isoformat() \
            .replace("+00:00", "Z")
    else:
        status["privacyStatus"] = privacy

    body = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": tags[:30], "categoryId": "24"},
        "status": status,
    }
    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        st, response = request.next_chunk()
        if st and progress:
            progress(int(st.progress() * 100))
    video_id = response["id"]

    if thumbnail and thumbnail.exists():
        try:
            service.thumbnails().set(videoId=video_id,
                                     media_body=str(thumbnail)).execute()
        except Exception:
            pass  # conta sem thumbnail customizada verificada — segue sem
    return f"https://youtu.be/{video_id}"


# --------------------------------------------------- gerenciamento do canal
def get_my_channel() -> dict:
    """Canal da conta conectada (snippet + estatísticas + branding)."""
    service = _get_service()
    resp = service.channels().list(part="snippet,statistics,brandingSettings",
                                   mine=True).execute()
    items = resp.get("items") or []
    if not items:
        raise RuntimeError("Nenhum canal nesta conta Google — crie um em "
                           "youtube.com (2 minutos) e tente de novo.")
    ch = items[0]
    return {
        "id": ch["id"],
        "name": ch["snippet"]["title"],
        "description": ch["snippet"].get("description", ""),
        "subscribers": int(ch["statistics"].get("subscriberCount", 0)),
        "videos": int(ch["statistics"].get("videoCount", 0)),
        "views": int(ch["statistics"].get("viewCount", 0)),
        "keywords": (ch.get("brandingSettings", {}).get("channel", {})
                     .get("keywords", "")),
        "url": f"https://www.youtube.com/channel/{ch['id']}",
    }


def update_channel_branding(description: str | None = None,
                            keywords: list[str] | None = None) -> None:
    """Aplica descrição e palavras-chave do canal via API."""
    service = _get_service()
    ch = service.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
    branding = ch.get("brandingSettings", {})
    channel = branding.setdefault("channel", {})
    if description is not None:
        channel["description"] = description[:1000]
    if keywords is not None:
        # formato exigido: termos com espaço entre aspas, ≤500 chars
        joined = " ".join(f'"{k}"' if " " in k else k for k in keywords)
        channel["keywords"] = joined[:500]
    service.channels().update(part="brandingSettings",
                              body={"id": ch["id"],
                                    "brandingSettings": branding}).execute()


def set_channel_banner(image_path: Path) -> None:
    """Sobe e aplica o banner do canal (imagem 2560×1440)."""
    from googleapiclient.http import MediaFileUpload

    service = _get_service()
    res = service.channelBanners().insert(
        media_body=MediaFileUpload(str(image_path))).execute()
    url = res.get("url")
    if not url:
        raise RuntimeError("YouTube não retornou a URL do banner")
    ch = service.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
    branding = ch.get("brandingSettings", {})
    branding.setdefault("image", {})["bannerExternalUrl"] = url
    service.channels().update(part="brandingSettings",
                              body={"id": ch["id"],
                                    "brandingSettings": branding}).execute()
