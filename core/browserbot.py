"""Piloto de Navegador — gera imagens/vídeos nas ferramentas web do Google
(Whisk e Flow/Veo 3) usando a SUA conta logada, sem gastar créditos de API.

Como funciona:
  • abre um Chrome próprio do DarkStudio (perfil persistente em browser_profile/
    — você loga UMA vez na conta Google e fica logado);
  • WHISK  : digita cada prompt, clica gerar, captura a imagem gerada e salva
             direto na cena do projeto;
  • FLOW   : modo assistido — abre o Flow, deixa o prompt na área de
             transferência e vigia a pasta de downloads; você clica em gerar/
             baixar e o app importa o vídeo para a cena automaticamente.

EXPERIMENTAL: sites mudam de layout; se um passo automático falhar, o app avisa
e cai no modo assistido (você faz o clique, ele importa). Automatize com bom
senso — a conta é sua e os termos dos Labs valem para uso pessoal.
"""
from __future__ import annotations

import base64
import shutil
import time
from pathlib import Path

from .config import ROOT_DIR

PROFILE_DIR = ROOT_DIR / "browser_profile"
DOWNLOADS_DIR = ROOT_DIR / "browser_downloads"
WHISK_URL = "https://labs.google/fx/tools/whisk"
FLOW_URL = "https://labs.google/fx/tools/flow"

# JS: baixa a imagem de um <img> (mesmo blob:) e devolve dataURL
_IMG_TO_DATAURL = """
async (el) => {
  const r = await fetch(el.src);
  const b = await r.blob();
  return await new Promise(res => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.readAsDataURL(b);
  });
}
"""

# JS: baixa qualquer mídia por URL (blob:/https) e devolve dataURL
_MEDIA_TO_DATAURL = """
async (src) => {
  const r = await fetch(src);
  const b = await r.blob();
  return await new Promise(res => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.readAsDataURL(b);
  });
}
"""


class BotError(RuntimeError):
    pass


