import base64
import contextlib
import hmac
import io
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

import altair as alt
import boto3
import pandas as pd
import streamlit as st
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# ---------- AWS Step Functions ----------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
STATE_MACHINE_ARN = os.environ.get(
    "STATE_MACHINE_ARN",
    "arn:aws:states:us-east-2:906513713169:stateMachine:t1-farmazids-05",
)
# "EXPRESS", "STANDARD" ou "AUTO" (detecta sozinho; exige states:DescribeStateMachine)
STATE_MACHINE_TYPE = os.environ.get("STATE_MACHINE_TYPE", "EXPRESS").upper()
EXECUTION_TIMEOUT_S = 60  # tempo máximo de espera (só para workflows Standard)

# ---------- Configuração ----------
BOT_NAME = "Zids"  # a única palavra verde do título
TAG = "Assistente de preços Farmazids"
SUBHEAD = "Pergunte sobre preços dos concorrentes e vendas da Farmazids em linguagem natural."
BUBBLES = ["Olá, eu sou o Zids.", "O que você quer saber sobre preços?"]
# Substitua pelos seus números reais
STATS = [
    ("Medicamentos", "10.000+", "no banco de dados"),
    ("Tempo de resposta", "6 s", "em média por pergunta"),
    ("Extração completa", "17", "campos por medicamento (15 na VeraCruz)"),
]
SUGGESTIONS = [
    "Qual o preço médio da dipirona na FarmaPonte?",
    "Onde a dipirona está mais barata entre os concorrentes?",
    "Quais os 5 produtos mais vendidos em setembro?",
]

st.set_page_config(page_title=f"{BOT_NAME}", page_icon="💜", layout="wide")

# ---------- Modo escuro ----------
if "dark" not in st.session_state:
    st.session_state.dark = st.query_params.get("tema") == "escuro"
DARK = bool(st.session_state.dark)
# Cores usadas nos gráficos (Altair não lê as variáveis CSS)
INK = "#f2f0f7" if DARK else "#1c1c1e"
MUTED = "#a9a4b8" if DARK else "#676768"
GRID = "#2f2640" if DARK else "#eff1f6"
SURFACE = "#1c1528" if DARK else "#faf8f5"

# ---------- Estilo (tokens do Grove AI) ----------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono&family=Libre+Caslon+Text&display=swap');

:root {
  /* Colors (o verde Forest Grove do guia foi trocado por roxo) */
  --color-brand: #6d3fc0;
  --color-gold: #c4a054;
  --color-gold-deep: #8c6d2a;
  --color-pine-shadow: #231a33;
  --color-ink-black: #1c1c1e;
  --color-graphite: #303033;
  --color-slate-mid: #676768;
  --color-mist-gray: #eff1f6;
  --color-pure-white: #ffffff;
  --color-shadow-smoke: #bfbfbf;

  /* Typography — Font Families */
  --font-sans-serif: 'sans-serif', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-libre-caslon-text: 'Libre Caslon Text', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-geist: 'Geist', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-geist-mono: 'Geist Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --font-geist-medium: 'Geist Medium', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;

  /* Typography — Scale */
  --text-caption: 12px; --leading-caption: 1.5; --tracking-caption: 1.2px;
  --text-body-sm: 14px; --leading-body-sm: 1.5; --tracking-body-sm: -0.28px;
  --text-body: 16px; --leading-body: 1.5; --tracking-body: -0.32px;
  --text-subheading: 20px; --leading-subheading: 1.25; --tracking-subheading: -0.4px;
  --text-heading-sm: 24px; --leading-heading-sm: 1.25; --tracking-heading-sm: -0.6px;
  --text-heading: 32px; --leading-heading: 1.2; --tracking-heading: -0.9px;
  --text-heading-lg: 40px; --leading-heading-lg: 1.2; --tracking-heading-lg: -1.44px;
  --text-display: 92px; --leading-display: 1.2; --tracking-display: -1.01px;

  /* Typography — Weights */
  --font-weight-regular: 400; --font-weight-medium: 500;
  --font-weight-semibold: 600; --font-weight-bold: 700;

  /* Spacing */
  --spacing-unit: 4px; --spacing-4: 4px; --spacing-8: 8px; --spacing-12: 12px;
  --spacing-16: 16px; --spacing-20: 20px; --spacing-24: 24px; --spacing-32: 32px;
  --spacing-36: 36px; --spacing-40: 40px; --spacing-48: 48px; --spacing-64: 64px;
  --spacing-72: 72px; --spacing-80: 80px; --spacing-96: 96px;

  /* Layout */
  --page-max-width: 1200px; --section-gap: 80px; --card-padding: 24px; --element-gap: 10px;

  /* Border Radius */
  --radius-lg: 8px; --radius-xl: 12px; --radius-2xl: 16px; --radius-2xl-2: 20px;
  --radius-3xl: 24px; --radius-3xl-2: 28px; --radius-3xl-3: 40px;
  --radius-full: 100px; --radius-full-2: 999px;

  /* Named Radii */
  --radius-tags: 9999px; --radius-cards: 20px; --radius-icons: 12px; --radius-inputs: 8px;
  --radius-buttons: 9999px; --radius-largecards: 24px; --radius-testimonialcards: 20px;

  /* Shadows */
  --shadow-subtle: rgba(0, 0, 0, 0.25) 0px 1px 2px 0px inset;
  --shadow-subtle-2: rgba(0, 0, 0, 0.35) 0px 0px 1px 0px;
  --shadow-subtle-3: rgba(0, 0, 0, 0.15) 0px 1px 1px 0px;
  --shadow-subtle-4: rgba(255, 255, 255, 0.75) 0px 1px 2px 0px inset;

  /* Surfaces */
  --surface-canvas: #faf8f5;
  --surface-card: #eff1f6;
  --surface-inverted-dark: #231a33;
  --surface-brand-accent: var(--color-brand);
}

html, body, .stApp, [data-testid="stMarkdownContainer"] {
  font-family: var(--font-geist);
  font-feature-settings: "ss01" on, "tnum" on;
  font-size: var(--text-body);
  line-height: var(--leading-body);
  letter-spacing: var(--tracking-body);
  color: var(--color-ink-black);
}
code, pre, [data-testid="stCode"] * { font-family: var(--font-geist-mono) !important; }
.stApp { background: var(--surface-canvas); overflow-x: hidden; }
#MainMenu, footer { visibility: hidden; }
[data-testid="stHeader"] { display: none; }
.block-container { max-width: var(--page-max-width); padding: var(--spacing-16) var(--spacing-24) 8rem; }

/* Faixa de anúncio e topo (largura total) */
.g-banner {
  background: var(--surface-brand-accent); color: var(--color-pure-white);
  font-size: var(--text-body-sm); line-height: var(--leading-body-sm); letter-spacing: var(--tracking-body-sm);
  text-align: center; padding: var(--spacing-4) var(--spacing-16);
  width: 100vw; margin-left: calc(50% - 50vw);
}
.g-nav {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--spacing-16) 0; margin-bottom: var(--spacing-64);
  border-bottom: 1px solid rgba(28,28,30,.1);
}
.g-logo { font-size: var(--text-heading-lg); font-weight: var(--font-weight-semibold); letter-spacing: var(--tracking-heading-lg); line-height: 1.2; }
.g-logo b { color: var(--color-brand); }

.g-brand { display: flex; flex-direction: column; align-items: flex-start; }
.g-logo-img { height: 92px; width: auto; display: block; margin-bottom: var(--spacing-24); }

/* Hero */
.g-hero { display: grid; grid-template-columns: 1.3fr 1fr; gap: var(--spacing-48); align-items: center; margin-bottom: var(--section-gap); }
.g-tag {
  display: inline-block; padding: var(--spacing-8) var(--spacing-16);
  border: 1px solid var(--color-brand); border-radius: var(--radius-tags); color: var(--color-brand);
  font-size: var(--text-caption); line-height: var(--leading-caption);
  letter-spacing: var(--tracking-caption); text-transform: uppercase; margin-bottom: var(--spacing-24);
}
.g-title {
  font-family: var(--font-libre-caslon-text) !important; font-weight: var(--font-weight-regular) !important;
  font-size: clamp(48px, 8vw, var(--text-display)); line-height: var(--leading-display);
  letter-spacing: -0.011em; margin: 0 0 var(--spacing-24); color: var(--color-ink-black);
}
.g-title em { font-style: normal; color: var(--color-brand); }
.g-sub {
  font-size: var(--text-subheading); font-weight: var(--font-weight-medium);
  line-height: var(--leading-subheading); letter-spacing: var(--tracking-subheading);
  max-width: 520px; margin: 0 0 var(--spacing-32);
}
.g-cta { display: flex; gap: var(--spacing-12); flex-wrap: wrap; }
.g-btn {
  border: 1px solid var(--color-ink-black); border-radius: var(--radius-buttons);
  padding: var(--spacing-12) var(--spacing-24); font-size: var(--text-body-sm);
  font-weight: var(--font-weight-medium); letter-spacing: var(--tracking-body-sm); text-decoration: none;
}
.g-btn, .g-btn:hover, .g-btn:visited { text-decoration: none !important; color: var(--color-ink-black) !important; }
.g-btn.fill, .g-btn.fill:hover, .g-btn.fill:visited { color: var(--color-pure-white) !important; }
.g-btn.fill { background: var(--color-ink-black); box-shadow: var(--shadow-subtle-3), var(--shadow-subtle-4); }

.g-mock {
  background: var(--color-pure-white); border-radius: var(--radius-cards);
  box-shadow: var(--shadow-subtle-2), var(--shadow-subtle); padding: var(--card-padding);
  min-height: 360px; display: flex; flex-direction: column; justify-content: flex-end; gap: var(--spacing-12);
}
.g-mock .ph { background: var(--color-mist-gray); border-radius: var(--radius-xl); flex: 1; min-height: 200px; overflow: hidden; }
.g-mock .ph img { width: 100%; height: 100%; object-fit: cover; object-position: 50% 35%; display: block; }
.g-b1 { align-self: flex-start; background: var(--color-brand); color: var(--color-pure-white);
  border-radius: var(--radius-buttons); padding: var(--spacing-8) var(--spacing-16); font-size: var(--text-body-sm); }
