"""Design system do DarkStudio — visual de estúdio profissional.

Identidade: superfícies quase-pretas, bordas hairline, um único acento
(vermelho-sinal, a "luz de REC"), tipografia Inter, ícones Material.
"""
from contextlib import contextmanager

from nicegui import ui

ACCENT = "#e5484d"

CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#0b0c0f; --bg-side:#0f1115; --card:#14161c; --card2:#191c24; --hover:#1b1f28;
  --border:#262a34; --border-soft:#1e222b;
  --tx:#e9ebf1; --tx2:#9aa2b1; --tx3:#636b7b;
  --acc:#e5484d; --acc-h:#f2555a; --acc-soft:rgba(229,72,77,.13);
  --ok:#3dd68c; --warn:#f5a524; --info:#4f8cff;
  --font:'Inter','Segoe UI Variable Text','Segoe UI',system-ui,sans-serif;
  --mono:'JetBrains Mono',Consolas,monospace;
}
html, body { background:var(--bg)!important; color:var(--tx); font-family:var(--font); font-size:14px; }
.q-page, .q-layout { background:var(--bg)!important; }
.nicegui-content { padding:0; }
* { outline-color:var(--acc); }
::selection { background:var(--acc-soft); }
::-webkit-scrollbar { width:10px; height:10px; }
::-webkit-scrollbar-thumb { background:#2a2f3a; border-radius:6px; border:2px solid var(--bg); }
::-webkit-scrollbar-track { background:transparent; }

/* ---------------- app bar ---------------- */
.appbar {
  background:var(--bg-side)!important; border-bottom:1px solid var(--border-soft);
  height:54px; padding:0 18px!important; display:flex; align-items:center;
}
.logo-dot { width:10px; height:10px; border-radius:50%; background:var(--acc);
  box-shadow:0 0 10px rgba(229,72,77,.8); }
.wordmark { font-weight:800; letter-spacing:.22em; font-size:13px; color:var(--tx); }
.wordmark b { color:var(--acc); }
.appbar .q-field .q-field__control { background:var(--card); }

/* ---------------- sidebar ---------------- */
.side { background:var(--bg-side)!important; border-right:1px solid var(--border-soft); }
.eyebrow { font-size:11px; font-weight:700; letter-spacing:.18em; color:var(--tx3);
  text-transform:uppercase; }
.stepper { position:relative; }
.stepper::before { content:''; position:absolute; left:17px; top:20px; bottom:20px;
  width:2px; background:var(--border-soft); }
.stp { position:relative; display:flex; flex-direction:column; justify-content:center;
  min-height:52px; padding:6px 10px 6px 44px; border-radius:10px; cursor:pointer;
  transition:background .12s ease; }
.stp:hover { background:var(--hover); }
.stp .dot { position:absolute; left:4px; top:50%; transform:translateY(-50%);
  width:28px; height:28px; border-radius:50%; display:flex; align-items:center;
  justify-content:center; font-size:12px; font-weight:700; font-family:var(--mono);
  background:var(--card2); border:1px solid var(--border); color:var(--tx3); z-index:1; }
.stp .t { font-size:13.5px; font-weight:600; color:var(--tx2); line-height:1.2; }
.stp .c { font-size:11.5px; color:var(--tx3); margin-top:1px; }
.stp.cur { background:var(--acc-soft); }
.stp.cur .t { color:var(--tx); }
.stp.cur .dot { border-color:var(--acc); color:var(--acc); }
.stp.ok .dot { background:rgba(61,214,140,.12); border-color:rgba(61,214,140,.4); color:var(--ok); }
.stp.lock { opacity:.42; cursor:default; }
.stp.lock:hover { background:transparent; }

/* ---------------- cards / seções ---------------- */
.card { background:var(--card); border:1px solid var(--border-soft); border-radius:14px;
  padding:20px 22px; width:100%; }
.card-h { font-size:12px; font-weight:700; letter-spacing:.14em; text-transform:uppercase;
  color:var(--tx3); }
.h-title { font-size:24px; font-weight:750; letter-spacing:-.02em; color:var(--tx); }
.h-sub { font-size:13.5px; color:var(--tx2); }
.mut { color:var(--tx2); } .mut2 { color:var(--tx3); }
.mono { font-family:var(--mono); }

/* ---------------- botões ---------------- */
.q-btn { border-radius:9px; font-family:var(--font); }
.btn-p { background:var(--acc)!important; color:#fff!important; font-weight:650;
  padding:0 18px; transition:background .12s ease, box-shadow .12s ease; }
.btn-p:hover { background:var(--acc-h)!important; box-shadow:0 4px 18px rgba(229,72,77,.35); }
.btn-g { background:var(--card2)!important; color:var(--tx)!important;
  border:1px solid var(--border)!important; font-weight:550; padding:0 16px; }
.btn-g:hover { background:var(--hover)!important; }
.ibtn { color:var(--tx2)!important; }
.ibtn:hover { color:var(--tx)!important; }

/* ---------------- pills de status ---------------- */
.pill { display:inline-flex; align-items:center; gap:6px; padding:3px 10px;
  border-radius:999px; font-size:11.5px; font-weight:600; white-space:nowrap; }
.pill i { width:6px; height:6px; border-radius:50%; display:inline-block; }
.pill.ok   { background:rgba(61,214,140,.1);  color:var(--ok);   border:1px solid rgba(61,214,140,.3); }
.pill.ok i { background:var(--ok); }
.pill.warn { background:rgba(245,165,36,.1);  color:var(--warn); border:1px solid rgba(245,165,36,.3); }
.pill.warn i { background:var(--warn); }
.pill.off  { background:var(--card2); color:var(--tx3); border:1px solid var(--border); }
.pill.off i { background:var(--tx3); }
.pill.acc  { background:var(--acc-soft); color:var(--acc); border:1px solid rgba(229,72,77,.35); }
.pill.acc i { background:var(--acc); }

/* ---------------- inputs quasar ---------------- */
.q-field--outlined .q-field__control { border-radius:9px; background:var(--card2); }
.q-field--outlined .q-field__control:before { border-color:var(--border); }
.q-field--outlined:hover .q-field__control:before { border-color:#333947; }
.q-field--focused .q-field__control:after { border-color:var(--acc)!important; }
.q-field__label, .q-field__native, .q-field__input { color:var(--tx2); font-family:var(--font); }
.q-field__native, .q-field__input { color:var(--tx); }
.q-menu { background:var(--card2); border:1px solid var(--border); border-radius:10px; }
textarea.q-field__native { line-height:1.55; }

/* ---------------- grade de estilos ---------------- */
.style-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(196px,1fr));
  gap:12px; width:100%; }