class BrowserBot:
    def __init__(self, headed: bool = True):
        self.headed = headed
        self._pw = None
        self.ctx = None
        self.page = None

    # ------------------------------------------------------------- ciclo
    def start(self):
        from playwright.sync_api import sync_playwright

        PROFILE_DIR.mkdir(exist_ok=True)
        DOWNLOADS_DIR.mkdir(exist_ok=True)
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=not self.headed,
            accept_downloads=True, viewport={"width": 1600, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def stop(self):
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
            self.ctx = self.page = self._pw = None

    # ------------------------------------------------------------ helpers
    def needs_login(self) -> bool:
        """Precisa logar? Só considera login pendente se estivermos na tela de
        contas do Google OU se houver um BOTÃO de login visível na página.
        (Checar só o texto 'sign in' dava falso positivo com o usuário já logado.)"""
        if "accounts.google.com" in self.page.url:
            return True
        for sel in ("a:has-text('Sign in')", "a:has-text('Fazer login')",
                    "button:has-text('Sign in')", "button:has-text('Fazer login')",
                    "a:has-text('Entrar')", "button:has-text('Entrar')"):
            try:
                loc = self.page.locator(sel).first
                if loc.count() and loc.is_visible():
                    return True
            except Exception:
                continue
        return False

    def goto(self, url: str, progress=None):
        if progress:
            progress(f"Abrindo {url.split('/')[-1]}…")
        self.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        self.page.wait_for_timeout(3000)

    def wait_login(self, progress=None, timeout_s: int = 300):
        """Se precisar de login, espera o usuário logar na janela aberta."""
        if not self.needs_login():
            return
        if progress:
            progress("Faça login na janela do navegador (aguardando até 5 min)…")
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            self.page.wait_for_timeout(3000)
            if "labs.google" in self.page.url and not self.needs_login():
                return
        raise BotError("Login não concluído a tempo — tente de novo")

    def _find_prompt_box(self):
        for sel in ("textarea", "[contenteditable='true']",
                    "input[type='text']", "[role='textbox']"):
            loc = self.page.locator(sel).first
            try:
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:
                continue
        raise BotError("Não achei o campo de prompt (layout mudou?)")

    def _snapshot_imgs(self) -> set[str]:
        try:
            return set(self.page.eval_on_selector_all(
                "img", "els => els.map(e => e.src).filter(s => s)"))
        except Exception:
            return set()

    # ------------------------------------------------------------- WHISK
    def whisk_generate(self, prompts: list[tuple[int, str]], save_scene, progress,
                       cancel=None) -> tuple[int, int]:
        """Gera cada prompt no Whisk e salva via save_scene(i, caminho_png).
        Retorna (ok, falhas). Em falha de automação, tenta importar o download
        manual mais recente antes de desistir da cena."""
        self.goto(WHISK_URL, progress)
        self.wait_login(progress)
        ok = fail = 0
        for k, (i, prompt) in enumerate(prompts, 1):
            if cancel and cancel():
                break
            progress(f"Whisk: cena {i + 1} ({k}/{len(prompts)})…")
            try:
                before = self._snapshot_imgs()
                box = self._find_prompt_box()
                box.click()
                self.page.keyboard.press("Control+A")
                self.page.keyboard.press("Delete")
                box.type(prompt[:1500], delay=4)
                self.page.keyboard.press("Enter")
                path = self._wait_new_image(before, timeout_s=210)
                save_scene(i, path)
                ok += 1
            except Exception as e:
                progress(f"cena {i + 1}: automação falhou ({str(e)[:60]}) — "
                         "baixe manualmente que eu importo")
                manual = self._wait_manual_download((".png", ".jpg", ".jpeg", ".webp"),
                                                    timeout_s=120)
                if manual:
                    save_scene(i, manual)
                    ok += 1
                else:
                    fail += 1
        return ok, fail

    def _wait_new_image(self, before: set[str], timeout_s: int = 210) -> Path:
        """Espera surgir uma imagem gerada nova e salva em arquivo temporário."""
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            self.page.wait_for_timeout(2500)
            now = self._snapshot_imgs()
            fresh = [s for s in now - before
                     if s.startswith(("blob:", "data:", "https"))
                     and "avatar" not in s and "logo" not in s]
            # pega a MAIOR imagem nova (miniaturas/ícones ficam de fora)
            best, best_area = None, 0
            for src in fresh:
                try:
                    el = self.page.locator(f'img[src="{src}"]').first
                    bb = el.bounding_box()
                    area = (bb["width"] * bb["height"]) if bb else 0
                    if area > best_area and area > 90_000:
                        best, best_area = el, area
                except Exception:
                    continue
            if best is not None:
                data_url = best.evaluate(_IMG_TO_DATAURL)
                raw = base64.b64decode(data_url.split(",", 1)[1])
                out = DOWNLOADS_DIR / f"whisk_{int(time.time() * 1000)}.png"
                out.write_bytes(raw)
                return out
        raise BotError("tempo esgotado esperando a imagem")

    # -------------------------------------------------------------- FLOW
    def flow_assist(self, scenes: list[tuple[int, Path, str]], save_clip, progress,
                    cancel=None) -> tuple[int, int]:
        """Modo assistido do Flow/Veo 3: para cada cena, copia o prompt para a
        área de transferência e espera você gerar/baixar; o download é
        importado automaticamente para a cena."""
        self.goto(FLOW_URL, progress)
        self.wait_login(progress)
        ok = fail = 0
        for k, (i, image, prompt) in enumerate(scenes, 1):
            if cancel and cancel():
                break
            try:
                self.page.evaluate("t => navigator.clipboard.writeText(t)", prompt[:1500])
            except Exception:
                pass
            progress(f"Flow cena {i + 1} ({k}/{len(scenes)}): prompt copiado (Ctrl+V). "
                     f"Envie a imagem da cena, gere e BAIXE o vídeo — eu importo. "
                     f"Imagem: {image.name}")
            clip = self._wait_manual_download((".mp4", ".webm", ".mov"), timeout_s=600,
                                              cancel=cancel)
            if clip:
                save_clip(i, clip)
                ok += 1
                progress(f"cena {i + 1} importada ✔")
            else:
                fail += 1
        return ok, fail

    def flow_auto(self, scenes: list[tuple[int, Path, str]], save_clip, progress,
                  cancel=None) -> tuple[int, int]:
        """Flow/Veo 3 automático: cria UM projeto, entra no modo Vídeo → Frames
        e, para cada cena, sobe a imagem de partida (frame inicial), escreve o
        prompt de movimento, clica em Criar, baixa o vídeo e segue — até terminar.

        Fluxo do Flow (mapeado): Novo projeto → chip de modelo → aba Vídeo →
        Frames → slot 'Inicial' (input[type=file]) → prompt → botão 'Criar'.

        Best-effort: o Flow muda de layout com frequência. Se um passo automático
        falhar numa cena, cai no assistido SÓ naquela (prompt copiado, espera seu
        download) e continua as demais, sem travar o lote.

        ATENÇÃO: consome créditos do seu plano Flow (não usa a API Gemini)."""
        self.goto(FLOW_URL, progress)
        self.wait_login(progress)
        progress("Flow: abrindo projeto…")
        self._flow_open_project()
        # orientação a partir da 1ª imagem (9:16 p/ retrato, senão 16:9)
        portrait = False
        try:
            from PIL import Image
            with Image.open(scenes[0][1]) as im:
                portrait = im.height > im.width
        except Exception:
            pass
        progress("Flow: selecionando modo Vídeo → Frames…")
        self._flow_enter_frames_mode(portrait=portrait)
        seen = self._snapshot_videos()
        ok = fail = 0
        n = len(scenes)
        for k, (i, image, prompt) in enumerate(scenes, 1):
            if cancel and cancel():
                break
            try:
                progress(f"Flow cena {i + 1} ({k}/{n}): enviando a imagem…")
                self._flow_set_initial_frame(image)
                self._flow_set_prompt(prompt)
                progress(f"Flow cena {i + 1} ({k}/{n}): gerando o vídeo "
                         "(usa créditos do Flow; ~1-3 min)…")
                self._flow_click_generate()
                clip = self._flow_grab_new_video(seen, timeout_s=600, cancel=cancel)
                seen = self._snapshot_videos()
                save_clip(i, clip)
                ok += 1
                progress(f"cena {i + 1} pronta ✔ ({k}/{n})")
            except Exception as e:
                # fallback assistido apenas para ESTA cena — não trava o resto
                progress(f"cena {i + 1}: automático falhou ({str(e)[:60]}). "
                         "Prompt copiado — gere/baixe manual que eu importo.")
                try:
                    self.page.evaluate("t => navigator.clipboard.writeText(t)",
                                       prompt[:1500])
                except Exception:
                    pass
                manual = self._wait_manual_download((".mp4", ".webm", ".mov"),
                                                    timeout_s=600, cancel=cancel)
                if manual:
                    save_clip(i, manual)
                    seen = self._snapshot_videos()
                    ok += 1
                    progress(f"cena {i + 1} importada ✔ ({k}/{n})")
                else:
                    fail += 1
        return ok, fail

    # ---------------------------------------------------- passos do Flow
    def _click_first(self, selectors: tuple[str, ...], optional: bool = False,
                     timeout: int = 4000) -> bool:
        """Clica no primeiro seletor que existir/estiver visível. Retorna True se
        clicou. Se optional, não levanta erro quando nenhum casa."""
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                loc.wait_for(state="visible", timeout=timeout)
                loc.click()
                return True
            except Exception:
                continue
        if optional:
            return False
        raise BotError(f"não achei o elemento: {selectors[0]}")

    def _flow_open_project(self) -> None:
        """Garante que estamos dentro de um projeto (URL /project/...)."""
        if "/project/" in (self.page.url or ""):
            return
        self._click_first(("button:has-text('Novo projeto')",
                           "button:has-text('New project')"), timeout=15_000)
        for _ in range(20):
            self.page.wait_for_timeout(800)
            if "/project/" in (self.page.url or ""):
                self.page.wait_for_timeout(2500)
                return
        raise BotError("não consegui abrir um projeto no Flow")

    # chips que só existem quando o modo Agente está DESLIGADO (rótulo varia)
    _CHIP_SELS = ("button:has-text('Vídeo ·')", "button:has-text('Nano Banana')",
                  "button:has-text('Omni')", "button:has-text('crop_16_9')",
                  "button:has-text('crop_9_16')")

    def _model_chip(self):
        for s in self._CHIP_SELS:
            loc = self.page.locator(s).first
            try:
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    def _flow_enter_frames_mode(self, portrait: bool = False) -> None:
        """Coloca a barra em Vídeo → Frames (imagem→vídeo).

        Sequência mapeada ao vivo: se o painel de chat do agente estiver aberto,
        fecha; clica o chip 'Agente' da barra (revela o chip de modelo); abre o
        popover pelo chip; escolhe Vídeo (play_circle) → Frames (crop_free) →
        aspecto (9:16 se retrato, senão 16:9) → 1 variante (1x)."""
        p = self.page
        # 1) fecha o chat do agente, se aberto (aí não há chip de modelo)
        if self._model_chip() is None:
            for s in ("button[aria-label='Fechar']", "button:has-text('close')"):
                try:
                    loc = p.locator(s).last
                    if loc.count() and loc.is_visible():
                        loc.click()
                        p.wait_for_timeout(700)
                        break
                except Exception:
                    continue
        # 2) clica o chip 'Agente' da barra p/ revelar o chip de modelo
        if self._model_chip() is None:
            try:
                p.get_by_role("button", name="Agente", exact=True).last.click()
                p.wait_for_timeout(900)
            except Exception:
                pass
        chip = self._model_chip()
        if chip is None:
            raise BotError("não achei o seletor de modo (Flow ficou em modo agente)")
        # 3) abre o popover e escolhe Vídeo → Frames → 1 variante
        chip.click()
        p.wait_for_timeout(900)
        self._click_first(("button:has-text('play_circle')",), optional=True, timeout=3000)
        p.wait_for_timeout(500)
        self._click_first(("button:has-text('crop_free')",), optional=True, timeout=3000)
        p.wait_for_timeout(500)
        # aspecto conforme a orientação (rótulo '9:16'/'16:9' — o chip usa
        # 'crop_16_9' com underscore, então não colide)
        self._click_first((f"button:has-text('{'9:16' if portrait else '16:9'}')",),
                          optional=True, timeout=1500)
        p.wait_for_timeout(300)
        self._click_first(("button:has-text('1x')",), optional=True, timeout=1500)
        p.wait_for_timeout(400)
        try:
            p.keyboard.press("Escape")
        except Exception:
            pass
        p.wait_for_timeout(500)

    def _flow_set_initial_frame(self, image: Path) -> None:
        """Anexa a imagem ao frame 'Inicial'. Fluxo mapeado: clicar no slot abre
        um seletor de mídia; 'Enviar mídia' faz upload e já pré-seleciona a
        imagem; então é PRECISO clicar 'Incluir no comando' p/ prendê-la ao
        frame (sem isso o Veo gera do zero, ignorando a imagem)."""
        p = self.page
        p.locator(":text-is('Inicial')").first.click()
        p.wait_for_timeout(900)
        sent = False
        for name in ("Enviar mídia", "Upload", "Fazer upload", "Enviar", "Carregar"):
            try:
                with p.expect_file_chooser(timeout=3500) as fc:
                    p.get_by_role("button", name=name).first.click()
                fc.value.set_files(str(image))
                sent = True
                break
            except Exception:
                continue
        if not sent:
            raise BotError("não consegui enviar a imagem no frame Inicial")
        p.wait_for_timeout(4500)   # espera upload + preview
        # ANEXA ao frame (passo que faltava → image-to-video de verdade)
        if not self._click_first(("button:has-text('Incluir no comando')",
                                  "button:has-text('Incluir')",
                                  "button:has-text('Add to prompt')",
                                  "button:has-text('Include')"),
                                 optional=True, timeout=8000):
            raise BotError("não achei 'Incluir no comando' p/ anexar o frame")
        p.wait_for_timeout(2500)

    def _flow_set_prompt(self, prompt: str) -> None:
        box = self._find_prompt_box()
        box.click()
        try:
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Delete")
        except Exception:
            pass
        box.type(prompt[:1500], delay=3)
        self.page.wait_for_timeout(400)

    def _flow_click_generate(self) -> None:
        # o botão de gerar é o 'arrow_forward' (Criar) — 'add_2 Criar' é outro
        if not self._click_first(("button:has-text('arrow_forward')",),
                                 optional=True, timeout=3000):
            self.page.keyboard.press("Enter")   # fallback

    def _snapshot_videos(self) -> set[str]:
        try:
            return set(self.page.evaluate(
                "() => Array.from(document.querySelectorAll('video'))"
                ".map(v => v.currentSrc || v.src).filter(Boolean)"))
        except Exception:
            return set()

    def _flow_grab_new_video(self, seen: set[str], timeout_s: int = 600,
                             cancel=None) -> Path:
        """Espera surgir um <video> NOVO (não visto antes) e o salva. Tenta
        também capturar um download disparado (botão baixar do Flow)."""
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if cancel and cancel():
                raise BotError("cancelado")
            # 1) o Flow disparou download?
            try:
                dl = self.page.wait_for_event("download", timeout=2500)
                out = DOWNLOADS_DIR / (dl.suggested_filename or
                                       f"flow_{int(time.time() * 1000)}.mp4")
                dl.save_as(str(out))
                if out.suffix.lower() in (".mp4", ".webm", ".mov"):
                    return out
            except Exception:
                pass
            # 2) surgiu um <video> novo pronto? captura o blob direto
            fresh = [s for s in self._snapshot_videos() - seen
                     if s.startswith(("blob:", "http", "data:"))]
            for src in fresh:
                try:
                    data_url = self.page.evaluate(_MEDIA_TO_DATAURL, src)
                    raw = base64.b64decode(data_url.split(",", 1)[1])
                    if len(raw) < 50_000:      # ainda é placeholder/miniatura
                        continue
                    out = DOWNLOADS_DIR / f"flow_{int(time.time() * 1000)}.mp4"
                    out.write_bytes(raw)
                    return out
                except Exception:
                    continue
        raise BotError("tempo esgotado esperando o vídeo")

    # ------------------------------------------------- downloads manuais
    def _wait_manual_download(self, exts: tuple[str, ...], timeout_s: int,
                              cancel=None) -> Path | None:
        """Vigia a pasta de downloads do navegador do bot E a do Windows."""
        watch = [DOWNLOADS_DIR, Path.home() / "Downloads"]
        t0 = time.time()
        seen = {f: f.stat().st_mtime for d in watch if d.exists()
                for f in d.glob("*") if f.suffix.lower() in exts}
        while time.time() - t0 < timeout_s:
            if cancel and cancel():
                return None
            try:
                dl = self.page.wait_for_event("download", timeout=2500)
                out = DOWNLOADS_DIR / dl.suggested_filename
                dl.save_as(str(out))
                if out.suffix.lower() in exts:
                    return out
            except Exception:
                pass
            for d in watch:
                if not d.exists():
                    continue
                for f in sorted(d.glob("*"), key=lambda p: p.stat().st_mtime,
                                reverse=True):
                    if (f.suffix.lower() in exts and f.stat().st_mtime > t0 - 2
                            and f not in seen and not f.name.endswith(".crdownload")):
                        time.sleep(1.5)  # espera terminar de gravar
                        return f
        return None


def available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False