.g-b2 { align-self: flex-start; border: 1px solid rgba(28,28,30,.2); border-radius: var(--radius-buttons);
  padding: var(--spacing-8) var(--spacing-16); font-size: 18px; letter-spacing: -0.017em; }

/* Estatísticas (fórmula: rótulo → número → legenda) */
.g-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--spacing-16); margin-bottom: var(--section-gap); }
.g-stat { background: var(--surface-card); border-radius: var(--radius-cards); padding: var(--card-padding); }
.g-label { font-size: var(--text-caption); line-height: var(--leading-caption); letter-spacing: var(--tracking-caption);
  text-transform: uppercase; color: var(--color-brand); }
.g-num { font-size: var(--text-heading-lg); font-weight: var(--font-weight-semibold); line-height: var(--leading-heading-lg);
  letter-spacing: var(--tracking-heading-lg); margin: var(--spacing-8) 0 var(--spacing-4); }
.g-cap { font-size: var(--text-body-sm); line-height: var(--leading-body-sm); letter-spacing: var(--tracking-body-sm); color: var(--color-graphite); }
.g-section { font-family: var(--font-libre-caslon-text) !important; font-weight: var(--font-weight-regular) !important;
  font-size: var(--text-heading-lg); line-height: var(--leading-heading-lg); letter-spacing: -0.011em; margin: 0 0 var(--spacing-8); }
@media (max-width: 900px) { .g-hero { grid-template-columns: 1fr; } .g-stats { grid-template-columns: 1fr; } }

.g-logo { padding: var(--spacing-16) 0; }
.g-navline { border-bottom: 1px solid rgba(28,28,30,.1); margin: var(--spacing-8) 0 var(--spacing-64); }
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"] {
  background: var(--color-ink-black); border-color: var(--color-ink-black);
  box-shadow: var(--shadow-subtle-3), var(--shadow-subtle-4);
}
.stButton > button[kind="primary"] p, .stButton > button[data-testid="stBaseButton-primary"] p { color: var(--color-pure-white); }
.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="stBaseButton-primary"]:hover { background: var(--color-graphite); }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: var(--radius-cards); }

/* Carregamento: frase "Pensando..." centralizada */
.g-loading { display: flex; justify-content: center; align-items: center; width: 100%; padding: var(--spacing-24) 0; }
.g-pensando { font-size: var(--text-body); letter-spacing: var(--tracking-body); color: var(--color-slate-mid);
  animation: g-pulso 1.4s ease-in-out infinite; }
@keyframes g-pulso { 0%, 100% { opacity: .4; } 50% { opacity: 1; } }

/* Botão "Baixar PDF" no mesmo estilo dos botões escuros */
[data-testid="stDownloadButton"] button {
  border-radius: var(--radius-buttons); padding: var(--spacing-12) var(--spacing-24);
  background: var(--color-ink-black); border: 1px solid var(--color-ink-black);
  box-shadow: var(--shadow-subtle-3), var(--shadow-subtle-4);
}
[data-testid="stDownloadButton"] button p {
  color: var(--color-pure-white); font-size: var(--text-body-sm); font-weight: var(--font-weight-medium);
}

/* Chat */
[data-testid="stChatMessage"] {
  background: var(--color-pure-white); border-radius: var(--radius-testimonialcards);
  padding: var(--spacing-20) var(--card-padding); box-shadow: var(--shadow-subtle-2), var(--shadow-subtle);
  margin: 0 auto var(--spacing-16); max-width: 760px;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background: var(--surface-card); box-shadow: none; }
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] { display: none; }
[data-testid="stChatMessage"] p { font-size: var(--text-body); line-height: var(--leading-body); letter-spacing: var(--tracking-body); }
.stButton > button {
  border-radius: var(--radius-buttons); padding: var(--spacing-12) var(--spacing-24);
  font-size: var(--text-body-sm); font-weight: var(--font-weight-medium); letter-spacing: var(--tracking-body-sm);
  border: 1px solid var(--color-ink-black); background: transparent; color: var(--color-ink-black); box-shadow: none;
}
.stButton > button:hover { background: var(--surface-card); border-color: var(--color-ink-black); color: var(--color-ink-black); }
[data-testid="stChatInput"] > div { border-radius: var(--radius-buttons); background: var(--color-pure-white);
  border: 1px solid rgba(28,28,30,.12); box-shadow: none; }
[data-testid="stBottom"] > div { background: var(--surface-canvas); }
[data-testid="stExpander"] { border-radius: var(--radius-xl); }
/* Botões do topo (Chatbot / Insights / Dados) em dourado, como na logo */
.st-key-nav_chat button, .st-key-nav_insights button , .st-key-nav_dados button {
  background: transparent; border: 1px solid var(--color-gold-deep); box-shadow: none;
}
.st-key-nav_chat button p, .st-key-nav_insights button p , .st-key-nav_dados button p { color: var(--color-gold-deep); }
.st-key-nav_chat button:hover, .st-key-nav_insights button:hover , .st-key-nav_dados button:hover {
  background: rgba(196,160,84,.15); border-color: var(--color-gold-deep);
}
.st-key-nav_chat button[kind="primary"], .st-key-nav_insights button[kind="primary"], .st-key-nav_dados button[kind="primary"],
.st-key-nav_chat button[data-testid="stBaseButton-primary"], .st-key-nav_insights button[data-testid="stBaseButton-primary"] , .st-key-nav_dados button[data-testid="stBaseButton-primary"] {
  background: var(--color-gold); border-color: var(--color-gold);
  box-shadow: var(--shadow-subtle-3), var(--shadow-subtle-4);
}
.st-key-nav_chat button[kind="primary"] p, .st-key-nav_insights button[kind="primary"] p, .st-key-nav_dados button[kind="primary"] p,
.st-key-nav_chat button[data-testid="stBaseButton-primary"] p, .st-key-nav_insights button[data-testid="stBaseButton-primary"] p , .st-key-nav_dados button[data-testid="stBaseButton-primary"] p {
  color: var(--color-pine-shadow);
}
.st-key-nav_chat button[kind="primary"]:hover, .st-key-nav_insights button[kind="primary"]:hover, .st-key-nav_dados button[kind="primary"]:hover,
.st-key-nav_chat button[data-testid="stBaseButton-primary"]:hover, .st-key-nav_insights button[data-testid="stBaseButton-primary"]:hover , .st-key-nav_dados button[data-testid="stBaseButton-primary"]:hover {
  background: #b38f45; border-color: #b38f45;
}
/* Botão de tema: metade do tamanho dos botões do topo */
.st-key-nav_theme button { padding: 6px 12px; min-height: 0; white-space: nowrap; }
.st-key-nav_theme button p { font-size: 12px; }
</style>
""",
    unsafe_allow_html=True,
)

if DARK:
    st.markdown(
        """