.stylecard { position:relative; background:var(--card2); border:1px solid var(--border-soft);
  border-radius:12px; overflow:hidden; cursor:pointer;
  transition:transform .14s ease, border-color .14s ease, box-shadow .14s ease; }
.stylecard:hover { transform:translateY(-2px); border-color:#39404e; }
.stylecard.sel { border-color:var(--acc); box-shadow:0 0 0 1px var(--acc), 0 8px 26px rgba(0,0,0,.45); }
.stylecard .thumb { aspect-ratio:16/9; display:block; width:100%; }
.stylecard .thumb svg { width:100%; height:100%; display:block; }
.stylecard .meta { padding:10px 12px 11px; }
.stylecard .meta .n { font-size:13px; font-weight:650; color:var(--tx); }
.stylecard .meta .d { font-size:11.5px; color:var(--tx3); margin-top:2px; line-height:1.35; }
.stylecard .selpin { position:absolute; top:8px; right:8px; width:22px; height:22px;
  border-radius:50%; background:var(--acc); color:#fff; display:flex; align-items:center;
  justify-content:center; font-size:13px; box-shadow:0 2px 8px rgba(0,0,0,.4); }

/* ---------------- grade de imagens ---------------- */
.img-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(224px,1fr));
  gap:12px; width:100%; }
.imgcard { position:relative; background:var(--card2); border:1px solid var(--border-soft);
  border-radius:12px; overflow:hidden; }
.imgcard img { width:100%; aspect-ratio:16/9; object-fit:cover; display:block; cursor:zoom-in; }
.imgcard .idx { position:absolute; top:8px; left:8px; background:rgba(8,9,12,.78);
  color:var(--tx2); padding:1px 8px; border-radius:6px; font-size:11px; font-weight:600;
  font-family:var(--mono); backdrop-filter:blur(4px); }