<style>
:root {
  --color-brand: #8a63d9;
  --color-gold-deep: #d9b869;
  --color-ink-black: #f2f0f7;
  --color-graphite: #c9c5d3;
  --color-slate-mid: #a9a4b8;
  --color-mist-gray: #2a2236;
  --color-pure-white: #1c1528;
  --surface-canvas: #120d1b;
  --surface-card: #2a2236;
  --shadow-subtle: rgba(0, 0, 0, 0.5) 0px 1px 2px 0px inset;
  --shadow-subtle-2: rgba(255, 255, 255, 0.22) 0px 0px 1px 0px;
  --shadow-subtle-3: rgba(0, 0, 0, 0.4) 0px 1px 1px 0px;
  --shadow-subtle-4: rgba(255, 255, 255, 0.1) 0px 1px 2px 0px inset;
}
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: #120d1b !important; color: #f2f0f7; }
.g-navline, .g-nav { border-bottom-color: rgba(255,255,255,.12) !important; }
.g-b1 { color: #ffffff !important; }
.g-b2 { border-color: rgba(255,255,255,.28) !important; }
.g-logo-img { background: #ffffff; padding: 10px 18px; border-radius: 16px; }
[data-testid="stChatInput"] > div { border-color: rgba(255,255,255,.18) !important; background: #1c1528 !important; }
[data-testid="stChatInput"] textarea { color: #f2f0f7 !important; background: transparent !important; }
[data-testid="stChatInput"] textarea::placeholder { color: #a9a4b8 !important; }
[data-testid="stBottom"], [data-testid="stBottom"] > div { background: #120d1b !important; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color: rgba(255,255,255,.14) !important; }
[data-testid="stExpander"] details { border-color: rgba(255,255,255,.14) !important; background: transparent !important; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { color: #f2f0f7 !important; }
[data-testid="stCode"], [data-testid="stCode"] pre, [data-testid="stCode"] code { background: #2a2236 !important; }
[data-testid="stCode"] * { color: #e6e1f0 !important; }
[data-testid="stDataFrame"] { filter: invert(0.92) hue-rotate(180deg); }
[data-testid="stAlert"] * { color: #f2f0f7 !important; }
[data-testid="stSpinner"] * { color: #c9c5d3 !important; }
.stButton > button:disabled { opacity: .5; }
</style>
""",
        unsafe_allow_html=True,
    )

# ---------- Página ----------
def load_logo(nome: str = "logo_farmazids.png") -> str:
    caminho = Path(__file__).parent / nome
    if not caminho.exists():
        return ""
    b64 = base64.b64encode(caminho.read_bytes()).decode()
    return f'<img class="g-logo-img" src="data:image/png;base64,{b64}" alt="Farmazids">'




@contextlib.contextmanager
def carregando(texto: str = "Consultando os dados..."):
    """Mostra a frase "Pensando..." (centralizada) enquanto a busca roda, no lugar do st.spinner."""
    espaco = st.empty()
    espaco.markdown(
        f'<div class="g-loading" role="status" aria-label="{texto}"><span class="g-pensando">Pensando...</span></div>',
        unsafe_allow_html=True,
    )
    try:
        yield
    finally:
        espaco.empty()


# ---------- Login (aparece sempre que alguém abre o site) ----------
# Usuário e senha vêm dos Secrets / variáveis de ambiente, nunca do código:
#   APP_USER + APP_PASSWORD  (um acesso)   ou   tabela [usuarios] com vários acessos
def _segredo(nome: str):
    valor = os.environ.get(nome)
    if valor:
        return valor
    try:
        return st.secrets.get(nome)
    except Exception:
        return None


def _usuarios() -> dict:
    acessos = {}
    try:
        tabela = st.secrets.get("usuarios")
        if tabela:
            acessos.update({str(k): str(v) for k, v in dict(tabela).items()})
    except Exception:
        pass
    usuario, senha = _segredo("APP_USER"), _segredo("APP_PASSWORD")
    if usuario and senha:
        acessos[str(usuario)] = str(senha)
    return acessos


def _confere(usuario: str, senha: str, acessos: dict) -> bool:
    ok = False
    for u, p in acessos.items():  # percorre todos e compara em tempo constante
        ok_usuario = hmac.compare_digest(usuario.strip().encode(), u.encode())
        ok_senha = hmac.compare_digest(senha.encode(), p.encode())
        ok = ok or (ok_usuario and ok_senha)
    return ok


def tela_login():
    st.markdown(
        """
<style>
.g-login { text-align: center; margin-top: var(--spacing-32); }
.g-login .g-logo-img { margin: 0 auto var(--spacing-24); }
.g-login .g-tag { margin-bottom: var(--spacing-16); }
.g-login .g-cap { margin-bottom: var(--spacing-24); }
[data-testid="stForm"] {
  border: 1px solid rgba(128,128,128,.25); border-radius: var(--radius-cards);
  padding: var(--card-padding); background: var(--color-pure-white);
  box-shadow: var(--shadow-subtle-2), var(--shadow-subtle);
}
[data-testid="stForm"] input { border-radius: var(--radius-inputs); }
[data-testid="stFormSubmitButton"] button {
  border-radius: var(--radius-buttons); padding: var(--spacing-12) var(--spacing-24);
  background: var(--color-ink-black); border: 1px solid var(--color-ink-black);
  box-shadow: var(--shadow-subtle-3), var(--shadow-subtle-4);
}
[data-testid="stFormSubmitButton"] button p {
  color: var(--color-pure-white); font-size: var(--text-body-sm); font-weight: var(--font-weight-medium);
}
</style>
""",
        unsafe_allow_html=True,
    )
    acessos = _usuarios()
    _, centro, _ = st.columns([1, 1.2, 1])
    with centro:
        st.markdown(
            f'<div class="g-login">{load_logo()}<span class="g-tag">Acesso restrito</span>'
            f'<h1 class="g-title" style="font-size:clamp(40px,6vw,56px)">Entrar no <em>{BOT_NAME}</em></h1>'
            f'<p class="g-cap">Informe seu usuário e senha para continuar.</p></div>',
            unsafe_allow_html=True,
        )
        if not acessos:
            st.error("Login não configurado. Defina APP_USER e APP_PASSWORD nos Secrets do app.")
            return
        with st.form("login_form"):
            usuario = st.text_input("Usuário", key="login_user")
            senha = st.text_input("Senha", type="password", key="login_pass")
            enviar = st.form_submit_button("Entrar", type="primary", use_container_width=True)
        if enviar:
            if _confere(usuario, senha, acessos):
                st.session_state.autenticado = True
                st.rerun()
            time.sleep(1)  # atrasa tentativas erradas
            st.error("Usuário ou senha incorretos.")


if not st.session_state.get("autenticado"):
    tela_login()
    st.stop()

stats = "".join(
    f'<div class="g-stat"><div class="g-label">{l}</div><div class="g-num">{n}</div><div class="g-cap">{c}</div></div>'
    for l, n, c in STATS
)
bubbles = f'<div class="g-b1">{BUBBLES[0]}</div><div class="g-b2">{BUBBLES[1]}</div>'

body_html = (
    f'<div class="g-hero"><div><div class="g-brand">{load_logo()}<span class="g-tag">{TAG}</span></div>'
    f'<h1 class="g-title">Conheça o <em>{BOT_NAME}</em></h1><p class="g-sub">{SUBHEAD}</p>'
    f'<div class="g-cta"><a class="g-btn fill" href="#conversar">Começar a conversar</a>'
    f'<a class="g-btn" href="#resultados">Ver resultados</a></div></div>'
    f'<div class="g-mock"><div class="ph"><img src="app/static/ZIDS.gif" alt="{BOT_NAME}"></div>{bubbles}</div></div>'
    f'<div id="resultados" class="g-stats">{stats}</div>'
    f'<div id="conversar"><h2 class="g-section">Converse com o {BOT_NAME}</h2>'
    f'<p class="g-cap" style="margin-bottom:24px">Escolha uma pergunta ou escreva a sua.</p></div>'
)

if "page" not in st.session_state:
    st.session_state.page = "chat"

# ---------- Topo: logo + botões de troca de página ----------
c_logo, c_chat, c_ins, c_dados, c_tema = st.columns([4.05, 1.4, 1.4, 1.4, 0.85], vertical_alignment="center")
c_logo.markdown(f'<div class="g-logo"><b>●</b> {BOT_NAME}</div>', unsafe_allow_html=True)
for col, key, label in ((c_chat, "chat", "Chatbot"), (c_ins, "insights", "Insights"), (c_dados, "dados", "Dados")):
    ativo = st.session_state.page == key
    if col.button(label, key=f"nav_{key}", type="primary" if ativo else "secondary", use_container_width=True):
        st.session_state.page = key
        st.rerun()
if c_tema.button("Modo claro" if DARK else "Modo escuro", key="nav_theme", use_container_width=True):
    st.session_state.dark = not DARK
    st.query_params["tema"] = "claro" if DARK else "escuro"
    st.rerun()
st.markdown('<div class="g-navline"></div>', unsafe_allow_html=True)

if st.session_state.page == "chat":
    st.markdown(body_html, unsafe_allow_html=True)


# ---------- Lógica do chat ----------
@st.cache_resource
def get_sfn():
    # Credenciais vêm da cadeia padrão do boto3 (variáveis de ambiente, ~/.aws, IAM role)
    return boto3.client(
        "stepfunctions",
        region_name=AWS_REGION,
        config=Config(read_timeout=280, connect_timeout=10, retries={"max_attempts": 1}),
    )


@st.cache_resource
def get_state_machine_type() -> str:
    if STATE_MACHINE_TYPE in ("EXPRESS", "STANDARD"):
        return STATE_MACHINE_TYPE
    try:
        return get_sfn().describe_state_machine(stateMachineArn=STATE_MACHINE_ARN)["type"]
    except (ClientError, BotoCoreError):
        return "STANDARD"


def rows_to_df(linhas):
    """Converte o ResultSet do Athena (primeira linha = cabeçalho) em DataFrame."""
    try:
        valores = [[c.get("VarCharValue") for c in r["Data"]] for r in linhas]
        return pd.DataFrame(valores[1:], columns=valores[0]) if len(valores) > 1 else None
    except (KeyError, TypeError, IndexError):
        return None


def parse_output(output: str) -> dict:
    """A state machine devolve {"resposta": ..., "sql": ..., "linhas": [...]}."""
    try:
        data = json.loads(output)
    except (TypeError, ValueError):
        return {"content": str(output)}
    if not isinstance(data, dict):
        return {"content": str(data)}
    texto = data.get("resposta")
    if isinstance(texto, list):  # o JSONPath com filtro pode devolver lista
        texto = texto[0] if texto else None
    return {
        "content": texto or json.dumps(data, ensure_ascii=False, indent=2),
        "sql": data.get("sql"),
        "rows": data.get("linhas"),
    }


def montar_historico(mensagens: list, max_turnos: int = 3, max_resp: int = 350, max_sql: int = 1200) -> str:
    """Resume as últimas trocas do chat (pergunta, trecho da resposta e SQL) para a memória da conversa."""
    turnos = [m for m in mensagens if m.get("role") == "assistant" and m.get("pergunta") and m.get("sql")]
    partes = []
    for n, m in enumerate(turnos[-max_turnos:], 1):
        resposta = " ".join(str(m.get("content", "")).split())[:max_resp]
        sql = " ".join(str(m["sql"]).split())[:max_sql]
        partes.append(f"[{n}] Pergunta: {m['pergunta']}\nResposta (trecho): {resposta}\nSQL: {sql}")
    return "\n\n".join(partes)


def generate_reply(pergunta: str, historico: str = "") -> dict:
    # A state machine lê $.pergunta e $.historico (texto com as últimas trocas; vazio = sem memória)
    payload = {"pergunta": pergunta, "historico": historico}
    sfn = get_sfn()
    try:
        if get_state_machine_type() == "EXPRESS":
            result = sfn.start_sync_execution(
                stateMachineArn=STATE_MACHINE_ARN, input=json.dumps(payload)
            )
            status, output = result["status"], result.get("output")
            error, cause = result.get("error"), result.get("cause")
        else:
            execution = sfn.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                name=f"chat-{uuid.uuid4()}",
                input=json.dumps(payload),
            )
            deadline = time.time() + EXECUTION_TIMEOUT_S
            while True:
                result = sfn.describe_execution(executionArn=execution["executionArn"])
                status = result["status"]
                if status != "RUNNING":
                    break
                if time.time() > deadline:
                    return {"content": "A resposta demorou mais que o esperado. Tente novamente."}
                time.sleep(1)
            output, error, cause = result.get("output"), result.get("error"), result.get("cause")
    except (ClientError, BotoCoreError) as exc:
        return {"content": f"Não consegui acessar o serviço: {exc}"}

    if status != "SUCCEEDED":
        # Os estados Fail da state machine já trazem uma mensagem amigável em "cause"
        return {"content": cause or f"A execução terminou com status {status} ({error})."}
    return parse_output(output) if output else {"content": "A execução terminou sem resposta."}


PURPLE = "#8a63d9" if DARK else "#6d3fc0"
PALETTE = (
    [PURPLE, INK, "#a98ee0", "#9c98a8", "#c7b5ec", "#c9c5d3"]
    if DARK
    else ["#6d3fc0", "#1c1c1e", "#a98ee0", "#676768", "#c7b5ec", "#303033"]
)


def tema_escuro(chart):
    """Ajusta gráficos do chat (build_chart) para o modo escuro."""
    if not DARK:
        return chart
    return (
        chart.configure_view(stroke=None)
        .configure_axis(labelColor=MUTED, titleColor=MUTED, gridColor=GRID, domainColor=GRID, tickColor=GRID)
        .configure_legend(labelColor=INK, titleColor=INK)
        .properties(background="rgba(0,0,0,0)")
    )
CHART_WORDS = ("gráfico", "grafico", "chart", "plot", "plote", "visualização", "visualizacao")


def wants_chart(pergunta: str) -> bool:
    return any(w in pergunta.lower() for w in CHART_WORDS)


def build_chart(df: pd.DataFrame, pergunta: str):
    """Monta um gráfico Altair a partir do resultado; devolve None se não houver dados numéricos."""
    q = pergunta.lower()
    df = df.copy()
    date_col, num_cols, text_cols = None, [], []
    for c in df.columns:
        vals = df[c].dropna().astype(str)
        if vals.empty:
            text_cols.append(c)
            continue
        dates = pd.to_datetime(vals, format="%Y-%m-%d", errors="coerce")
        nums = pd.to_numeric(vals, errors="coerce")
        looks_like_id = vals.str.fullmatch(r"\d{8,}").all() or any(k in c.lower() for k in ("gtin", "codigo", "id_"))
        if date_col is None and dates.notna().all():
            date_col = c
        elif nums.notna().all() and not looks_like_id:
            num_cols.append(c)
        else:
            text_cols.append(c)
    if not num_cols:
        return None

    y = num_cols[-1]  # agregados costumam ser a última coluna do SELECT
    d = pd.DataFrame({"valor": pd.to_numeric(df[y], errors="coerce")})
    d["rotulo"] = df[text_cols].astype(str).agg(" – ".join, axis=1) if text_cols else df.index.astype(str)
    ytitle = alt.Axis(title=y)

    if date_col is not None:
        d["x"] = pd.to_datetime(df[date_col], format="%Y-%m-%d", errors="coerce")
        enc = dict(x=alt.X("x:T", title=None), y=alt.Y("valor:Q", axis=ytitle))
        if text_cols:
            enc["color"] = alt.Color("rotulo:N", title=None, scale=alt.Scale(range=PALETTE))
            return alt.Chart(d).mark_line(point=True).encode(**enc)
        return alt.Chart(d).mark_line(point=True, color=PURPLE).encode(**enc)

    if "pizza" in q and len(d) <= 8:
        return alt.Chart(d).mark_arc().encode(
            theta="valor:Q", color=alt.Color("rotulo:N", title=None, scale=alt.Scale(range=PALETTE))
        )
    return (
        alt.Chart(d)
        .mark_bar(color=PURPLE, cornerRadiusEnd=4)
        .encode(
            x=alt.X("rotulo:N", sort=None, title=None, axis=alt.Axis(labelAngle=-30, labelLimit=180)),
            y=alt.Y("valor:Q", axis=ytitle),
            tooltip=["rotulo", "valor"],
        )
    )


def md_seguro(texto) -> str:
    """Escapa o cifrão: o Streamlit trata $...$ como fórmula e quebra textos com dois 'R$' no mesmo parágrafo."""
    return str(texto or "").replace("\\$", "$").replace("$", "\\$")


def render_message(m: dict):
    st.markdown(md_seguro(m["content"]))
    df = rows_to_df(m.get("rows") or []) if m.get("sql") else None
    if m.get("chart"):
        chart = build_chart(df, m.get("pergunta", "")) if df is not None else None
        if chart is not None:
            st.altair_chart(tema_escuro(chart.properties(height=320)), use_container_width=True,
                            theme=None if DARK else "streamlit")
        else:
            st.info("Não há dados numéricos suficientes para montar um gráfico com essa pergunta.")
    if m.get("sql"):
        with st.expander("Ver consulta e dados"):
            st.code(m["sql"], language="sql")
            if df is not None:
                st.dataframe(df, use_container_width=True, hide_index=True)


# ---------- Página: Insights ----------
# Cada card tem um GRÁFICO FIXO (tipo, eixos, cores e formato definidos aqui).
# A state machine só devolve os dados: a pergunta fixa o nome e a ORDEM das colunas,
# e o app as lê por posição. Edite títulos, perguntas e formatos à vontade.
#   tipo: "barras_agrupadas" (grupo, rotulo, valor) | "barras_v" (rotulo, valor)
#         "barras_h" (rotulo, valor) | "linha" (data, valor)
#   fmt:  "int" (1.234) | "dinheiro" (R$ 1.234,56) | "pct" (12,5%)
INSIGHTS = [
    {
        "titulo": "Mais vendidos por farmácia",
        "tipo": "barras_agrupadas",
        "fmt": "int",
        "eixo": "Unidades vendidas",
        "colunas": ["grupo", "rotulo", "valor"],
        "pergunta": (
            "Quais são os 3 produtos mais vendidos em cada farmácia no mês mais recente com vendas "
            "registradas na tabela historico_farmazids? Considere o mês da maior data_venda da tabela, "
            "e não o mês atual. Some quantidade_vendida por farmácia e produto. Devolva exatamente 3 colunas, "
            "nesta ordem e com estes apelidos: farmacia, produto, total_vendido."
        ),
    },
    {
        "titulo": "Maior diferença de preço vs. concorrentes",
        "tipo": "variacao",
        "fmt": "dinheiro",
        "eixo": "Diferença do concorrente vs. Farmazids (R$)",
        "nome_grupo": "Comparação",
        "colunas": ["grupo", "rotulo", "valor"],
        "pergunta": (
            "Compare o preço de cada produto da Farmazids (tabela medicamentos_farmazids, coluna preco, "
            "usando só a coleta mais recente) com o preço com desconto no pix (coluna preco_desconto_pix) "
            "da FarmaPonte (tabela farmaponte_tratado) e da VeraCruz (tabela veracruz_tratado), ligando as "
            "tabelas pelo gtin e usando só a coleta mais recente de cada tabela. Calcule "
            "diferenca_preco = preco_desconto_pix - preco (em reais). Compare SOMENTE produtos que tenham preço "
            "definido nos dois lados: aplique obrigatoriamente no WHERE as condições preco IS NOT NULL AND "
            "preco > 0 (Farmazids) e preco_desconto_pix IS NOT NULL AND preco_desconto_pix > 0 (concorrente), "
            "e descarte qualquer linha que não atenda a todas. "
            "Devolva os 5 produtos com maior diferença absoluta (valor absoluto de diferenca_preco) para cada "
            "concorrente, 10 linhas no total, mantendo o sinal de diferenca_preco. Devolva exatamente 3 colunas, "
            "nesta ordem e com estes apelidos: comparacao (use exatamente 'Farmazids x FarmaPonte' ou "
            "'Farmazids x VeraCruz'), produto (nome do produto na Farmazids), diferenca_preco."
        ),
    },
    {
        "titulo": "Top 3 categorias mais vendidas",
        "tipo": "barras_h",
        "fmt": "int",
        "eixo": "Unidades vendidas",
        "nome_item": "Categoria",
        "colunas": ["rotulo", "valor"],
        "pergunta": (
            "Quais são as 3 categorias mais vendidas no mês mais recente com vendas registradas na tabela "
            "historico_farmazids (considere o mês da maior data_venda da tabela, e não o mês atual)? "
            "A tabela historico_farmazids não tem categoria, então descubra a categoria de cada produto pelo gtin, "
            "buscando em farmaponte_tratado e, se não houver, em veracruz_tratado. Monte primeiro uma lista com "
            "UM único registro por gtin (por exemplo, GROUP BY gtin com MAX(categoria), ignorando categorias nulas "
            "ou vazias) para não duplicar as vendas, juntando as duas tabelas com UNION e COALESCE. Use INNER JOIN "
            "com essa lista: produtos que não estejam cadastrados em nenhuma das duas tabelas devem ser "
            "simplesmente ignorados. Some quantidade_vendida por categoria e devolva as 3 maiores. Devolva "
            "exatamente 2 colunas, nesta ordem e com estes apelidos: categoria, total_vendido."
        ),
    },
    {
        "titulo": "Sugestões para o catálogo",
        "tipo": "tabela",
        "pergunta": (
            "Quero sugestões de produtos para adicionar ao catálogo da Farmazids. Pegue, na coleta mais recente "
            "de farmaponte_tratado e de veracruz_tratado, os produtos cujo gtin NÃO existe na tabela "
            "medicamentos_farmazids (use NOT EXISTS ou LEFT JOIN com IS NULL), com gtin e preco_desconto_pix "
            "não nulos e maiores que zero. As tabelas dos concorrentes não têm vendas, então priorize nesta "
            "ordem: 1) produtos cujo gtin aparece nas duas tabelas (FarmaPonte e VeraCruz); 2) produtos das "
            "categorias que mais vendem na Farmazids (some quantidade_vendida de historico_farmazids por "
            "categoria, descobrindo a categoria de cada gtin vendido em farmaponte_tratado ou veracruz_tratado, "
            "com um único registro por gtin para não duplicar vendas); 3) maior desconto_pct. Devolva 5 "
            "produtos da FarmaPonte e 5 da VeraCruz (10 linhas no total), um registro por gtin em cada "
            "concorrente. Devolva exatamente 4 colunas, nesta ordem e com estes apelidos: concorrente "
            "(use exatamente 'FarmaPonte' ou 'VeraCruz'), produto, categoria, preco_pix (o preco_desconto_pix)."
        ),
    },
    {
        "titulo": "Farmazids vs. concorrentes: posição de preço",
        "tipo": "pizza",
        "fmt": "int",
        "eixo": "Produtos",
        "nome_item": "Situação",
        "colunas": ["rotulo", "valor"],
        "pergunta": (
            "Classifique os produtos que a Farmazids vende (tabela medicamentos_farmazids, coluna preco, coleta "
            "mais recente, um registro por gtin) em relação aos concorrentes. Para cada gtin presente também em "
            "farmaponte_tratado ou veracruz_tratado (coleta mais recente), pegue o MENOR preco_desconto_pix entre "
            "os concorrentes que o vendem, considerando apenas preços não nulos e maiores que zero, e exija "
            "preco > 0 e preco IS NOT NULL na Farmazids. Calcule a diferença relativa = (preco - menor_preco_concorrente) "
            "/ menor_preco_concorrente. Classifique em: 'Farmazids mais cara' (diferença maior que 10%), "
            "'Farmazids mais barata' (diferença menor que -10%) e 'Preço similar' (entre -10% e 10%, inclusive). "
            "Conte quantos produtos há em cada situação. Devolva exatamente 3 linhas e 2 colunas, nesta ordem e "
            "com estes apelidos: situacao (exatamente um dos três textos acima), qtd_produtos."
        ),
    },
]

# Formatadores (padrão brasileiro) usados na tabela, nos tooltips e nos rótulos
def fmt_valor(v: float, fmt: str) -> str:
    if pd.isna(v):
        return ""
    if fmt == "dinheiro":
        s = f"{v:,.2f}"
        prefixo, sufixo = "R$ ", ""
    elif fmt == "pct":
        s = f"{v:,.1f}"
        prefixo, sufixo = "", "%"
    else:
        s = f"{v:,.0f}"
        prefixo, sufixo = "", ""
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    if s.startswith("-"):
        return "-" + prefixo + s[1:] + sufixo
    return prefixo + s + sufixo


def padronizar(df: pd.DataFrame, spec: dict):
    """Lê as colunas por posição e renomeia para os nomes padrão do gráfico."""
    nomes = spec["colunas"]
    if df is None or df.shape[1] < len(nomes):
        return None
    d = df.iloc[:, : len(nomes)].copy()
    d.columns = nomes
    d["valor"] = pd.to_numeric(d["valor"], errors="coerce")
    d = d.dropna(subset=["valor"])
    if "data" in d.columns:
        d["data"] = pd.to_datetime(d["data"], errors="coerce", dayfirst=False)
        d = d.dropna(subset=["data"]).sort_values("data")
    d["texto"] = d["valor"].map(lambda v: fmt_valor(v, spec["fmt"]))
    return d if not d.empty else None


def grafico_fixo(d: pd.DataFrame, spec: dict):
    tipo, eixo = spec["tipo"], spec["eixo"]
    fonte = "Geist"
    xmax = float(d["valor"].max()) * 1.2 if len(d) else 1.0
    if tipo == "linha":
        base = alt.Chart(d).encode(
            x=alt.X("data:T", title=None, axis=alt.Axis(format="%d/%m", labelAngle=0)),
            y=alt.Y("valor:Q", title=eixo, scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("data:T", title="Dia", format="%d/%m/%Y"), alt.Tooltip("texto:N", title=eixo)],
        )
        chart = (
            base.mark_area(color=PURPLE, opacity=0.12, line=False)
            + base.mark_line(color=PURPLE, strokeWidth=2.5)
            + base.mark_point(color=PURPLE, filled=True, size=70)
        )
    elif tipo == "barras_h":
        base = alt.Chart(d).encode(
            y=alt.Y("rotulo:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240)),
            x=alt.X("valor:Q", title=eixo, scale=alt.Scale(domain=[0, xmax])),
            tooltip=[alt.Tooltip("rotulo:N", title=spec.get("nome_item", "Produto")), alt.Tooltip("texto:N", title=eixo)],
        )
        chart = base.mark_bar(color=PURPLE, cornerRadiusEnd=6) + base.mark_text(
            align="left", dx=6, color=INK, font=fonte
        ).encode(text="texto:N")
    elif tipo == "pizza":
        d = d.copy()
        total = d["valor"].sum()
        d["pct"] = d["valor"].map(lambda v: f"{v / total * 100:.0f}%" if total else "")
        d["detalhe"] = d["texto"] + " produtos"
        cores = alt.Scale(
            domain=["Farmazids mais barata", "Preço similar", "Farmazids mais cara"],
            range=[PURPLE, "#c4a054", INK],
        )
        ordem = alt.Order("rotulo:N")
        arco = alt.Chart(d).mark_arc(innerRadius=62, outerRadius=105, stroke=SURFACE, strokeWidth=2).encode(
            theta=alt.Theta("valor:Q", stack=True),
            color=alt.Color("rotulo:N", title=None, scale=cores, legend=alt.Legend(orient="bottom", columns=1)),
            order=ordem,
            tooltip=[alt.Tooltip("rotulo:N", title="Situação"), alt.Tooltip("detalhe:N", title="Quantidade"),
                     alt.Tooltip("pct:N", title="Participação")],
        )
        rotulos = alt.Chart(d).mark_text(radius=84, fontWeight=600, font=fonte, size=13).encode(
            theta=alt.Theta("valor:Q", stack=True),
            detail="rotulo:N",
            order=ordem,
            text="pct:N",
            color=alt.condition(
                alt.FieldOneOfPredicate(field="rotulo", oneOf=["Preço similar"] + (["Farmazids mais cara"] if DARK else [])),
                alt.value("#1b1526"), alt.value("#ffffff")),
        )
        chart = (arco + rotulos).properties(height=300)
    elif tipo == "variacao":
        d = d.copy()
        d["abs"] = d["valor"].abs()
        d["sentido"] = d["valor"].map(lambda v: "Concorrente mais caro" if v >= 0 else "Concorrente mais barato")
        base = alt.Chart(d).encode(
            y=alt.Y("rotulo:N", sort=alt.EncodingSortField(field="abs", order="descending"), title=None,
                    axis=alt.Axis(labelLimit=200, orient="left")),
            x=alt.X("valor:Q", title=eixo, scale=alt.Scale(padding=70)),
            color=alt.Color("sentido:N", title=None, scale=alt.Scale(
                domain=["Concorrente mais caro", "Concorrente mais barato"], range=[PURPLE, "#c4a054"]),
                legend=alt.Legend(orient="bottom")),
            tooltip=[alt.Tooltip("grupo:N", title="Comparação"), alt.Tooltip("rotulo:N", title="Produto"),
                     alt.Tooltip("texto:N", title="Diferença")],
        )
        pos = base.mark_text(align="left", dx=6, color=INK, font=fonte).encode(text="texto:N").transform_filter(
            alt.datum.valor >= 0)
        neg = base.mark_text(align="right", dx=-6, color=INK, font=fonte).encode(text="texto:N").transform_filter(
            alt.datum.valor < 0)
        chart = (
            (base.mark_bar(cornerRadiusEnd=6) + pos + neg)
            .properties(width=240, height=alt.Step(26))
            .facet(facet=alt.Facet("grupo:N", title=None, header=alt.Header(labelFontWeight=600, labelFontSize=13)),
                   columns=1)
            .resolve_scale(y="independent")
        )
    elif tipo == "barras_agrupadas":
        base = alt.Chart(d).encode(
            y=alt.Y("rotulo:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
            x=alt.X("valor:Q", title=eixo, scale=alt.Scale(domain=[0, xmax])),
            tooltip=[alt.Tooltip("grupo:N", title="Farmácia"), alt.Tooltip("rotulo:N", title="Produto"),
                     alt.Tooltip("texto:N", title=eixo)],
        )
        chart = (
            (base.mark_bar(color=PURPLE, cornerRadiusEnd=6)
             + base.mark_text(align="left", dx=6, color=INK, font=fonte).encode(text="texto:N"))
            .properties(width=240, height=alt.Step(26))
            .facet(facet=alt.Facet("grupo:N", title=None, header=alt.Header(labelFontWeight=600, labelFontSize=13)),
                   columns=1)
            .resolve_scale(y="independent")
        )
    else:  # barras_v
        base = alt.Chart(d).encode(
            x=alt.X("rotulo:N", sort=None, title=None, axis=alt.Axis(labelAngle=0, labelLimit=180)),
            y=alt.Y("valor:Q", title=eixo),
            color=alt.Color("rotulo:N", legend=None, scale=alt.Scale(range=PALETTE)),
            tooltip=[alt.Tooltip("rotulo:N", title="Item"), alt.Tooltip("texto:N", title=eixo)],
        )
        chart = base.mark_bar(cornerRadiusEnd=6, size=60) + base.mark_text(
            dy=-8, color=INK, font=fonte, fontWeight=600
        ).encode(text="texto:N")
    final = (
        chart.configure_view(stroke=None)
        .configure_axis(labelFont=fonte, titleFont=fonte, grid=True, gridColor=GRID,
                        domain=False, tickColor=GRID, labelColor=MUTED, titleColor=MUTED)
        .configure_legend(labelFont=fonte, labelColor=INK, titleColor=INK)
        .configure_header(labelFont=fonte, labelColor=INK, titleColor=INK)
    )
    if DARK:
        final = final.properties(background="rgba(0,0,0,0)")
    return final


@st.cache_data(ttl=3600, show_spinner=False)
def run_insight(pergunta: str) -> dict:
    resultado = generate_reply(pergunta)
    if not resultado.get("sql"):  # não guarda erros no cache
        raise RuntimeError(resultado["content"])
    return resultado


def render_tabela(bruto: pd.DataFrame, spec: dict) -> bool:
    """Tabela fixa por concorrente: colunas lidas por posição (concorrente, produto, categoria, preco_pix)."""
    if bruto is None or bruto.shape[1] < 4:
        return False
    d = bruto.iloc[:, :4].copy()
    d.columns = ["concorrente", "Produto", "Categoria", "Preço no pix (R$)"]
    d["Preço no pix (R$)"] = pd.to_numeric(d["Preço no pix (R$)"], errors="coerce")
    d = d.dropna(subset=["Produto"])
    if d.empty:
        return False
    for nome, sub in d.groupby("concorrente", sort=True):
        st.markdown(
            f'<div class="g-cap" style="font-weight:600;margin:12px 0 4px">Presente na {nome}, ausente na Farmazids</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            sub.drop(columns=["concorrente"]).head(5),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Produto": st.column_config.TextColumn("Produto", width="large"),
                "Categoria": st.column_config.TextColumn("Categoria", width="small"),
                "Preço no pix (R$)": st.column_config.NumberColumn("Preço no pix", format="R$ %.2f", width="small"),
            },
        )
    return True


# ---------- PDF dos insights (para apresentar em reuniões) ----------
# Gráficos desenhados com matplotlib e documento montado com reportlab. Sempre em tema claro,
# mesmo que o site esteja no modo escuro. Instale: py -m pip install reportlab matplotlib
def _pdf_texto(t) -> str:
    """Texto simples (sem markdown) e só com caracteres que a fonte padrão do PDF suporta."""
    t = str(t or "").replace("**", "").replace("`", "")
    t = re.sub(r"^\s*#+\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*]\s+", "• ", t, flags=re.M)
    for de, para in {"≥": ">=", "≤": "<=", "→": "->", "←": "<-", "−": "-", "\u00a0": " ", "\u202f": " ", "≈": "~"}.items():
        t = t.replace(de, para)
    return t.encode("cp1252", "replace").decode("cp1252")


def grafico_pdf(d: pd.DataFrame, spec: dict) -> bytes:
    """Desenha o gráfico do indicador em PNG (fundo branco) usando as mesmas cores do site."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    roxo, ouro, tinta, mudo, grade = "#6d3fc0", "#c4a054", "#1c1c1e", "#676768", "#e6e3ee"
    tipo, eixo = spec["tipo"], spec.get("eixo", "")
    esc = lambda x: str(x).replace("$", r"\$")  # matplotlib trata $...$ como fórmula
    cortar = lambda x, n=44: (str(x)[: n - 1] + "…") if len(str(x)) > n else str(x)

    def barras(ax, sub, cor, xlim):
        sub = sub.reset_index(drop=True)
        ax.barh(range(len(sub)), sub["valor"], color=[cor(v) for v in sub["valor"]], height=0.62)
        ax.set_yticks(range(len(sub)))
        ax.set_yticklabels([esc(cortar(x)) for x in sub["rotulo"]])
        ax.invert_yaxis()
        for i, (v, t) in enumerate(zip(sub["valor"], sub["texto"])):
            ax.text(v, i, ("  " if v >= 0 else "") + esc(t) + ("" if v >= 0 else "  "),
                    va="center", ha="left" if v >= 0 else "right", fontsize=8.5)
        ax.set_xlim(*xlim)
        ax.grid(axis="x", color=grade)
        ax.set_axisbelow(True)
        ax.axvline(0, color=mudo, lw=0.8)

    rc = {"font.size": 9, "text.color": tinta, "axes.edgecolor": grade, "axes.labelcolor": mudo,
          "xtick.color": mudo, "ytick.color": tinta, "axes.spines.top": False, "axes.spines.right": False}
    with plt.rc_context(rc):
        if tipo in ("barras_agrupadas", "variacao"):
            grupos = list(dict.fromkeys(d["grupo"]))
            linhas = [int((d["grupo"] == g).sum()) for g in grupos]
            fig, axes = plt.subplots(len(grupos), 1, squeeze=False, figsize=(8, 1.0 + sum(linhas) * 0.34 + 0.9 * len(grupos)),
                                     gridspec_kw={"height_ratios": linhas}, layout="constrained")
            vmax, vmin = float(d["valor"].max()), float(d["valor"].min())
            xlim = (min(0.0, vmin) * 1.45, max(0.0, vmax) * 1.45) if tipo == "variacao" else (0, vmax * 1.2)
            for ax, g in zip(axes[:, 0], grupos):
                sub = d[d["grupo"] == g]
                sub = sub.reindex(sub["valor"].abs().sort_values(ascending=False).index) if tipo == "variacao" \
                    else sub.sort_values("valor", ascending=False)
                barras(ax, sub, (lambda v: roxo if v >= 0 else ouro) if tipo == "variacao" else (lambda v: roxo), xlim)
                ax.set_title(esc(g), loc="left", fontweight="bold", fontsize=10)
            axes[-1, 0].set_xlabel(esc(eixo))
            if tipo == "variacao":
                fig.legend(handles=[Patch(color=roxo, label="Concorrente mais caro"), Patch(color=ouro, label="Concorrente mais barato")],
                           loc="outside lower center", ncol=2, frameon=False)
        elif tipo == "barras_h":
            sub = d.sort_values("valor", ascending=False)
            fig, ax = plt.subplots(figsize=(8, 0.9 + len(sub) * 0.5))
            barras(ax, sub, lambda v: roxo, (0, float(d["valor"].max()) * 1.2))
            ax.set_xlabel(esc(eixo))
        elif tipo == "linha":
            fig, ax = plt.subplots(figsize=(8, 3.6))
            ax.plot(d["data"], d["valor"], color=roxo, lw=2.2, marker="o")
            ax.fill_between(d["data"], d["valor"], float(d["valor"].min()), color=roxo, alpha=0.12)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
            ax.set_ylabel(esc(eixo))
            ax.grid(axis="y", color=grade)
            if len(d) <= 12:
                for x, y, t in zip(d["data"], d["valor"], d["texto"]):
                    ax.annotate(esc(t), (x, y), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8)
        elif tipo == "pizza":
            cores = {"Farmazids mais barata": roxo, "Preço similar": ouro, "Farmazids mais cara": tinta}
            total = float(d["valor"].sum()) or 1.0
            fig, ax = plt.subplots(figsize=(6.6, 3.6))
            fatias, _ = ax.pie(d["valor"], colors=[cores.get(r, mudo) for r in d["rotulo"]], startangle=90,
                               counterclock=False, wedgeprops=dict(width=0.38, edgecolor="white", linewidth=2))
            ax.legend(fatias, [f"{esc(r)}: {esc(t)} ({v / total * 100:.0f}%)" for r, t, v in zip(d["rotulo"], d["texto"], d["valor"])],
                      loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)
        else:  # barras_v
            paleta = ["#6d3fc0", "#1c1c1e", "#a98ee0", "#676768", "#c7b5ec", "#303033"]
            fig, ax = plt.subplots(figsize=(8, 3.6))
            ax.bar([esc(cortar(x, 20)) for x in d["rotulo"]], d["valor"], color=[paleta[i % 6] for i in range(len(d))])
            for i, t in enumerate(d["texto"]):
                ax.text(i, float(d["valor"].iloc[i]), esc(t), ha="center", va="bottom", fontsize=9, fontweight="bold")
            ax.set_ylabel(esc(eixo))
            ax.grid(axis="y", color=grade)
            ax.set_axisbelow(True)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)
    return buf.getvalue()


def gerar_pdf_insights() -> bytes:
    """Monta o PDF (A4 paisagem): capa + uma página por indicador, com gráfico, dados e análise."""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    roxo, tinta, mudo, grade = colors.HexColor("#6d3fc0"), colors.HexColor("#1c1c1e"), colors.HexColor("#676768"), colors.HexColor("#e6e3ee")
    try:
        from zoneinfo import ZoneInfo
        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    except Exception:
        agora = datetime.now()
    quando = agora.strftime("%d/%m/%Y às %H:%M")

    capa_t = ParagraphStyle("capa_t", fontName="Helvetica-Bold", fontSize=34, leading=40, textColor=tinta)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=tinta, spaceAfter=10)
    rotulo = ParagraphStyle("rot", fontName="Helvetica", fontSize=8.5, leading=11, textColor=roxo, spaceAfter=2)
    corpo = ParagraphStyle("corpo", fontName="Helvetica", fontSize=10.5, leading=15, textColor=tinta)
    peq = ParagraphStyle("peq", fontName="Helvetica", fontSize=8.5, leading=11, textColor=tinta)
    peq_b = ParagraphStyle("peq_b", parent=peq, fontName="Helvetica-Bold", textColor=roxo)

    P = lambda t, st_=corpo: Paragraph(escape(_pdf_texto(t)).replace("\n", "<br/>"), st_)

    def imagem(png: bytes, max_w: float, max_h: float):
        iw, ih = ImageReader(io.BytesIO(png)).getSize()
        k = min(max_w / iw, max_h / ih)
        return Image(io.BytesIO(png), width=iw * k, height=ih * k)

    def tabela_simples(cab: list, linhas: list, larguras: list):
        dados = [[Paragraph(escape(_pdf_texto(c)), peq_b) for c in cab]] + \
                [[Paragraph(escape(_pdf_texto(c)), peq) for c in l] for l in linhas]
        t = Table(dados, colWidths=larguras, repeatRows=1)
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, grade), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
        return t

    def moldura(canvas, doc):
        w, h = landscape(A4)
        canvas.saveState()
        canvas.setFillColor(roxo)
        canvas.rect(0, h - 0.3 * cm, w, 0.3 * cm, stroke=0, fill=1)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(mudo)
        canvas.drawString(1.5 * cm, 0.9 * cm, _pdf_texto(f"{BOT_NAME} · Farmazids · gerado em {quando}"))
        canvas.drawRightString(w - 1.5 * cm, 0.9 * cm, f"Página {doc.page}")
        canvas.restoreState()

    historia = []
    # ----- capa -----
    caminho = Path(__file__).parent / "logo_farmazids.png"
    if caminho.exists():
        logo = imagem(caminho.read_bytes(), 9 * cm, 2.6 * cm)
        logo.hAlign = "LEFT"
        historia += [logo, Spacer(1, 1.2 * cm)]
    historia += [Paragraph("PAINEL DE PREÇOS", rotulo), Paragraph(f"Insights do {BOT_NAME}", capa_t), Spacer(1, 0.4 * cm),
                 P(f"Gerado em {quando}", corpo), Spacer(1, 1 * cm), Paragraph("INDICADORES DESTE RELATÓRIO", rotulo)]
    historia += [P(f"{i}. {sp['titulo']}", corpo) for i, sp in enumerate(INSIGHTS, 1)]
    historia += [Spacer(1, 1 * cm),
                 P("Os indicadores são gerados a partir das bases de preços dos concorrentes e do histórico de vendas da "
                   "Farmazids, por consulta em linguagem natural. Os valores podem variar entre atualizações.", peq)]

    # ----- um indicador por página -----
    for i, spec in enumerate(INSIGHTS, 1):
        historia += [PageBreak(), Paragraph(f"INDICADOR {i} DE {len(INSIGHTS)}", rotulo), P(spec["titulo"], h1)]
        try:
            r = run_insight(spec["pergunta"])
        except RuntimeError as exc:
            historia.append(P(f"Indicador indisponível no momento: {exc}"))
            continue
        bruto = rows_to_df(r.get("rows") or [])
        if spec["tipo"] == "tabela":
            d = None
            if bruto is not None and bruto.shape[1] >= 4:
                d = bruto.iloc[:, :4].copy()
                d.columns = ["concorrente", "produto", "categoria", "preco"]
                d["preco"] = pd.to_numeric(d["preco"], errors="coerce")
            if d is None or d.empty:
                historia.append(P("Sem dados para este indicador no momento."))
            else:
                for nome, sub in d.groupby("concorrente", sort=True):
                    historia += [P(f"Presente na {nome}, ausente na Farmazids", peq_b), Spacer(1, 0.15 * cm),
                                 tabela_simples(["Produto", "Categoria", "Preço no pix"],
                                                [[x.produto, x.categoria, fmt_valor(x.preco, "dinheiro")] for x in sub.head(5).itertuples()],
                                                [14 * cm, 6 * cm, 4 * cm]), Spacer(1, 0.4 * cm)]
        else:
            d = padronizar(bruto, spec)
            if d is None:
                historia.append(P("Sem dados para este indicador no momento."))
            else:
                if "grupo" in d.columns:
                    cab = [spec.get("nome_grupo", "Farmácia"), spec.get("nome_item", "Produto"), spec["eixo"]]
                    linhas = [[x.grupo, x.rotulo, x.texto] for x in d.head(14).itertuples()]
                    larg = [2.6 * cm, 4.6 * cm, 2.4 * cm]
                elif "data" in d.columns:
                    cab = ["Dia", spec["eixo"]]
                    linhas = [[x.data.strftime("%d/%m/%Y"), x.texto] for x in d.head(14).itertuples()]
                    larg = [4 * cm, 5.6 * cm]
                else:
                    cab = [spec.get("nome_item", "Item"), spec["eixo"]]
                    linhas = [[x.rotulo, x.texto] for x in d.head(14).itertuples()]
                    larg = [6.2 * cm, 3.4 * cm]
                try:
                    grafico = imagem(grafico_pdf(d, spec), 15.4 * cm, 11.2 * cm)
                except Exception:
                    grafico = P("Não foi possível desenhar o gráfico; os dados estão na tabela ao lado.", peq)
                bloco = Table([[grafico, tabela_simples(cab, linhas, larg)]], colWidths=[15.8 * cm, 9.6 * cm])
                bloco.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
                historia += [bloco, Spacer(1, 0.3 * cm)]

    saida = io.BytesIO()
    doc = SimpleDocTemplate(saida, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.4 * cm, bottomMargin=1.6 * cm, title=f"Insights do {BOT_NAME}", author="Farmazids")
    doc.build(historia, onFirstPage=moldura, onLaterPages=moldura)
    return saida.getvalue()


def render_insights():
    c_txt, c_img = st.columns([1.3, 1], gap="large", vertical_alignment="center")
    with c_txt:
        st.markdown(
            f'<span class="g-tag">Painel de preços</span>'
            f'<h1 class="g-title" style="font-size:clamp(40px,6vw,64px)">Insights do <em>{BOT_NAME}</em></h1>'
            f'<p class="g-sub">Indicadores gerados a partir dos dados de preços e vendas. '
            f'Os resultados são guardados por 1 hora.</p>',
            unsafe_allow_html=True,
        )
        b1, b2, b3 = st.columns([1, 0.9, 1.1])
        if b1.button("Atualizar dados", key="refresh_insights"):
            run_insight.clear()
            st.session_state.pop("pdf_insights", None)
            st.rerun()
        if b2.button("Gerar PDF", key="gerar_pdf"):
            try:
                with carregando("Gerando o PDF..."):
                    st.session_state.pdf_insights = gerar_pdf_insights()
            except ImportError:
                st.error("Para gerar o PDF, instale: py -m pip install reportlab matplotlib")
            except Exception as exc:
                st.error(f"Não foi possível gerar o PDF: {exc}")
        if st.session_state.get("pdf_insights"):
            b3.download_button("Baixar PDF", st.session_state.pdf_insights, key="baixar_pdf", type="primary",
                               file_name=f"insights_zids_{datetime.now():%Y-%m-%d}.pdf", mime="application/pdf")
    with c_img:
        # mesma moldura (card branco + área cinza) do hero da página Chatbot
        st.markdown(
            f'<div class="g-mock" style="min-height:0"><div class="ph" style="flex:none;aspect-ratio:16/9;min-height:0">'
            f'<img src="app/static/ZIDS_INSIGHTS.gif" alt="{BOT_NAME}" style="object-position:50% 50%"></div></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div style="height:32px"></div>', unsafe_allow_html=True)
    cols = st.columns(2)
    for i, spec in enumerate(INSIGHTS):
        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(f'<div class="g-label">{spec["titulo"]}</div>', unsafe_allow_html=True)
                try:
                    with carregando("Consultando os dados..."):
                        r = run_insight(spec["pergunta"])
                except RuntimeError as exc:
                    st.warning(str(exc))
                    continue
                bruto = rows_to_df(r.get("rows") or [])
                if spec["tipo"] == "tabela":
                    if not render_tabela(bruto, spec):
                        st.info("Sem dados para este indicador no momento.")
                    with st.expander("Ver consulta"):
                        if r.get("content"):
                            st.markdown(md_seguro(r["content"]))
                        st.code(r["sql"], language="sql")
                    continue
                d = padronizar(bruto, spec)
                if d is None:
                    st.info("Sem dados para este indicador no momento.")
                else:
                    st.altair_chart(grafico_fixo(d, spec), use_container_width=(spec["tipo"] != "barras_agrupadas"),
                                    theme=None if DARK else "streamlit")
                with st.expander("Ver tabela e consulta"):
                    if r.get("content"):
                        st.markdown(md_seguro(r["content"]))
                    if d is not None:
                        tabela = d.drop(columns=["valor"]).rename(columns={"texto": spec["eixo"], "rotulo": spec.get("nome_item", "Item"),
                                                                           "grupo": spec.get("nome_grupo", "Farmácia"), "data": "Dia"})
                        if "Dia" in tabela:
                            tabela["Dia"] = tabela["Dia"].dt.strftime("%d/%m/%Y")
                        st.dataframe(tabela, use_container_width=True, hide_index=True)
                    st.code(r["sql"], language="sql")



if st.session_state.page == "insights":
    render_insights()
    st.stop()


# ---------- Página: Dados (amostras das tabelas que o Zids consegue consultar) ----------
# Tabelas FIXAS de exemplo (5 produtos por base). Valores fictícios: servem só para mostrar
# quais colunas existem em cada base. Não geram consulta à state machine.
_PRODUTOS = [
    # nome, categoria, laboratório, gtin, FarmaPonte (sem desc., pix), VeraCruz (sem desc., pix), preço Farmazids
    ("Glifage XR 500mg 30 comprimidos de liberação prolongada", "Diabetes", "Merck", "7891234500011", (12.90, 11.61), (12.20, 11.59), 12.50),
    ("Dipirona Sódica 500mg 30 comprimidos", "Dor e febre", "EMS", "7891234500028", (14.90, 13.41), (15.50, 14.73), 14.20),
    ("Losartana Potássica 50mg 30 comprimidos", "Pressão alta", "Medley", "7891234500035", (9.90, 8.91), (10.40, 9.88), 9.50),
    ("Omeprazol 20mg 28 cápsulas", "Estômago", "Eurofarma", "7891234500042", (19.90, 17.91), (18.90, 17.96), 18.50),
    ("Vitamina D3 2000UI 60 cápsulas", "Vitaminas e suplementos", "Vitamedic", "7891234500059", (39.90, 35.91), (42.00, 39.90), 38.00),
]


def _exemplo_concorrente(idx: int, farmacia: str, prefixo: str, com_extras: bool) -> pd.DataFrame:
    linhas = []
    for i, (nome, cat, lab, gtin, fp, vc, _) in enumerate(_PRODUTOS):
        sem, pix = (fp if idx == 0 else vc)
        parcelas = 6 if sem > 30 else 3
        linha = {
            "nome_farmacia": farmacia,
            "data_extracao": "16/10/2026 12:11",
            "nome": nome,
            "categoria": cat,
            "disponibilidade": "Indisponível" if i == 3 else "Disponível",
            "preco_sem_desconto": sem,
            "preco_desconto_pix": pix,
            "desconto_pct": round((1 - pix / sem) * 100, 1),
            "laboratorio": lab,
        }
        if com_extras:
            linha["cashback"] = [0.0, 1.0, 0.0, 0.0, 2.0][i]
        linha.update({
            "desconto_laboratorio": [0.0, 0.0, 10.0, 0.0, 0.0][i],
            "gtin": gtin,
            "codigo_interno": f"{prefixo}-{10230 + i}",
            "numero_parcelas": f"{parcelas}x",
            "valor_parcelas": round(sem / parcelas, 2),
        })
        if com_extras:
            linha["preco_total_parcelado"] = sem
        linha["url_produto"] = f"https://www.exemplo.com.br/produto/{gtin}"
        linhas.append(linha)
    return pd.DataFrame(linhas)


EXEMPLOS = {
    "farmaponte_tratado": _exemplo_concorrente(0, "FarmaPonte", "FP", com_extras=True),
    "veracruz_tratado": _exemplo_concorrente(1, "Drogaria Vera Cruz", "VC", com_extras=False),
    "medicamentos_farmazids": pd.DataFrame([
        {"nome_farmacia": "Farmazids", "data_extracao": "16/10/2026 12:00", "gtin": p[3], "nome": p[0], "preco": p[6]}
        for p in _PRODUTOS
    ]),
    "historico_farmazids": pd.DataFrame([
        {"id_venda": f"V-{100200 + i}", "farmacia": ["Farmazids Loja 01", "Farmazids Loja 02"][i % 2], "gtin": p[3],
         "data_venda": f"2026-09-{30 - i:02d} 1{i}:42:10", "quantidade_vendida": float([2, 1, 3, 1, 4][i])}
        for i, p in enumerate(_PRODUTOS)
    ]),
}


DADOS = [
    {
        "nome": "Extração FarmaPonte",
        "origem": "FarmaPonte",
        "tabela": "farmaponte_tratado",
        "descricao": "Preços coletados no site da concorrente FarmaPonte (uma linha por produto em cada coleta).",
        "resumo": "coletas",
        "resumo_pergunta": "Para cada dia de coleta da tabela farmaponte_tratado (considere todas as coletas, sem "
                           "filtro de data), conte os produtos distintos por gtin e as categorias distintas. Agrupe "
                           "por date(date_parse(data_extracao, '%d/%m/%Y %H:%i')) e ordene do dia mais recente para o "
                           "mais antigo. Devolva exatamente 3 colunas, nesta ordem e com estes apelidos: "
                           "dia, produtos, categorias.",
    },
    {
        "nome": "Extração VeraCruz",
        "origem": "VeraCruz",
        "tabela": "veracruz_tratado",
        "descricao": "Preços coletados no site da concorrente Drogaria VeraCruz (uma linha por produto em cada coleta).",
        "resumo": "coletas",
        "resumo_pergunta": "Para cada dia de coleta da tabela veracruz_tratado (considere todas as coletas, sem "
                           "filtro de data), conte os produtos distintos por gtin e as categorias distintas. Agrupe "
                           "por date(date_parse(data_extracao, '%d/%m/%Y %H:%i')) e ordene do dia mais recente para o "
                           "mais antigo. Devolva exatamente 3 colunas, nesta ordem e com estes apelidos: "
                           "dia, produtos, categorias.",
    },
    {
        "nome": "Catálogo Farmazids",
        "origem": "Farmazids",
        "tabela": "medicamentos_farmazids",
        "descricao": "Catálogo e preços da própria Farmazids (uma linha por produto em cada coleta).",
        "resumo": "coletas_sem_categoria",
        "resumo_pergunta": "Para cada dia de coleta da tabela medicamentos_farmazids (considere todas as coletas, sem "
                           "filtro de data), conte os produtos distintos por gtin. Agrupe por "
                           "date(date_parse(data_extracao, '%d/%m/%Y %H:%i')) e ordene do dia mais recente para o "
                           "mais antigo. Devolva exatamente 2 colunas, nesta ordem e com estes apelidos: "
                           "dia, produtos.",
    },
    {
        "nome": "Histórico de vendas",
        "origem": "Farmazids",
        "tabela": "historico_farmazids",
        "descricao": "Histórico de vendas da Farmazids, por farmácia, produto (gtin) e data.",
        "resumo": "vendas",
        "resumo_pergunta": "Para cada mês da tabela historico_farmazids (considere todo o histórico, sem filtro de "
                           "data), conte o total de vendas (COUNT(*)), os produtos distintos por gtin e as farmácias "
                           "distintas. Agrupe por date_format(data_venda, '%Y-%m') e ordene do mês mais recente para "
                           "o mais antigo. Devolva exatamente 4 colunas, nesta ordem e com estes apelidos: "
                           "mes, vendas, produtos, farmacias.",
    },
]


def render_resumo(item: dict):
    """Resumo da base (quantidades e datas das extrações), lido por posição das colunas."""
    st.markdown(
        """
<style>
.g-stats.g-compact { margin-bottom: var(--spacing-24); }
@media (min-width: 901px) { .g-stats.g-n4 { grid-template-columns: repeat(4, 1fr); } }
.g-chips { display: flex; flex-wrap: wrap; gap: var(--spacing-8); margin: var(--spacing-8) 0 var(--spacing-32); }
.g-chip { border: 1px solid rgba(128,128,128,.35); border-radius: var(--radius-tags); padding: var(--spacing-4) var(--spacing-12);
  font-size: var(--text-caption); letter-spacing: 0; color: var(--color-graphite); }
</style>
""",
        unsafe_allow_html=True,
    )
    try:
        with carregando("Calculando o resumo..."):
            r = run_insight(item["resumo_pergunta"])
    except RuntimeError:
        st.info("Resumo indisponível no momento.")
        return
    bruto = rows_to_df(r.get("rows") or [])
    tipo, origem = item["resumo"], item["origem"]
    nomes = {"coletas": ["dia", "produtos", "categorias"], "coletas_sem_categoria": ["dia", "produtos"],
             "vendas": ["mes", "vendas", "produtos", "farmacias"]}[tipo]
    if bruto is None or bruto.shape[1] < len(nomes):
        st.info("Resumo indisponível no momento.")
        return
    d = bruto.iloc[:, : len(nomes)].copy()
    d.columns = nomes
    for c in nomes[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    n = lambda v: fmt_valor(v, "int")

    if tipo == "vendas":
        d["data"] = pd.to_datetime(d["mes"].astype(str) + "-01", errors="coerce")
        rotulo, ordem_fmt, rotulo_datas = "mes", "%m/%Y", "Meses com vendas"
        total = d["vendas"].sum()
    else:
        d["data"] = pd.to_datetime(d["dia"], errors="coerce")
        ordem_fmt, rotulo_datas = "%d/%m/%Y", "Datas das extrações"
    d = d.dropna(subset=["data"]).sort_values("data", ascending=False)
    if d.empty:
        st.info("Resumo indisponível no momento.")
        return
    ult, ini = d.iloc[0], d.iloc[-1]
    f_ult, f_ini = ult["data"].strftime(ordem_fmt), ini["data"].strftime(ordem_fmt)
    k = len(d)

    if tipo == "vendas":
        frase = (f"Há <b>{n(total)}</b> vendas registradas em <b>{k}</b> meses, de {f_ini} a {f_ult}. "
                 f"No mês mais recente ({f_ult}) foram vendidos <b>{n(ult['produtos'])}</b> produtos diferentes "
                 f"em <b>{n(ult['farmacias'])}</b> farmácias.")
        cartoes = [("Vendas registradas", n(total), f"em {k} meses"),
                   ("Produtos vendidos", n(ult["produtos"]), f"no mês {f_ult}"),
                   ("Farmácias", n(ult["farmacias"]), f"no mês {f_ult}"),
                   ("Último mês", f_ult, "com vendas")]
    else:
        cat = f" em <b>{n(ult['categorias'])}</b> categorias" if tipo == "coletas" else ""
        frase = (f"Na <b>{origem}</b> há <b>{n(ult['produtos'])}</b> medicamentos extraídos{cat} na coleta mais "
                 f"recente ({f_ult}). Foram feitas <b>{k}</b> coletas, de {f_ini} a {f_ult}.")
        cartoes = [("Medicamentos", n(ult["produtos"]), "na última coleta")]
        if tipo == "coletas":
            cartoes.append(("Categorias", n(ult["categorias"]), "na última coleta"))
        cartoes += [("Coletas feitas", n(k), f"de {f_ini} a {f_ult}"), ("Última coleta", f_ult, "dado mais recente")]

    html = "".join(
        f'<div class="g-stat"><div class="g-label">{a}</div><div class="g-num">{b}</div><div class="g-cap">{c}</div></div>'
        for a, b, c in cartoes
    )
    datas = [x.strftime(ordem_fmt) for x in d["data"]]
    chips = "".join(f'<span class="g-chip">{x}</span>' for x in datas[:14])
    if len(datas) > 14:
        chips += f'<span class="g-chip">+ {len(datas) - 14} anteriores</span>'
    st.markdown(
        f'<p class="g-cap" style="font-size:var(--text-body);margin-bottom:16px">{frase}</p>'
        f'<div class="g-stats g-compact g-n{len(cartoes)}">{html}</div>'
        f'<div class="g-label">{rotulo_datas}</div><div class="g-chips">{chips}</div>',
        unsafe_allow_html=True,
    )


def render_dados():
    st.markdown(
        '<span class="g-tag">Catálogo de dados</span>'
        f'<h1 class="g-title" style="font-size:clamp(40px,6vw,64px)">Dados do <em>{BOT_NAME}</em></h1>'
        '<p class="g-sub">Um exemplo de cada base que o assistente consegue consultar. '
        'Os resultados são guardados por 1 hora.</p>',
        unsafe_allow_html=True,
    )
    if st.button("Atualizar dados", key="refresh_dados"):
        run_insight.clear()
        st.rerun()
    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    escolha = st.radio("Base de dados", [d["nome"] for d in DADOS], horizontal=True,
                       label_visibility="collapsed", key="dados_tabela")
    item = next(d for d in DADOS if d["nome"] == escolha)
    st.markdown(
        f'<div class="g-label" style="margin-top:16px">{item["tabela"]}</div>'
        f'<p class="g-cap" style="margin:4px 0 16px">{item["descricao"]}</p>',
        unsafe_allow_html=True,
    )
    render_resumo(item)
    df = EXEMPLOS[item["tabela"]]
    st.markdown(
        f'<p class="g-cap">Exemplo com {len(df)} produtos e {len(df.columns)} colunas. '
        f'Os valores são fictícios e servem só para mostrar o que é possível consultar.</p>',
        unsafe_allow_html=True,
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


if st.session_state.page == "dados":
    render_dados()
    st.stop()


if "messages" not in st.session_state:
    st.session_state.messages = []

clicked = None
if not st.session_state.messages:
    for i, text in enumerate(SUGGESTIONS):
        if st.button(text, key=f"sug_{i}"):
            clicked = text

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        render_message(m)

prompt = st.chat_input("Escreva sua pergunta") or clicked
if prompt:
    historico = montar_historico(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(md_seguro(prompt))
    with st.chat_message("assistant"):
        with carregando("Consultando os dados..."):
            reply = generate_reply(prompt, historico)
            reply["chart"] = wants_chart(prompt)
            reply["pergunta"] = prompt
        render_message(reply)
    st.session_state.messages.append({"role": "assistant", **reply})
    if clicked:
        st.rerun()