.imgcard .acts { position:absolute; top:6px; right:6px; opacity:0; transition:opacity .12s ease; }
.imgcard:hover .acts { opacity:1; }
.img-skel { width:100%; aspect-ratio:16/9; display:flex; align-items:center; justify-content:center;
  color:var(--tx3); font-size:12px; background:
  repeating-linear-gradient(-45deg, var(--card2), var(--card2) 14px, #1b1e26 14px, #1b1e26 28px); }

/* ---------------- linhas de sincronização ---------------- */
.syncrow { display:flex; align-items:center; gap:12px; padding:8px 6px;
  border-bottom:1px solid var(--border-soft); }
.syncrow:last-child { border-bottom:none; }
.tchip { font-family:var(--mono); font-size:11px; color:var(--tx2); background:var(--card2);
  border:1px solid var(--border-soft); padding:2px 7px; border-radius:6px; white-space:nowrap; }
.durbar { height:4px; border-radius:2px; background:var(--acc); opacity:.55; min-width:4px; }

/* ---------------- preview karaokê ---------------- */
.kprev { background:#000; border-radius:10px; aspect-ratio:16/6; display:flex;
  align-items:flex-end; justify-content:center; padding:18px; overflow:hidden;
  border:1px solid var(--border-soft); }
.kprev .line { text-align:center; font-weight:800; line-height:1.25;
  text-shadow:0 2px 4px #000, 0 0 6px #000, 2px 0 4px #000, -2px 0 4px #000; }

/* ---------------- barra de progresso global ---------------- */
.jobbar { position:fixed; top:54px; left:0; right:0; z-index:2000; }
.jobcard { background:var(--card); border:1px solid var(--border-soft); border-radius:12px; }

/* footer wizard */
.wfooter { border-top:1px solid var(--border-soft); background:rgba(11,12,15,.88);
  backdrop-filter:blur(10px); }
.q-notification { font-family:var(--font); }
</style>
"""

# ------------------------------------------------------------------ thumbs
# Miniaturas SVG desenhadas à mão — uma vinheta por estilo visual.
STYLE_THUMBS: dict[str, str] = {
    "doodle": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#f7f7f4"/><g stroke="#1c1c1c" stroke-width="2.2" fill="none" stroke-linecap="round"><circle cx="60" cy="30" r="9"/><path d="M60 39v19M60 45l-12 8M60 45l13 6M60 58l-9 15M60 58l10 14"/><path d="M20 22c4-7 11-7 14 0"/><circle cx="124" cy="21" r="8"/><path d="M124 8v5M124 29v5M111 21h5M132 21h5M115 12l3 3M133 12l-3 3"/><path d="M96 64c10-3 20-2 28 2" stroke="#d43b3b"/></g></svg>""",
    "storybook": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="sb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b1b3d"/><stop offset=".55" stop-color="#a84e38"/><stop offset="1" stop-color="#e8a04c"/></linearGradient></defs><rect width="160" height="90" fill="url(#sb)"/><circle cx="112" cy="50" r="13" fill="#ffd9a0"/><circle cx="112" cy="50" r="20" fill="#ffd9a0" opacity=".25"/><path d="M0 68q40-16 82-6t78 4v24H0z" fill="#1d1230"/><path d="M36 68c0-11 5-18 5-18s5 7 5 18" fill="#120a1e"/><circle cx="28" cy="18" r="1.4" fill="#fff" opacity=".8"/><circle cx="48" cy="10" r="1" fill="#fff" opacity=".6"/><circle cx="14" cy="34" r="1.2" fill="#fff" opacity=".7"/></svg>""",
    "pixar3d": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="px" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7fc1ff"/><stop offset="1" stop-color="#dff0ff"/></linearGradient></defs><rect width="160" height="90" fill="url(#px)"/><ellipse cx="80" cy="84" rx="44" ry="8" fill="#8fb1d6" opacity=".5"/><path d="M56 80c-5-27 6-46 24-46s29 19 24 46z" fill="#ffb84d"/><path d="M56 80c-5-27 6-46 24-46 4 0 8 1 11 3-14 4-22 20-19 43z" fill="#f09a2e"/><circle cx="72" cy="52" r="7" fill="#fff"/><circle cx="93" cy="52" r="7" fill="#fff"/><circle cx="73.5" cy="53" r="3.4" fill="#22354e"/><circle cx="91.5" cy="53" r="3.4" fill="#22354e"/><circle cx="74.8" cy="51.4" r="1.2" fill="#fff"/><circle cx="92.8" cy="51.4" r="1.2" fill="#fff"/><path d="M76 66q6 5 13 0" stroke="#8a4b12" stroke-width="2.4" fill="none" stroke-linecap="round"/></svg>""",
    "cinematic": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="cn" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#12333d"/><stop offset="1" stop-color="#3a2115"/></linearGradient></defs><rect width="160" height="90" fill="#000"/><rect y="12" width="160" height="66" fill="url(#cn)"/><circle cx="116" cy="36" r="13" fill="#ff9d45" opacity=".9"/><circle cx="116" cy="36" r="24" fill="#ff9d45" opacity=".15"/><path d="M0 78l50-28 26 14 28-18 56 32z" fill="#04070a"/><rect x="12" y="22" width="24" height="1.6" fill="#7fd6e8" opacity=".55"/><rect x="12" y="27" width="14" height="1.6" fill="#7fd6e8" opacity=".3"/></svg>""",
    "anime": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="an" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2c1f63"/><stop offset="1" stop-color="#c2427e"/></linearGradient></defs><rect width="160" height="90" fill="url(#an)"/><g stroke="#ffffff" opacity=".35" stroke-width="1.4"><path d="M116 8l38 24M108 2l50 34M124 16l30 18"/></g><path d="M28 48q28-24 56 0-28 24-56 0z" fill="#fff"/><circle cx="56" cy="48" r="10.5" fill="#5aa7e8"/><circle cx="56" cy="48" r="4.8" fill="#161628"/><circle cx="59.5" cy="43.5" r="2.6" fill="#fff"/><path d="M30 38q26-16 52 0" stroke="#161628" stroke-width="3" fill="none" stroke-linecap="round"/></svg>""",
    "watercolor": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#f6f2e9"/><ellipse cx="50" cy="38" rx="34" ry="24" fill="#4f9fbf" opacity=".42"/><ellipse cx="92" cy="52" rx="38" ry="26" fill="#b45f8e" opacity=".34"/><ellipse cx="120" cy="28" rx="24" ry="17" fill="#e0a13e" opacity=".38"/><ellipse cx="70" cy="60" rx="20" ry="12" fill="#3d6b52" opacity=".3"/><path d="M18 76q62 8 124-6" stroke="#3d6b52" stroke-width="3" fill="none" opacity=".45" stroke-linecap="round"/></svg>""",
    "flat": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#10324a"/><circle cx="118" cy="26" r="15" fill="#f2b134"/><rect x="18" y="46" width="50" height="30" rx="4" fill="#e34f4f"/><path d="M82 76l22-34 22 34z" fill="#3ec6a8"/><rect x="18" y="18" width="30" height="9" rx="4.5" fill="#e9e4d8"/><rect x="54" y="18" width="9" height="9" rx="4.5" fill="#e9e4d8" opacity=".55"/></svg>""",
    "comic": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#1c2f6e"/><path d="M80 12l9 20 22-14-8 23 25 2-21 13 15 18-24-7-2 23-14-19-16 17 3-24-24 3 19-15-17-14 24 3z" fill="#ffd23f" stroke="#111" stroke-width="3"/><g fill="#e34f4f"><circle cx="22" cy="18" r="3"/><circle cx="34" cy="26" r="3"/><circle cx="22" cy="34" r="3"/><circle cx="138" cy="66" r="3"/><circle cx="146" cy="76" r="3"/></g></svg>""",
    "noir": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#0a0a0a"/><g fill="#e8e8e8" opacity=".85"><path d="M20 8h10v74H20zM44 8h10v74H44zM68 8h10v74H68zM92 8h10v74H92zM116 8h10v74h-10z" transform="skewX(-12)"/></g><path d="M96 50c0-9 7-14 15-14s15 5 15 14v32H96z" fill="#000"/><ellipse cx="111" cy="36" rx="17" ry="5" fill="#000"/></svg>""",
    "cyberpunk": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#0d0221"/><g fill="#1a0b3b"><rect x="10" y="30" width="22" height="60"/><rect x="40" y="18" width="26" height="72"/><rect x="74" y="36" width="20" height="54"/><rect x="102" y="12" width="30" height="78"/><rect x="138" y="42" width="16" height="48"/></g><g stroke="#ff2ec4" stroke-width="2"><path d="M40 18h26M102 12h30"/><rect x="108" y="24" width="6" height="8" fill="#ff2ec4"/></g><g stroke="#00f0ff" stroke-width="2"><path d="M10 30h22M74 36h20"/><rect x="48" y="34" width="6" height="10" fill="#00f0ff"/></g><path d="M0 90h160" stroke="#ff2ec4" stroke-width="3"/></svg>""",
    "oil": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#2b1214"/><g stroke-linecap="round"><path d="M14 70q30-26 60-16" stroke="#7d2c33" stroke-width="12" fill="none"/><path d="M40 56q36-22 72-8" stroke="#a8434b" stroke-width="10" fill="none"/><path d="M70 40q30-14 58-2" stroke="#d9a05b" stroke-width="8" fill="none"/></g><circle cx="118" cy="30" r="12" fill="#e8c268" opacity=".9"/><path d="M0 0h160v6H0zM0 84h160v6H0z" fill="#8a6a2f"/></svg>""",
    "sketch": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#f2efe9"/><g stroke="#4a4a4a" fill="none" stroke-width="1.6"><circle cx="70" cy="40" r="22"/><path d="M52 60q18 12 36 0M48 36q8-14 22-12M60 84q20-14 60-10"/><path d="M96 22l26 26M100 18l26 26M104 14l26 26" opacity=".5"/></g><path d="M118 66l22-22 6 6-22 22-8 2z" fill="#c9a86a"/></svg>""",
    "vintage": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#d9c39a"/><rect x="12" y="10" width="136" height="70" fill="#b89968"/><rect x="18" y="16" width="124" height="58" fill="#8a6f45"/><circle cx="60" cy="40" r="12" fill="#d9c39a" opacity=".8"/><path d="M18 74l30-24 22 16 26-20 46 28z" fill="#6d5433"/><path d="M34 16v58M118 16v58" stroke="#d9c39a" opacity=".3" stroke-width="2"/></svg>""",
    "dark_fantasy": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#0e0b16"/><circle cx="116" cy="26" r="16" fill="#b3202e"/><circle cx="116" cy="26" r="24" fill="#b3202e" opacity=".2"/><path d="M28 90V48l8-8v-10l6 6 6-6v10l8 8v14h10V40l10-10 10 10v50z" fill="#05030a"/><path d="M0 90l40-8 44 6 40-10 36 8v4H0z" fill="#161022"/><g fill="#e8e8f0" opacity=".7"><circle cx="20" cy="14" r="1.2"/><circle cx="58" cy="8" r="1"/><circle cx="86" cy="18" r="1.4"/></g></svg>""",
    "pixel": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges"><rect width="160" height="90" fill="#1b2d5c"/><rect x="120" y="12" width="16" height="16" fill="#ffe08a"/><g fill="#2e8f5b"><rect x="0" y="66" width="160" height="24"/><rect x="24" y="58" width="8" height="8"/><rect x="32" y="50" width="8" height="16"/><rect x="40" y="58" width="8" height="8"/></g><g fill="#3fae72"><rect x="88" y="54" width="8" height="12"/><rect x="96" y="46" width="8" height="20"/><rect x="104" y="54" width="8" height="12"/></g><rect x="64" y="34" width="8" height="8" fill="#e8e8f0"/><rect x="72" y="42" width="8" height="8" fill="#e8e8f0" opacity=".6"/></svg>""",
    "lowpoly": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#17263b"/><path d="M0 78l44-42 30 26 26-34 60 50v12H0z" fill="#2c4a6e"/><path d="M44 36l30 26-38 16z" fill="#3d6491"/><path d="M100 28l26 34-40 16z" fill="#4d7cb0"/><path d="M100 28l14 18-24 14z" fill="#6b9ac9"/><circle cx="120" cy="16" r="9" fill="#ffd97a"/></svg>""",
    "claymation": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#b8d8d0"/><ellipse cx="80" cy="80" rx="42" ry="7" fill="#93b8ae"/><path d="M56 76c-5-22 4-40 24-40s29 18 24 40q-24 8-48 0z" fill="#e8875a"/><circle cx="70" cy="52" r="6.5" fill="#fff"/><circle cx="91" cy="52" r="6.5" fill="#fff"/><circle cx="71.5" cy="53.5" r="3" fill="#33261f"/><circle cx="89.5" cy="53.5" r="3" fill="#33261f"/><path d="M74 65q7 6 14 0" stroke="#8a4b2a" stroke-width="2.6" fill="none" stroke-linecap="round"/><path d="M62 42q-3-8 4-12M98 42q3-8-4-12" stroke="#d0764b" stroke-width="4" fill="none" stroke-linecap="round"/></svg>""",
    "papercut": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#f4e9d8"/><path d="M0 26q40 14 80 2t80 4v58H0z" fill="#e8b04b"/><path d="M0 26q40 14 80 2t80 4v4q-40-6-80-2t-80-2z" fill="#000" opacity=".12"/><path d="M0 46q40 12 80 0t80 6v38H0z" fill="#d96c4f"/><path d="M0 46q40 12 80 0t80 6v4q-40-8-80-4t-80-2z" fill="#000" opacity=".14"/><path d="M0 66q40 10 80 2t80 2v20H0z" fill="#7a3b52"/><circle cx="120" cy="20" r="10" fill="#fff" opacity=".85"/></svg>""",
    "isometric": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#22273a"/><g><path d="M80 18l30 17-30 17-30-17z" fill="#8fb7e8"/><path d="M50 35v22l30 17V52z" fill="#5d86b8"/><path d="M110 35v22l-30 17V52z" fill="#40628c"/></g><g transform="translate(-34,18)"><path d="M80 30l20 11-20 11-20-11z" fill="#e8a05a"/><path d="M60 41v14l20 11V52z" fill="#b8763d"/><path d="M100 41v14l-20 11V52z" fill="#8a5527"/></g><g transform="translate(34,22)"><path d="M80 30l18 10-18 10-18-10z" fill="#7ac98f"/><path d="M62 40v12l18 10V50z" fill="#529464"/><path d="M98 40v12l-18 10V50z" fill="#3a6d49"/></g></svg>""",
    "ghibli": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="gh" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#add8e6"/><stop offset="1" stop-color="#e8f4d9"/></linearGradient></defs><rect width="160" height="90" fill="url(#gh)"/><ellipse cx="40" cy="20" rx="20" ry="9" fill="#fff" opacity=".9"/><ellipse cx="120" cy="14" rx="16" ry="7" fill="#fff" opacity=".8"/><path d="M0 68q40-12 80-4t80 2v24H0z" fill="#7cb342"/><path d="M0 76q50-8 90 0t70-2v16H0z" fill="#5a9e3a"/><path d="M112 68c0-16 6-24 6-24s6 8 6 24" fill="#3d7a28"/><circle cx="118" cy="42" r="4" fill="#f0e68c"/></svg>""",
    "cel_shaded": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#ff7043"/><path d="M0 0h80v90H0z" fill="#ffa726"/><g stroke="#1a1a2e" stroke-width="2.4"><path d="M32 46q28-26 56 0-28 24-56 0z" fill="#fff"/><circle cx="60" cy="46" r="11" fill="#29b6f6"/><circle cx="60" cy="46" r="5" fill="#1a1a2e"/></g><circle cx="63" cy="42" r="3" fill="#fff"/><path d="M34 34q26-16 52 0" stroke="#1a1a2e" stroke-width="3.4" fill="none" stroke-linecap="round"/><path d="M96 20l14 8-14 8z" fill="#1a1a2e"/></svg>""",
    "felt": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#c9e4d8"/><ellipse cx="80" cy="80" rx="40" ry="7" fill="#a8ccc0"/><ellipse cx="80" cy="52" rx="30" ry="30" fill="#f2a5a5"/><ellipse cx="80" cy="52" rx="30" ry="30" fill="none" stroke="#e08a8a" stroke-width="2" stroke-dasharray="3 3"/><circle cx="69" cy="48" r="5.5" fill="#fff"/><circle cx="91" cy="48" r="5.5" fill="#fff"/><circle cx="69" cy="49" r="2.6" fill="#3a2a2a"/><circle cx="91" cy="49" r="2.6" fill="#3a2a2a"/><circle cx="62" cy="58" r="4" fill="#f7bcbc"/><circle cx="98" cy="58" r="4" fill="#f7bcbc"/><path d="M74 60q6 5 12 0" stroke="#8a4a4a" stroke-width="2.4" fill="none" stroke-linecap="round"/></svg>""",
    "analog_horror": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#0a140d"/><rect width="160" height="90" fill="#1a3320" opacity=".5"/><g opacity=".5"><rect y="10" width="160" height="1.5" fill="#7fffb0"/><rect y="26" width="160" height="1" fill="#7fffb0"/><rect y="44" width="160" height="1.5" fill="#ff5b5b"/><rect y="62" width="160" height="1" fill="#7fffb0"/><rect y="78" width="160" height="1.5" fill="#7fffb0"/></g><ellipse cx="80" cy="44" rx="20" ry="26" fill="#0d1f13"/><circle cx="72" cy="40" r="3.5" fill="#c8ffdb"/><circle cx="88" cy="40" r="3.5" fill="#c8ffdb"/><path d="M70 56q10 6 20 0" stroke="#0a140d" stroke-width="3" fill="none"/><rect x="12" y="12" width="30" height="8" fill="#c8ffdb" opacity=".25"/></svg>""",
    "retro_anime": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="ra" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c98a9e"/><stop offset="1" stop-color="#6b5a8a"/></linearGradient></defs><rect width="160" height="90" fill="url(#ra)"/><rect width="160" height="90" fill="#000" opacity=".08"/><circle cx="118" cy="26" r="14" fill="#e8b8a0" opacity=".85"/><g stroke="#2a2038" stroke-width="2"><path d="M40 48q22-22 44 0-22 20-44 0z" fill="#f0dcc8"/><circle cx="62" cy="46" r="9" fill="#a85a6e"/></g><circle cx="64" cy="43" r="2.4" fill="#fff"/><path d="M38 38q24-14 48 0" stroke="#2a2038" stroke-width="3" fill="none" stroke-linecap="round"/><g fill="#fff" opacity=".15"><rect y="20" width="160" height="1"/><rect y="55" width="160" height="1"/></g></svg>""",
    "custom": """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#171922"/><path d="M62 62l28-28 9 9-28 28-12 3z" fill="#cfd4e2"/><path d="M92 32l9 9 6-6-9-9z" fill="#8b93a9"/><g fill="#e8c268"><path d="M40 22l2.6 6.2 6.2 2.6-6.2 2.6-2.6 6.2-2.6-6.2-6.2-2.6 6.2-2.6z"/><path d="M118 60l2 4.6 4.6 2-4.6 2-2 4.6-2-4.6-4.6-2 4.6-2z"/><circle cx="104" cy="18" r="2" opacity=".7"/></g></svg>""",
}

DEFAULT_THUMB = """<svg viewBox="0 0 160 90" xmlns="http://www.w3.org/2000/svg"><rect width="160" height="90" fill="#1a1d26"/><circle cx="80" cy="40" r="16" fill="#2c3140"/><path d="M30 78l34-26 24 18 20-14 22 22z" fill="#2c3140"/></svg>"""


def apply() -> None:
    ui.add_head_html(CSS)
    ui.colors(primary=ACCENT, secondary="#4f8cff", positive="#3dd68c",
              negative="#e5484d", warning="#f5a524", dark="#14161c")


# ------------------------------------------------------------- componentes
@contextmanager
def card(title: str | None = None):
    with ui.column().classes("card gap-3") as col:
        if title:
            ui.label(title).classes("card-h")
        yield col


def pill(text: str, kind: str = "off"):
    ui.html(f'<span class="pill {kind}"><i></i>{text}</span>')


def page_header(title: str, subtitle: str, trailing=None):
    with ui.row().classes("w-full items-end justify-between no-wrap"):
        with ui.column().classes("gap-1"):
            ui.label(title).classes("h-title")
            ui.label(subtitle).classes("h-sub")
        if trailing:
            trailing()


def primary_btn(label: str, on_click, icon: str | None = None) -> ui.button:
    b = ui.button(label, on_click=on_click)
    b.props("unelevated no-caps" + (f" icon={icon}" if icon else "")).classes("btn-p")
    return b


def ghost_btn(label: str, on_click, icon: str | None = None) -> ui.button:
    b = ui.button(label, on_click=on_click)
    b.props("unelevated no-caps" + (f" icon={icon}" if icon else "")).classes("btn-g")
    return b


def icon_btn(icon: str, on_click, tooltip: str | None = None) -> ui.button:
    b = ui.button(icon=icon, on_click=on_click).props("flat round dense").classes("ibtn")
    if tooltip:
        with b:
            ui.tooltip(tooltip)
    return b
