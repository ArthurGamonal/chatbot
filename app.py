import asyncio
import base64
import contextlib
import functools
import hashlib
import hmac
import io
import json
import math
import os
import re
import threading
import time
import unicodedata
import uuid
import wave
from array import array
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html import escape as esc
from pathlib import Path

import altair as alt
import boto3
import pandas as pd
import streamlit as st
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

try:  # pip install amazon-transcribe  (só necessário para perguntar por voz)
    from amazon_transcribe.client import TranscribeStreamingClient
    from amazon_transcribe.handlers import TranscriptResultStreamHandler
except ImportError:
    TranscribeStreamingClient = None
    TranscriptResultStreamHandler = object

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

st.set_page_config(page_title=f"{BOT_NAME}", page_icon="💜", layout="wide", initial_sidebar_state="expanded")

# ---------- Modo escuro ----------
if "dark" not in st.session_state:
    st.session_state.dark = st.query_params.get("tema") == "escuro"
DARK = bool(st.session_state.dark)
# Cores usadas nos gráficos (Altair não lê as variáveis CSS)
INK = "#f2f0f7" if DARK else "#1c1c1e"
MUTED = "#a9a4b8" if DARK else "#676768"
GRID = "#2f2640" if DARK else "#eff1f6"
SURFACE = "#1c1528" if DARK else "#faf8f5"
# GIF do Zids: versão noturna no modo escuro (os dois arquivos ficam na pasta static)
ZIDS_GIF = "app/static/ZIDS_dark.gif" if DARK else "app/static/ZIDS.gif"
ZIDS_INSIGHTS_GIF = "app/static/ZIDS_INSIGHTS_dark.gif" if DARK else "app/static/ZIDS_INSIGHTS.gif"
# GIF exibido na tela de login quando usuário ou senha estão incorretos (arquivo na pasta static)
SENHA_ERRADA_GIF = "app/static/SENHA_ERRADA.gif"
# Segundo GIF da senha errada: aparece ao lado do primeiro (arquivo na pasta static)
SENHA_ERRADA_GIF_2 = "app/static/SENHA_ERRADA_2.gif"

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
/* A barra de chats é recolhida/aberta pelos botões próprios abaixo (os controles nativos ficam escondidos) */
[data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] { display: none !important; }
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
  padding: var(--spacing-8) var(--spacing-16); font-size: var(--text-body-sm); letter-spacing: var(--tracking-body-sm); }

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
  border-radius: var(--radius-xl); padding: var(--spacing-12) var(--spacing-24);
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
  border-radius: var(--radius-xl); padding: var(--spacing-12) var(--spacing-24);
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

/* Botões do topo e do hero: retângulos de cantos arredondados (em vez de pílula) */
.g-btn { border-radius: var(--radius-xl); }
.st-key-nav_chat button, .st-key-nav_insights button, .st-key-nav_dados button, .st-key-nav_theme button {
  border-radius: var(--radius-xl);
}

/* Barra lateral de chats (retrátil): um item por conversa, o ativo em destaque */
[data-testid="stSidebar"] { background: var(--surface-card) !important; border-right: 1px solid rgba(128,128,128,.22); }
[class*="st-key-chatsel_"] button { border: none; background: transparent; padding: var(--spacing-8) var(--spacing-12); }
[class*="st-key-chatsel_"] button > div { justify-content: flex-start; width: 100%; }
[class*="st-key-chatsel_"] button p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; width: 100%; }
[class*="st-key-chatsel_"] button:hover { background: rgba(128,128,128,.16); }
[class*="st-key-chatsel_on_"] button, [class*="st-key-chatsel_on_"] button:hover { background: rgba(109,63,192,.18); }
[class*="st-key-chatsel_on_"] button p { font-weight: var(--font-weight-semibold); }
[class*="st-key-chatdel_"] button { border: none; background: transparent; padding: var(--spacing-4); min-height: 0; color: var(--color-slate-mid); }
[class*="st-key-chatdel_"] button:hover { background: rgba(214,69,69,.16); color: #d64545; }
.st-key-abrir_chats { position: fixed; top: 12px; left: 12px; z-index: 1000000; width: auto !important; }
.st-key-abrir_chats button, .st-key-fechar_chats button {
  border: 1px solid var(--color-gold-deep); background: var(--surface-card); border-radius: var(--radius-xl);
  padding: 6px 14px; min-height: 0;
}
.st-key-abrir_chats button p, .st-key-fechar_chats button p { color: var(--color-gold-deep); font-size: 16px; }
.st-key-abrir_chats button:hover, .st-key-fechar_chats button:hover { background: rgba(196,160,84,.18); border-color: var(--color-gold-deep); }
/* Aba Boas-vindas do topo, em dourado como as demais */
.st-key-nav_inicio button { background: transparent; border: 1px solid var(--color-gold-deep); box-shadow: none; border-radius: var(--radius-xl); }
.st-key-nav_inicio button p { color: var(--color-gold-deep); }
.st-key-nav_inicio button:hover { background: rgba(196,160,84,.15); border-color: var(--color-gold-deep); }
.st-key-nav_inicio button[kind="primary"], .st-key-nav_inicio button[data-testid="stBaseButton-primary"] {
  background: var(--color-gold); border-color: var(--color-gold); box-shadow: var(--shadow-subtle-3), var(--shadow-subtle-4); }
.st-key-nav_inicio button[kind="primary"] p, .st-key-nav_inicio button[data-testid="stBaseButton-primary"] p { color: var(--color-pine-shadow); }
/* Aba Simulador do topo, em dourado como as demais */
.st-key-nav_simulador button { background: transparent; border: 1px solid var(--color-gold-deep); box-shadow: none; border-radius: var(--radius-xl); }
.st-key-nav_simulador button p { color: var(--color-gold-deep); }
.st-key-nav_simulador button:hover { background: rgba(196,160,84,.15); border-color: var(--color-gold-deep); }
.st-key-nav_simulador button[kind="primary"], .st-key-nav_simulador button[data-testid="stBaseButton-primary"] {
  background: var(--color-gold); border-color: var(--color-gold); box-shadow: var(--shadow-subtle-3), var(--shadow-subtle-4); }
.st-key-nav_simulador button[kind="primary"] p, .st-key-nav_simulador button[data-testid="stBaseButton-primary"] p { color: var(--color-pine-shadow); }
/* Aba Tendências do topo, em dourado como as demais */
.st-key-nav_tendencias button { background: transparent; border: 1px solid var(--color-gold-deep); box-shadow: none; border-radius: var(--radius-xl); }
.st-key-nav_tendencias button p { color: var(--color-gold-deep); }
.st-key-nav_tendencias button:hover { background: rgba(196,160,84,.15); border-color: var(--color-gold-deep); }
.st-key-nav_tendencias button[kind="primary"], .st-key-nav_tendencias button[data-testid="stBaseButton-primary"] {
  background: var(--color-gold); border-color: var(--color-gold); box-shadow: var(--shadow-subtle-3), var(--shadow-subtle-4); }
.st-key-nav_tendencias button[kind="primary"] p, .st-key-nav_tendencias button[data-testid="stBaseButton-primary"] p { color: var(--color-pine-shadow); }
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
.g-erro-gif { display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: var(--spacing-16); margin-top: var(--spacing-16); }
.g-erro-gif img { height: 240px; width: auto; max-width: 100%; object-fit: contain; border-radius: var(--radius-cards); }
[data-testid="stForm"] {
  border: 1px solid rgba(128,128,128,.25); border-radius: var(--radius-cards);
  padding: var(--card-padding); background: var(--color-pure-white);
  box-shadow: var(--shadow-subtle-2), var(--shadow-subtle);
}
[data-testid="stForm"] input { border-radius: var(--radius-inputs); }
[data-testid="stFormSubmitButton"] button {
  border-radius: var(--radius-xl); padding: var(--spacing-12) var(--spacing-24);
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
                st.session_state.usuario = usuario.strip()
                st.session_state.page = "inicio"  # a primeira tela depois da senha é a de boas-vindas
                st.rerun()
            time.sleep(1)  # atrasa tentativas erradas
            st.error("Usuário ou senha incorretos.")
            st.markdown(
                f'<div class="g-erro-gif"><img src="{SENHA_ERRADA_GIF}" alt="Senha incorreta">'
                f'<img src="{SENHA_ERRADA_GIF_2}" alt="Senha incorreta"></div>',
                unsafe_allow_html=True,
            )


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
    f'<div class="g-mock"><div class="ph"><img src="{ZIDS_GIF}" alt="{BOT_NAME}"></div>{bubbles}</div></div>'
    f'<div id="resultados" class="g-stats">{stats}</div>'
    f'<div id="conversar"><h2 class="g-section">Converse com o {BOT_NAME}</h2>'
    f'<p class="g-cap" style="margin-bottom:24px">Escolha uma pergunta ou escreva a sua.</p></div>'
)

if "page" not in st.session_state:
    st.session_state.page = "chat"

# ---------- Topo: logo + botões de troca de página ----------
c_logo, c_ini, c_chat, c_ins, c_sim, c_tend, c_dados, c_tema = st.columns([1.25, 1.3, 1.3, 1.3, 1.3, 1.4, 1.3, 0.85], vertical_alignment="center")
c_logo.markdown(f'<div class="g-logo"><b>●</b> {BOT_NAME}</div>', unsafe_allow_html=True)
for col, key, label in ((c_ini, "inicio", "Boas-vindas"), (c_chat, "chat", "Chatbot"),
                        (c_ins, "insights", "Insights"), (c_sim, "simulador", "Simulador"), (c_tend, "tendencias", "Tendências"), (c_dados, "dados", "Dados")):
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
@functools.lru_cache(maxsize=None)  # thread-safe; funciona também fora do Streamlit (threads dos insights)
def get_sfn():
    # Credenciais vêm da cadeia padrão do boto3 (variáveis de ambiente, ~/.aws, IAM role)
    return boto3.client(
        "stepfunctions",
        region_name=AWS_REGION,
        config=Config(read_timeout=280, connect_timeout=10, retries={"max_attempts": 1}),
    )


@functools.lru_cache(maxsize=None)
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
GOLD = "#c4a054"  # destaque da farmácia mais barata


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

# ---------- Quando e como desenhar o gráfico ----------

# Cor fixa de cada farmácia: assim a pessoa aprende "roxo = Farmazids" e vale para todo gráfico.
COR_FARMACIA = {"farmazids": PURPLE, "farmaponte": GOLD, "veracruz": "#9c98a8"}

# Trechos que indicam que a pessoa quer um gráfico. A comparação é feita sem acento
# e em minúsculas, então "Gráfico", "grafico" e "GRÁFICO" funcionam todos.
# Usamos "em barra" (e não só "barra") para não confundir com "código de barras".
PALAVRAS_GRAFICO = (
    "grafico", "chart", "plot", "visualizacao",       # pedido direto
    "em barra", "em linha", "em pizza", "em rosca",   # troca de tipo: "gere em barras"
    "ao longo", "evolucao", "mes a mes",              # perguntas de evolução no tempo
)


def _sem_acento(texto: str) -> str:
    """Põe em minúsculas e tira os acentos, para comparar textos sem depender da grafia."""
    # NFD separa a letra do acento (á vira a + ´); depois descartamos só os acentos (categoria "Mn")
    t = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def pediu_grafico(pergunta: str) -> bool:
    """True se a pergunta pede um gráfico (ou a troca do tipo dele)."""
    q = _sem_acento(pergunta)
    # any(...) é True se QUALQUER trecho da lista aparecer na pergunta
    return any(p in q for p in PALAVRAS_GRAFICO)


def wants_chart(pergunta: str) -> bool:
    return pediu_grafico(pergunta)


def tipo_pedido(pergunta: str):
    """Tipo citado na pergunta ('pizza', 'barras', 'linha') ou None, e aí o app escolhe sozinho."""
    q = _sem_acento(pergunta)
    if "pizza" in q or "rosca" in q:
        return "pizza"
    if "em barra" in q or "grafico de barra" in q:
        return "barras"
    if "em linha" in q or "grafico de linha" in q:
        return "linha"
    return None


def _formato_data(vals: pd.Series):
    """Descobre se a coluna é data em AAAA-MM-DD (dia/semana) ou AAAA-MM (mês). Devolve o formato ou None."""
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        # errors="coerce" troca o que não é data por NaT (vazio) em vez de dar erro
        if pd.to_datetime(vals, format=fmt, errors="coerce").notna().all():
            return fmt
    return None



def destaca_barato(pergunta: str) -> bool:
    """Perguntas sobre o menor preço ganham a barra mais barata em dourado."""
    q = pergunta.lower()
    return any(k in q for k in ("barat", "menor preço", "menor preco", "mais em conta", "mais econom", "mais econôm"))


def _tipo_marca(chart):
    try:
        mk = chart.mark
        return mk if isinstance(mk, str) else getattr(mk, "type", None)
    except Exception:
        return None


def build_chart(df: pd.DataFrame, pergunta: str):
    """Monta o gráfico Altair a partir do resultado; devolve None se não houver dados numéricos."""
    q = pergunta.lower()
    pedido = tipo_pedido(pergunta)
    df = df.copy()

    # 1) Classifica cada coluna do resultado como data, número ou texto
    col_data, fmt, col_num, col_txt = None, None, [], []
    for c in df.columns:
        vals = df[c].dropna().astype(str)
        if vals.empty:
            col_txt.append(c)
            continue
        formato = _formato_data(vals)
        nums = pd.to_numeric(vals, errors="coerce")
        # gtin e códigos parecem números, mas não servem como eixo y
        looks_like_id = vals.str.fullmatch(r"\d{8,}").all() or any(k in c.lower() for k in ("gtin", "codigo", "id_"))
        if col_data is None and formato:
            col_data, fmt = c, formato
        elif nums.notna().all() and not looks_like_id:
            col_num.append(c)
        else:
            col_txt.append(c)
    if not col_num:
        return None  # sem número não há o que desenhar

    # 2) A última coluna numérica é o valor (o SELECT deve trazer o valor por último)
    y = col_num[-1]
    valor = pd.to_numeric(df[y], errors="coerce")
    # Colunas de texto viram o rótulo (ex.: a farmácia). Se houver mais de uma, junta com " – "
    # valores vazios viram "Sem informação": no pandas novo eles seguem como número (NaN) e quebrariam o join
    rotulo = (df[col_txt].fillna("Sem informação").apply(lambda l: " – ".join(map(str, l)), axis=1)
              if col_txt else None)

    # 3) Há data: série no tempo (linhas ou barras agrupadas)
    if col_data is not None:
        d = pd.DataFrame({
            "x": pd.to_datetime(df[col_data], format=fmt, errors="coerce"),
            "valor": valor,
            "serie": rotulo if rotulo is not None else "Total",
        }).dropna(subset=["x", "valor"])
        if d.empty:
            return None

        # Rótulo do eixo em português: mês mostra mm/aaaa, semana ou dia mostra dd/mm
        fmt_rot = "%m/%Y" if fmt == "%Y-%m" else "%d/%m"
        d["periodo"] = d["x"].dt.strftime(fmt_rot)
        ordem = list(d.sort_values("x")["periodo"].drop_duplicates())  # ordem cronológica

        # Uma cor por série (farmácia); com uma série só, a legenda não é necessária
        series = list(dict.fromkeys(d["serie"]))
        escala = alt.Scale(
            domain=series,
            range=[COR_FARMACIA.get(s.lower(), PALETTE[i % len(PALETTE)]) for i, s in enumerate(series)],
        )
        cor = alt.Color("serie:N", title=None, scale=escala,
                        legend=alt.Legend(orient="bottom") if len(series) > 1 else None)
        dica = [alt.Tooltip("periodo:N", title="Período"), alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("valor:Q", title=y)]

        # Tipo: o que a pessoa pediu; senão, linha para muitos pontos e barras para poucos
        tipo = pedido if pedido in ("barras", "linha") else ("linha" if d["x"].nunique() > 12 else "barras")
        if tipo == "linha":
            return alt.Chart(d).mark_line(point=True, strokeWidth=2.5).encode(
                x=alt.X("x:T", title=None, axis=alt.Axis(format=fmt_rot, labelAngle=0)),
                y=alt.Y("valor:Q", title=y), color=cor, tooltip=dica,
            )
        barras = alt.Chart(d).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("periodo:O", sort=ordem, title=None, axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("valor:Q", title=y), color=cor, tooltip=dica,
        )
        if len(series) > 1:
            barras = barras.encode(xOffset=alt.XOffset("serie:N"))  # barras lado a lado por farmácia
        return barras

    # 4) Sem data: comparação entre itens (barras) ou pizza
    d = pd.DataFrame({"valor": valor})
    d["rotulo"] = rotulo if rotulo is not None else df.index.astype(str)
    ytitle = alt.Axis(title=y)
    if pedido == "pizza" and len(d) <= 8:
        return alt.Chart(d).mark_arc().encode(
            theta="valor:Q", color=alt.Color("rotulo:N", title=None, scale=alt.Scale(range=PALETTE))
        )
    barras = (
        alt.Chart(d)
        .mark_bar(color=PURPLE, cornerRadiusEnd=4)
        .encode(
            x=alt.X("rotulo:N", sort=None, title=None, axis=alt.Axis(labelAngle=-30, labelLimit=180)),
            y=alt.Y("valor:Q", axis=ytitle),
            tooltip=["rotulo", "valor"],
        )
    )
    if destaca_barato(q):  # o menor valor (mais barato) fica em dourado
        barras = barras.encode(color=alt.condition(
            alt.datum.valor == float(d["valor"].min()), alt.value(GOLD), alt.value(PURPLE)))
    return barras


def md_seguro(texto) -> str:
    """Escapa o cifrão: o Streamlit trata $...$ como fórmula e quebra textos com dois 'R$' no mesmo parágrafo."""
    return str(texto or "").replace("\\$", "$").replace("$", "\\$")


# ---------- Painel "Zids Intel": visual dos gráficos pedidos no chat ----------
# Todo gráfico pedido no chat sai neste painel (claro por padrão; escuro quando o modo escuro está ligado).
# Disponibilidade de produtos ganha o formato rosca + tabela por rede. Se algo der errado, o chat volta ao gráfico antigo.
# Paleta roxo + dourado (cada rede tem uma cor fixa)
PN_ROXO, PN_DOURADO, PN_LAVANDA = "#6d3fc0", "#c4a054", "#a98be0"
PN_ROXO_ESC, PN_OURO_ESC = "#4a2b86", "#8c6d2a"
PN_AZUL, PN_ROSA = PN_DOURADO, PN_LAVANDA  # FarmaPonte = dourado, Vera Cruz = lavanda
if DARK:
    PN_BG, PN_CARD, PN_LINHA = "#1c1528", "#241a33", "rgba(255,255,255,.10)"
    PN_TEXTO, PN_MUDO, PN_GRADE = "#f2f0f7", "#a9a4b8", "rgba(255,255,255,.08)"
    PN_TRILHO, PN_TAB_BG, PN_TAB_TX = "rgba(255,255,255,.10)", "#2e2342", "#e9ddff"
    PN_ROXO_TX, PN_OURO_TX = "#b99cf0", "#d9b866"
else:
    PN_BG, PN_CARD, PN_LINHA = "#ffffff", "#faf8f5", "rgba(35,26,51,.12)"
    PN_TEXTO, PN_MUDO, PN_GRADE = "#1c1c1e", "#676768", "rgba(35,26,51,.08)"
    PN_TRILHO, PN_TAB_BG, PN_TAB_TX = "rgba(35,26,51,.08)", "#f1ebfb", PN_ROXO_ESC
    PN_ROXO_TX, PN_OURO_TX = PN_ROXO_ESC, PN_OURO_ESC  # versões mais escuras, para texto legível no fundo claro
PN_PALETA = [PN_ROXO, PN_DOURADO, PN_LAVANDA, PN_OURO_ESC, PN_ROXO_ESC, "#b8b0c8"]
PN_REDES = {"farmazids": PN_ROXO, "farmaponte": PN_DOURADO, "veracruz": PN_LAVANDA}
PN_REDES_TX = {"farmazids": PN_ROXO_TX, "farmaponte": PN_OURO_TX, "veracruz": PN_ROXO_TX}  # cor do nome na tabela
PN_NOMES = {"farmazids": "Farmazids", "farmaponte": "FarmaPonte", "veracruz": "Vera Cruz"}

_CSS_PAINEL = """
<style>
[data-testid="stVerticalBlockBorderWrapper"]:has(.pn-marker) {
  background: __BG__ !important; border: 1px solid __LINHA__ !important; border-radius: 20px !important;
  padding: 0 24px 22px !important; margin: 8px 0 4px; overflow: hidden; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.pn-marker) [data-testid="stMarkdownContainer"],
[data-testid="stVerticalBlockBorderWrapper"]:has(.pn-marker) [data-testid="stMarkdownContainer"] p { color: __TEXTO__; }
.pn-marker { display: none; }
.pn-head { margin: 0 -24px; padding: 18px 24px 0; border-bottom: 1px solid __LINHA__; }
.pn-title { font-size: 17px; font-weight: 600; color: __ROXOTX__; letter-spacing: -.2px; }
.pn-sub { font-size: 12px; color: __MUDO__; margin: 2px 0 14px; letter-spacing: 0; }
.pn-tabs { display: flex; gap: 6px; }
.pn-tab { display: inline-flex; align-items: center; gap: 9px; padding: 9px 16px; font-size: 11px; letter-spacing: 1.2px;
  font-weight: 600; color: __TABTX__; background: __TABBG__; border-radius: 10px 10px 0 0; text-transform: uppercase;
  border-bottom: 2px solid #c4a054; }
.pn-tab i { width: 7px; height: 7px; border-radius: 50%; background: var(--pn-dot, #c4a054); }
.pn-sec { display: flex; align-items: center; gap: 12px; font-size: 11px; letter-spacing: 1.4px; text-transform: uppercase;
  color: __MUDO__; font-weight: 600; margin: 6px 0 0; }
.pn-sec::after { content: ""; flex: 1; height: 1px; background: __LINHA__; }
.pn-pills { display: inline-flex; gap: 4px; padding: 4px; background: __TRILHO__; border-radius: 12px; margin-top: 12px; }
.pn-pill { padding: 7px 18px; border-radius: 9px; font-size: 12px; color: __MUDO__; letter-spacing: 0; }
.pn-pill.on { background: #6d3fc0; color: #fff; font-weight: 600; }
.pn-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; }
.pn-card { background: __CARD__; border: 1px solid __LINHA__; border-radius: 14px; padding: 18px 14px; text-align: center; }
.pn-card-v { font-size: 24px; font-weight: 600; letter-spacing: -.5px; line-height: 1.2; }
.pn-card-l { font-size: 11px; letter-spacing: 1.2px; text-transform: uppercase; color: __MUDO__; margin-top: 4px; }
.pn-leg { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 18px; font-size: 12px; color: __MUDO__; letter-spacing: 0; }
.pn-leg i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 7px; vertical-align: -1px; }
.pn-nota { font-size: 11.5px; color: __MUDO__; letter-spacing: 0; text-align: center; }
.pn-av { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 28px; align-items: start; }
.pn-donut-box { display: flex; flex-direction: column; align-items: center; gap: 16px; margin-top: 18px; }
.pn-donut { position: relative; width: 190px; height: 190px; border-radius: 50%; display: grid; place-items: center; }
.pn-donut::before { content: ""; position: absolute; inset: 27px; border-radius: 50%; background: __BG__; }
.pn-donut-in { position: relative; text-align: center; line-height: 1.1; }
.pn-donut-in b { display: block; font-size: 34px; font-weight: 700; color: __TEXTO__; letter-spacing: -1px; }
.pn-donut-in span { font-size: 11px; letter-spacing: 1.2px; color: __MUDO__; text-transform: uppercase; }
.pn-tab-box { background: __CARD__; border: 1px solid __LINHA__; border-radius: 14px; overflow: hidden; margin-top: 14px; }
.pn-row { display: grid; grid-template-columns: 1.3fr 1fr 1fr 1.1fr; align-items: center; gap: 8px; padding: 12px 16px;
  font-size: 13px; letter-spacing: 0; border-top: 1px solid __LINHA__; color: __TEXTO__; }
.pn-row.h { border-top: none; font-size: 10.5px; letter-spacing: 1.2px; color: __MUDO__; text-transform: uppercase; font-weight: 600; background: __TABBG__; }
.pn-bar { display: block; height: 6px; border-radius: 6px; background: __TRILHO__; overflow: hidden; }
.pn-bar i { display: block; height: 100%; border-radius: 6px; }
/* Seletor da modalidade de preço (Padrão / PIX / Cartão), quando a resposta traz mais de um preço */
[data-testid="stVerticalBlockBorderWrapper"]:has(.pn-marker) [data-testid="stButtonGroup"] {
  background: __TRILHO__; border-radius: 12px; padding: 4px; width: fit-content; gap: 4px; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.pn-marker) [data-testid="stButtonGroup"] button {
  background: transparent !important; border: none !important; border-radius: 9px !important; padding: 6px 18px; color: __MUDO__ !important; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.pn-marker) [data-testid="stButtonGroup"] button p { color: inherit !important; font-size: 12px; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.pn-marker) [data-testid="stBaseButton-segmented_controlActive"] {
  background: #6d3fc0 !important; color: #fff !important; font-weight: 600; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.pn-marker) [data-testid="stRadio"] label p { color: __TEXTO__ !important; }
</style>
"""
CSS_PAINEL = (_CSS_PAINEL.replace("__BG__", PN_BG).replace("__LINHA__", PN_LINHA).replace("__TEXTO__", PN_TEXTO)
              .replace("__MUDO__", PN_MUDO).replace("__TABBG__", PN_TAB_BG).replace("__TABTX__", PN_TAB_TX)
              .replace("__TRILHO__", PN_TRILHO).replace("__CARD__", PN_CARD).replace("__ROXOTX__", PN_ROXO_TX))


def _ph(txt) -> str:
    """Texto seguro para HTML dentro do st.markdown (escapa e troca o $ para não virar fórmula)."""
    return esc(str(txt)).replace("$", "&#36;")


def _rede_chave(nome):
    k = _sem_acento(nome).replace(" ", "")
    return next((r for r in PN_REDES if r in k), None)


def _cor_rede(nome, i: int = 0) -> str:
    chave = _rede_chave(nome)
    return PN_REDES[chave] if chave else PN_PALETA[i % len(PN_PALETA)]


def _e_rede(valores) -> bool:
    return any(_rede_chave(v) for v in valores)


def _pct_txt(x: float) -> str:
    return f"{round(x)}%" if abs(x - round(x)) <= 0.05 else fmt_valor(x, "pct")


def _fmt_painel(v, fmt: str) -> str:
    if fmt == "dec":
        return fmt_valor(v, "dinheiro").replace("R$ ", "")
    return fmt_valor(v, fmt)


def _fmt_valores(coluna: str, valores: pd.Series) -> str:
    n = _sem_acento(coluna)
    if any(k in n for k in ("preco", "valor", "faturamento", "receita", "custo", "ticket")):
        return "dinheiro"
    if "pct" in n or "percent" in n:
        return "pct"
    v = valores.dropna()
    return "int" if v.empty or (v % 1 == 0).all() else "dec"


def _modalidade(nome: str):
    t = _sem_acento(nome)
    if "pix" in t:
        return "PIX"
    if "cartao" in t or "parcel" in t:
        return "Cartão"
    if "sem_desconto" in t or "sem desconto" in t or "padrao" in t:
        return "Padrão"
    return None


def _classificar_colunas(df: pd.DataFrame):
    """Separa as colunas em data, números e texto (mesma regra do build_chart)."""
    col_data, fmt, col_num, col_txt = None, None, [], []
    for c in df.columns:
        vals = df[c].dropna().astype(str)
        if vals.empty:
            col_txt.append(c)
            continue
        formato = _formato_data(vals)
        nums = pd.to_numeric(vals, errors="coerce")
        looks_like_id = vals.str.fullmatch(r"\d{8,}").all() or any(k in c.lower() for k in ("gtin", "codigo", "id_"))
        if col_data is None and formato:
            col_data, fmt = c, formato
        elif nums.notna().all() and not looks_like_id:
            col_num.append(c)
        else:
            col_txt.append(c)
    return col_data, fmt, col_num, col_txt


def _rotulos(df: pd.DataFrame, col_txt: list, padrao: str = "Total") -> pd.Series:
    """Rótulo de cada linha: colunas de texto juntas com ' – ' (vazio vira 'Sem informação')."""
    if not col_txt:
        return pd.Series(padrao if padrao == "Total" else (df.index + 1).astype(str), index=df.index)
    return df[col_txt].fillna("Sem informação").apply(lambda l: " – ".join(map(str, l)), axis=1)


def _ticks_bonitos(vmin: float, vmax: float, n: int = 6) -> list:
    """Valores 'redondos' para o eixo y (ex.: 11, 11,5, 12...), cobrindo de vmin a vmax."""
    if vmax <= vmin:
        vmax = vmin + (abs(vmin) * 0.1 or 1.0)
    bruto = (vmax - vmin) / n
    exp = math.floor(math.log10(bruto))
    f = bruto / 10 ** exp
    passo = (1 if f <= 1 else 2 if f <= 2 else 2.5 if f <= 2.5 else 5 if f <= 5 else 10) * 10 ** exp
    ini, fim = math.floor(vmin / passo) * passo, math.ceil(vmax / passo) * passo
    return [round(ini + i * passo, 10) for i in range(int(round((fim - ini) / passo)) + 1)]


def _eixo_y(ticks: list, fmt: str):
    """Eixo y com rótulos no padrão brasileiro (R$ 14,00), grade bem suave e sem linha de borda."""
    rotulos = [_fmt_painel(t, fmt) for t in ticks]
    expr = f"{json.dumps(rotulos, ensure_ascii=False)}[indexof({json.dumps(ticks)}, datum.value)]"
    return alt.Axis(values=ticks, labelExpr=expr, grid=True, gridColor=PN_GRADE, domain=False, ticks=False, title=None,
                    labelColor=PN_MUDO, labelFont="Geist", labelPadding=8)


def _eixo_x(angulo: int = 0):
    return alt.Axis(labelAngle=angulo, labelLimit=170, labelColor=PN_MUDO, labelFont="Geist", ticks=False,
                    domain=False, grid=False, labelPadding=8)


def _alt_barras(d: pd.DataFrame, fmt: str):
    """Barras largas com preenchimento translúcido e borda da cor da rede (como no modelo)."""
    n = len(d)
    ticks = _ticks_bonitos(min(0.0, float(d["valor"].min())), max(float(d["valor"].max()), 0.0))
    base = alt.Chart(d).encode(
        x=alt.X("rotulo:N", sort=None, title=None, scale=alt.Scale(paddingInner=0.35, paddingOuter=0.25),
                axis=_eixo_x(0 if n <= 4 else -30)),
        y=alt.Y("valor:Q", title=None, scale=alt.Scale(domain=[ticks[0], ticks[-1]], nice=False), axis=_eixo_y(ticks, fmt)),
        tooltip=[alt.Tooltip("rotulo:N", title="Item"), alt.Tooltip("texto:N", title="Valor")],
    )
    camada = base.mark_bar(cornerRadiusTopLeft=7, cornerRadiusTopRight=7, fillOpacity=0.28, strokeWidth=1.6).encode(
        color=alt.Color("cor:N", scale=None, legend=None), stroke=alt.Stroke("cor:N", scale=None, legend=None))
    if n > 4:  # sem cartões de valor, o número aparece em cima de cada barra
        camada = camada + base.mark_text(dy=-9, color=PN_TEXTO, font="Geist", fontSize=11).encode(text="texto:N")
    return camada.properties(height=300, background="rgba(0,0,0,0)").configure_view(stroke=None)


def _alt_serie(d: pd.DataFrame, series: list, cores: list, fmt: str, fmt_rot: str, tipo: str):
    """Evolução no tempo (linhas ou barras agrupadas) no mesmo estilo."""
    zero = tipo != "linha"
    lo, hi = float(d["valor"].min()), float(d["valor"].max())
    ticks = _ticks_bonitos(min(0.0, lo) if zero else lo, max(hi, 0.0) if zero else hi)
    escala = alt.Scale(domain=series, range=cores)
    y = alt.Y("valor:Q", title=None, scale=alt.Scale(domain=[ticks[0], ticks[-1]], nice=False), axis=_eixo_y(ticks, fmt))
    dica = [alt.Tooltip("periodo:N", title="Período"), alt.Tooltip("serie:N", title="Série"), alt.Tooltip("texto:N", title="Valor")]
    if tipo == "linha":
        ch = alt.Chart(d).mark_line(strokeWidth=2.5, point=True).encode(
            x=alt.X("x:T", title=None, axis=alt.Axis(format=fmt_rot, labelAngle=0, grid=False, domain=False, ticks=False,
                                                     labelColor=PN_MUDO, labelFont="Geist", labelPadding=8)),
            y=y, color=alt.Color("serie:N", scale=escala, legend=None), tooltip=dica)
    else:
        ordem = list(d.sort_values("x")["periodo"].drop_duplicates())
        ch = alt.Chart(d).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, fillOpacity=0.28, strokeWidth=1.6).encode(
            x=alt.X("periodo:O", sort=ordem, title=None, scale=alt.Scale(paddingInner=0.3), axis=_eixo_x(-30 if len(ordem) > 4 else 0)),
            y=y, color=alt.Color("serie:N", scale=escala, legend=None), stroke=alt.Stroke("serie:N", scale=escala, legend=None),
            tooltip=dica)
        if len(series) > 1:
            ch = ch.encode(xOffset=alt.XOffset("serie:N"))
    return ch.properties(height=300, background="rgba(0,0,0,0)").configure_view(stroke=None)


def _conic(fatias: list) -> str:
    """Gradiente cônico da rosca, com uma fresta escura entre as fatias."""
    total = sum(v for v, _ in fatias) or 1.0
    ac, partes = 0.0, []
    for v, cor in fatias:
        ini = ac / total * 100
        ac += v
        fim = ac / total * 100
        corte = max(fim - 0.5, ini)
        partes.append(f"{cor} {ini:.2f}% {corte:.2f}%, {PN_BG} {corte:.2f}% {fim:.2f}%")
    return "conic-gradient(" + ", ".join(partes) + ")"


def _donut_html(fatias: list, centro: str, rotulo_centro: str, legenda: str) -> str:
    return (f'<div class="pn-donut-box"><div class="pn-donut" style="background:{_conic(fatias)}">'
            f'<div class="pn-donut-in"><b>{_ph(centro)}</b><span>{_ph(rotulo_centro)}</span></div></div>'
            f'<div class="pn-leg">{legenda}</div></div>')


def _cards_html(itens: list) -> str:
    return '<div class="pn-cards">' + "".join(
        f'<div class="pn-card"><div class="pn-card-v" style="color:{cor}">{_ph(valor)}</div>'
        f'<div class="pn-card-l">{_ph(rotulo)}</div></div>' for valor, rotulo, cor in itens) + "</div>"


def _status_disp(v):
    t = _sem_acento(v)
    if any(p in t for p in ("indispon", "esgot", "sem estoque", "ruptura")):
        return "ind"
    if "dispon" in t or "em estoque" in t:
        return "disp"
    return None


def _dados_disponibilidade(df: pd.DataFrame, col_txt: list, col_num: list):
    """Se o resultado fala de disponibilidade, devolve uma tabela por rede com as colunas disp e ind; senão None."""
    if not col_num:
        return None
    achou = None
    for c in col_txt:
        marcados = df[c].dropna().astype(str).map(_status_disp)
        if marcados.notna().any() and marcados.notna().mean() >= 0.5:
            achou = c
            break
    if achou is not None:  # formato longo: rede, situação, quantidade
        outras = [c for c in col_txt if c != achou]
        rede = df[outras[0]].fillna("Sem informação").astype(str) if outras else pd.Series("Total", index=df.index)
        t = pd.DataFrame({"rede": rede, "st": df[achou].map(lambda v: _status_disp(v) if pd.notna(v) else None),
                          "n": pd.to_numeric(df[col_num[-1]], errors="coerce")}).dropna(subset=["st", "n"])
        if t.empty:
            return None
        g = t.pivot_table(index="rede", columns="st", values="n", aggfunc="sum", fill_value=0, sort=False)
        g = g.reindex(columns=["disp", "ind"], fill_value=0)
    else:  # formato largo: rede, disponíveis, indisponíveis
        c_d = next((c for c in col_num if "dispon" in _sem_acento(c) and "indispon" not in _sem_acento(c)), None)
        c_i = next((c for c in col_num if "indispon" in _sem_acento(c) or "esgot" in _sem_acento(c)), None)
        if not (c_d and c_i):
            return None
        rede = df[col_txt[0]].fillna("Sem informação").astype(str) if col_txt else pd.Series("Total", index=df.index)
        t = pd.DataFrame({"rede": rede, "disp": pd.to_numeric(df[c_d], errors="coerce"),
                          "ind": pd.to_numeric(df[c_i], errors="coerce")}).dropna()
        if t.empty:
            return None
        g = t.groupby("rede", sort=False)[["disp", "ind"]].sum()
    g = g[(g["disp"] + g["ind"]) > 0]
    return g if not g.empty else None


def _html_disponibilidade(g: pd.DataFrame) -> str:
    """Rosca com a disponibilidade geral + tabela de disponibilidade por rede."""
    redes = list(g.index)
    disp, ind = float(g["disp"].sum()), float(g["ind"].sum())
    geral = disp / (disp + ind) * 100
    if len(redes) > 1:
        fatias = [(float(g.loc[r, "disp"]), _cor_rede(r, i)) for i, r in enumerate(redes)]
        legenda = "".join(f'<span><i style="background:{c}"></i>{_ph(r)}</span>' for (_, c), r in zip(fatias, redes))
    else:
        fatias = [(disp, PN_ROXO), (ind, PN_DOURADO)]
        legenda = (f'<span><i style="background:{PN_ROXO}"></i>Disponível</span>'
                   f'<span><i style="background:{PN_DOURADO}"></i>Indisponível</span>')
    linhas = ""
    for i, r in enumerate(redes):
        d_, i_ = float(g.loc[r, "disp"]), float(g.loc[r, "ind"])
        pdisp = d_ / (d_ + i_) * 100
        cor = _cor_rede(r, i)
        chave = _rede_chave(r)
        cor_txt = PN_REDES_TX[chave] if chave else PN_ROXO_TX
        largura = max(min(pdisp, 100.0), 2.0)
        linhas += (f'<div class="pn-row"><span style="color:{cor_txt};font-weight:600">{_ph(r)}</span>'
                   f'<span style="color:{PN_ROXO_TX};font-weight:600">{_pct_txt(pdisp)}</span>'
                   f'<span style="font-weight:500">{fmt_valor(d_, "int")}</span>'
                   f'<span class="pn-bar"><i style="width:{largura:.1f}%;background:{cor}"></i></span></div>')
    return ('<div class="pn-av"><div><div class="pn-sec">Share de presença e disponibilidade</div>'
            + _donut_html(fatias, _pct_txt(geral), "Disponível", legenda) + '</div>'
            '<div><div class="pn-sec">Disponibilidade por rede</div><div class="pn-tab-box">'
            '<div class="pn-row h"><span>Farmácia</span><span>Disponível</span><span>Produtos</span><span>Barra</span></div>'
            + linhas + '</div></div></div>')


def _plano_painel(df: pd.DataFrame, pergunta: str, mod=None):
    """Decide o que o painel mostra (sem chamar o Streamlit). Devolve None se não der para montar."""
    col_data, fmt_data, col_num, col_txt = _classificar_colunas(df)
    if not col_num:
        return None

    g = _dados_disponibilidade(df, col_txt, col_num)
    if g is not None:
        return {"tab": "Disponibilidade", "dot": PN_DOURADO, "mod_atual": None,
                "blocos": [("html", _html_disponibilidade(g))]}

    # modalidades de preço (ex.: preco_sem_desconto, preco_desconto_pix): viram um seletor Padrão / PIX / Cartão
    mods = {}
    for c in col_num:
        m = _modalidade(c)
        if m and m not in mods:
            mods[m] = c
    ordem_mod = [m for m in ("Padrão", "PIX", "Cartão") if m in mods]
    usar_toggle = len(ordem_mod) >= 2
    mod_atual = (mod if mod in ordem_mod else ordem_mod[0]) if usar_toggle else None
    y = mods[mod_atual] if usar_toggle else col_num[-1]
    valor_all = pd.to_numeric(df[y], errors="coerce")
    fmt = _fmt_valores(y, valor_all)
    dinheiro = fmt == "dinheiro"
    q = _sem_acento(pergunta)
    y_legivel = y.replace("_", " ")

    blocos = []
    if usar_toggle:
        blocos += [("html", '<div class="pn-sec">Modalidade de preço</div>'), ("toggle", ordem_mod)]
    elif dinheiro:
        m = _modalidade(y) or ("PIX" if "pix" in q else ("Cartão" if "cartao" in q else None))
        if m:
            blocos.append(("html", f'<div class="pn-sec">Modalidade de preço</div><div class="pn-pills"><span class="pn-pill on">{m}</span></div>'))

    pedido = tipo_pedido(pergunta)
    cor_tab = PN_DOURADO if dinheiro else PN_ROXO

    # ----- série no tempo -----
    if col_data is not None:
        d = pd.DataFrame({"x": pd.to_datetime(df[col_data], format=fmt_data, errors="coerce"), "valor": valor_all,
                          "serie": _rotulos(df, col_txt)}).dropna(subset=["x", "valor"])
        if d.empty:
            return None
        fmt_rot = "%m/%Y" if fmt_data == "%Y-%m" else "%d/%m"
        d["periodo"] = d["x"].dt.strftime(fmt_rot)
        series = list(dict.fromkeys(d["serie"]))
        eh_rede = _e_rede(series)
        cores = [_cor_rede(s, i) if eh_rede else PN_PALETA[i % len(PN_PALETA)] for i, s in enumerate(series)]
        d["texto"] = d["valor"].map(lambda v: _fmt_painel(v, fmt))
        tipo = pedido if pedido in ("barras", "linha") else ("linha" if d["x"].nunique() > 12 else "barras")
        if len(series) <= 4:
            itens = []
            for s, c in zip(series, cores):
                ult = d[d["serie"] == s].sort_values("x").iloc[-1]
                itens.append((ult["texto"], s if s != "Total" else y_legivel, c))
            blocos.append(("html", _cards_html(itens)))
        blocos.append(("html", f'<div class="pn-sec">{"Evolução de preços" if dinheiro else "Evolução por período"}</div>'))
        blocos.append(("chart", _alt_serie(d, series, cores, fmt, fmt_rot, tipo)))
        if len(series) > 1:
            blocos.append(("html", '<div class="pn-leg">' + "".join(
                f'<span><i style="background:{c}"></i>{_ph(s)}</span>' for s, c in zip(series, cores)) + "</div>"))
        return {"tab": "Evolução de preços" if dinheiro else "Evolução no tempo", "dot": cor_tab, "blocos": blocos, "mod_atual": mod_atual}

    # ----- comparação entre itens (barras) ou participação (rosca) -----
    d = pd.DataFrame({"rotulo": _rotulos(df, col_txt, padrao="indice"), "valor": valor_all}).dropna(subset=["valor"]).reset_index(drop=True)
    if d.empty:
        return None
    n = len(d)
    eh_rede = _e_rede(d["rotulo"])
    d["cor"] = [_cor_rede(r, i) if eh_rede else PN_ROXO for i, r in enumerate(d["rotulo"])]
    d["texto"] = d["valor"].map(lambda v: _fmt_painel(v, fmt))

    if pedido == "pizza" and n <= 8 and (d["valor"] > 0).all():
        total = float(d["valor"].sum())
        cores_p = list(d["cor"]) if eh_rede else [PN_PALETA[i % len(PN_PALETA)] for i in range(n)]
        legenda = "".join(f'<span><i style="background:{c}"></i>{_ph(r)} · {_pct_txt(v / total * 100)}</span>'
                          for r, v, c in zip(d["rotulo"], d["valor"], cores_p))
        blocos.append(("html", '<div class="pn-sec">Distribuição</div>'))
        blocos.append(("html", _donut_html(list(zip(d["valor"], cores_p)), _fmt_painel(total, fmt), "Total", legenda)))
        return {"tab": "Distribuição", "dot": cor_tab, "blocos": blocos, "mod_atual": mod_atual}

    nota = ""
    if destaca_barato(pergunta) and n > 1:  # a opção mais barata em dourado
        d.loc[d["valor"].idxmin(), "cor"] = GOLD
        nota = "Em dourado: a opção mais barata."
    if n <= 4:
        blocos.append(("html", _cards_html(list(zip(d["texto"], d["rotulo"], d["cor"])))))
    blocos.append(("html", f'<div class="pn-sec">{"Comparativo por farmácia" if eh_rede else "Comparativo de " + _ph(y_legivel)}</div>'))
    blocos.append(("chart", _alt_barras(d, fmt)))
    chaves = list(dict.fromkeys(k for k in (_rede_chave(r) for r in d["rotulo"]) if k))
    if eh_rede and chaves:
        blocos.append(("html", '<div class="pn-leg">' + "".join(
            f'<span><i style="background:{PN_REDES[k]}"></i>{PN_NOMES[k]}</span>' for k in chaves) + "</div>"))
    if nota:
        blocos.append(("html", f'<div class="pn-nota">{nota}</div>'))
    return {"tab": "Comparativo de preços" if dinheiro else "Comparativo", "dot": cor_tab, "blocos": blocos, "mod_atual": mod_atual}


def _toggle_modalidade(opcoes: list, chave: str, padrao: str) -> str:
    if hasattr(st, "segmented_control"):
        sel = st.segmented_control("Modalidade de preço", opcoes, default=padrao, key=chave, label_visibility="collapsed")
    else:  # Streamlit mais antigo
        sel = st.radio("Modalidade de preço", opcoes, index=opcoes.index(padrao), key=chave, horizontal=True,
                       label_visibility="collapsed")
    return sel or padrao


def painel_grafico(df: pd.DataFrame, pergunta: str, uid: str = "0") -> bool:
    """Desenha o painel e devolve True. Devolve False (sem desenhar nada) se não houver como montar o gráfico."""
    if df is None or df.empty:
        return False
    plano = _plano_painel(df, pergunta)
    if plano is None:
        return False
    st.markdown(CSS_PAINEL, unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="pn-marker"></div><div class="pn-head"><div class="pn-title">Zids Intel</div>'
                    '<div class="pn-sub">Análise de mercado em tempo real · Athena</div>'
                    f'<div class="pn-tabs"><span class="pn-tab" style="--pn-dot:{plano["dot"]}"><i></i>{_ph(plano["tab"])}</span></div></div>',
                    unsafe_allow_html=True)
        i = 0
        while i < len(plano["blocos"]):
            tipo, conteudo = plano["blocos"][i]
            if tipo == "html":
                st.markdown(conteudo, unsafe_allow_html=True)
            elif tipo == "chart":
                st.altair_chart(conteudo, use_container_width=True, theme=None)
            elif tipo == "toggle":
                escolha = _toggle_modalidade(conteudo, f"pn_mod_{uid}", plano["mod_atual"])
                if escolha != plano["mod_atual"]:  # outra modalidade: refaz os blocos seguintes com a nova coluna de preço
                    plano = _plano_painel(df, pergunta, mod=escolha) or plano
            i += 1
    return True


def render_message(m: dict, uid: str = "0"):
    st.markdown(md_seguro(m["content"]))
    df = rows_to_df(m.get("rows") or []) if m.get("sql") else None
    if m.get("chart"):
        painel_ok = False
        if df is not None:
            try:  # gráfico no painel "Zids Intel"; se algo falhar, cai no gráfico antigo logo abaixo
                painel_ok = painel_grafico(df, m.get("pergunta", ""), uid)
            except Exception:  # noqa: BLE001
                painel_ok = False
        if not painel_ok:
            chart = build_chart(df, m.get("pergunta", "")) if df is not None else None
            if chart is not None:
                st.altair_chart(tema_escuro(chart.properties(height=320)), use_container_width=True,
                                theme=None if DARK else "streamlit")
                if destaca_barato(m.get("pergunta", "")) and _tipo_marca(chart) == "bar":
                    st.caption("Em dourado: a opção mais barata.")
            elif pediu_grafico(m.get("pergunta", "")):
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
            "e não o mês atual. Some quantidade_vendida por farmácia e gtin. Mostre o NOME do produto, nunca o gtin: "
            "se historico_farmazids não tiver o nome, busque-o pelo gtin em medicamentos_farmazids, farmaponte_tratado "
            "e veracruz_tratado (um único registro por gtin em cada tabela, com MAX(nome), e COALESCE entre elas) "
            "sem duplicar as vendas; use o gtin só se nenhuma tabela tiver o nome. Devolva exatamente 3 colunas, "
            "nesta ordem e com estes apelidos: farmacia, produto (o nome), total_vendido."
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
        "descricao": "Produtos que não estão na Farmazids, escolhidos pelo maior faturamento (preço × quantidade vendida).",
        "tipo": "tabela",
        "pergunta": (
            "Quero sugestões de produtos para adicionar ao catálogo da Farmazids, ordenadas por FATURAMENTO. "
            "Pegue, na coleta mais recente (maior dia de data_extracao) de farmaponte_tratado e de veracruz_tratado, "
            "os produtos cujo gtin NÃO existe na tabela medicamentos_farmazids (use NOT EXISTS ou LEFT JOIN com IS NULL), "
            "com gtin e preco_desconto_pix não nulos e maiores que zero, um registro por gtin (o MENOR "
            "preco_desconto_pix do gtin). Faturamento = preco_desconto_pix × unidades vendidas, onde unidades vendidas "
            "é a soma de quantidade_vendida na tabela historico_farmazids para o mesmo gtin e a farmácia "
            "correspondente (farmacia = 'farmaponte' para a FarmaPonte e farmacia = 'veracruz' para a VeraCruz), no "
            "mês da maior data_venda da carga mais recente (\"$file_modified_time\" = MAX(\"$file_modified_time\") da "
            "tabela), e não o mês atual. Considere só produtos com unidades vendidas maiores que zero. Devolva os 5 "
            "de maior faturamento da FarmaPonte e os 5 de maior faturamento da VeraCruz (10 linhas no total), em "
            "ordem decrescente de faturamento dentro de cada concorrente; se algum concorrente tiver menos de 5 "
            "produtos com vendas, complete com os de maior desconto_pct. Para a categoria, use a do próprio "
            "concorrente, com um único registro por gtin. Devolva exatamente 4 colunas, nesta ordem e com estes "
            "apelidos: concorrente (use exatamente 'FarmaPonte' ou 'VeraCruz'), produto, categoria, preco_pix "
            "(o preco_desconto_pix)."
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


# ---------- Insights em paralelo + pré-carregamento ----------
# Cada consulta é um "future" guardado por pergunta: quem pedir a mesma pergunta (a página Insights, o PDF,
# o pré-carregamento do login) reaproveita a que já está rodando ou pronta, sem repetir a chamada.
INSIGHT_TTL_S = 3600  # os resultados valem por 1 hora


@st.cache_resource
def _insight_store() -> dict:
    """Pool de threads e consultas (em andamento ou prontas); um só para todo o app, compartilhado entre sessões."""
    return {"lock": threading.Lock(), "itens": {},
            "pool": ThreadPoolExecutor(max_workers=6, thread_name_prefix="insight")}


def _consultar_insight(pergunta: str) -> dict:
    """Roda numa thread de fundo: não pode chamar nada do Streamlit (st.*)."""
    resultado = generate_reply(pergunta)
    if not resultado.get("sql"):  # erro não é guardado: na próxima vez a consulta é refeita
        raise RuntimeError(resultado["content"])
    return resultado


def _insight_future(pergunta: str):
    """Future da pergunta: reaproveita o existente (rodando, pronto e dentro do prazo) ou dispara um novo."""
    store = _insight_store()
    with store["lock"]:
        item = store["itens"].get(pergunta)
        if item is not None:
            fut, inicio = item
            if fut.done() and (fut.exception() is not None or time.time() - inicio > INSIGHT_TTL_S):
                item = None  # deu erro ou venceu o prazo: refaz
        if item is None:
            fut = store["pool"].submit(_consultar_insight, pergunta)
            store["itens"][pergunta] = (fut, time.time())
            return fut
        return item[0]


def run_insight(pergunta: str) -> dict:
    """Resultado da pergunta; espera se ainda estiver rodando. Erros levantam RuntimeError (como antes)."""
    return _insight_future(pergunta).result()


def iniciar_insights():
    """Dispara TODAS as consultas dos insights ao mesmo tempo (as já prontas ou em andamento são reaproveitadas)."""
    for pergunta in [s["pergunta"] for s in INSIGHTS] + [COMPARATIVO["pergunta"]]:
        _insight_future(pergunta)


def limpar_insights():
    """Botão 'Atualizar dados': esquece tudo para as consultas rodarem de novo."""
    store = _insight_store()
    with store["lock"]:
        store["itens"].clear()


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


# ---------- Dados mais memoráveis: sparklines, régua de preço e cartão de produto ----------
FARMACIAS = ["Farmazids", "FarmaPonte", "VeraCruz"]
UP_COR = "#3ccf8e" if DARK else "#1f9d63"
DOWN_COR = "#ff7a7a" if DARK else "#d64545"
CINZA_BARRA = "#6f6985" if DARK else "#9c98a8"

CSS_DESTAQUES = """
<style>
/* Sparkline + seta colorida dentro dos cartões de estatística */
.g-spark { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-12); margin-top: var(--spacing-16); }
.g-spark svg { width: 100%; max-width: 150px; height: auto; display: block; overflow: visible; }
.g-spark .linha { fill: none; stroke: var(--color-brand); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.g-spark .area { fill: var(--color-brand); opacity: .14; stroke: none; }
.g-spark .ponto { fill: var(--color-brand); }
.g-delta { font-size: var(--text-body-sm); font-weight: var(--font-weight-semibold); letter-spacing: 0; white-space: nowrap; }
.g-delta.up { color: __UP__; }
.g-delta.down { color: __DOWN__; }
.g-delta.flat { color: var(--color-slate-mid); }

/* Legenda das cores (dourado = menor preço) */
.g-legenda { display: flex; flex-wrap: wrap; gap: var(--spacing-16); font-size: var(--text-caption); letter-spacing: 0;
  color: var(--color-graphite); margin: var(--spacing-8) 0 var(--spacing-4); }
.g-legenda i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: -1px; }
.g-legenda .ouro { background: var(--color-gold); }
.g-legenda .roxo { background: var(--color-brand); }
.g-legenda .cinza { background: #9c98a8; }

/* Cartão de produto: comparação lado a lado + régua de preço */
.g-prods { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: var(--spacing-16); margin: var(--spacing-16) 0 var(--spacing-24); }
.g-prod { background: var(--surface-card); border-radius: var(--radius-cards); padding: var(--card-padding);
  display: flex; flex-direction: column; gap: var(--spacing-16); }
/* min-height de 2 linhas (2 x 1.3 de line-height): nomes curtos ganham uma "linha vazia" e os cartões ficam alinhados.
   O line-clamp corta em 2 linhas os nomes muito longos, para que nenhum cartão passe disso. */
.g-prod-nome { font-weight: var(--font-weight-semibold); line-height: 1.3; min-height: 2.6em;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.g-prod-status { align-self: flex-start; font-size: var(--text-caption); line-height: 1.4; letter-spacing: 0;
  border-radius: var(--radius-tags); padding: var(--spacing-4) var(--spacing-12); }
.g-prod-status.ok { background: rgba(196,160,84,.22); color: var(--color-gold-deep); font-weight: var(--font-weight-semibold); }
.g-prod-status.acima { background: rgba(128,128,128,.18); color: var(--color-graphite); }
.g-lado { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--spacing-8); }
.g-col { border: 1px solid rgba(128,128,128,.28); border-radius: var(--radius-xl); background: var(--surface-canvas);
  padding: var(--spacing-12) var(--spacing-8); text-align: center; }
.g-col.nossa { border-color: var(--color-brand); }
.g-col.barata { border-color: var(--color-gold); box-shadow: 0 0 0 1px var(--color-gold); background: rgba(196,160,84,.14); }
.g-col-nome { font-size: var(--text-caption); letter-spacing: .6px; text-transform: uppercase; color: var(--color-slate-mid); }
.g-col.nossa .g-col-nome { color: var(--color-brand); font-weight: var(--font-weight-semibold); }
.g-col-preco { font-size: var(--text-subheading); font-weight: var(--font-weight-semibold); letter-spacing: var(--tracking-subheading); margin: var(--spacing-4) 0; }
.g-col.sem .g-col-preco { color: var(--color-slate-mid); font-weight: var(--font-weight-regular); }
.g-col-dif { font-size: var(--text-caption); line-height: 1.5; letter-spacing: 0; color: var(--color-slate-mid); min-height: 1.5em; }
.g-col-tag { display: inline-block; font-size: 11px; font-weight: var(--font-weight-semibold); background: var(--color-gold);
  color: #231a33; border-radius: var(--radius-tags); padding: 0 var(--spacing-8); }

/* Régua de preço horizontal */
.g-regua { position: relative; height: 88px; margin: 0 var(--spacing-8); }
.g-regua-trilho { position: absolute; left: 0; right: 0; top: 38px; height: 4px; border-radius: 4px; background: rgba(128,128,128,.35); }
.g-regua-marca { position: absolute; top: 32px; width: 16px; height: 16px; margin-left: -8px; border-radius: 50%;
  background: #9c98a8; border: 2px solid var(--surface-card); box-sizing: border-box; }
.g-regua-marca.nossa { top: 30px; width: 20px; height: 20px; margin-left: -10px; background: var(--color-brand); }
.g-regua-marca.barata { background: var(--color-gold); }
.g-regua-marca.nossa.barata { background: var(--color-gold); box-shadow: 0 0 0 3px var(--color-brand); }
.g-regua-rot { position: absolute; transform: translateX(-50%); font-size: 11px; line-height: 1.2; letter-spacing: 0;
  white-space: nowrap; color: var(--color-graphite); }
.g-regua-rot.topo { top: 6px; font-weight: var(--font-weight-semibold); color: var(--color-brand); }
.g-regua-rot.b0 { top: 54px; }
.g-regua-rot.b1 { top: 70px; }
.g-regua-rot.barata { color: var(--color-gold-deep); font-weight: var(--font-weight-semibold); }
.g-regua-ext { display: flex; justify-content: space-between; font-size: 11px; letter-spacing: 0; color: var(--color-slate-mid); margin: 0 var(--spacing-8); }
</style>
""".replace("__UP__", UP_COR).replace("__DOWN__", DOWN_COR)


def sparkline(valores, w: int = 150, h: int = 40, pad: int = 4) -> str:
    """Mini-gráfico de linha em SVG (sem eixos) para os cartões de estatística."""
    v = [float(x) for x in valores if pd.notna(x)]
    if len(v) < 2:
        return ""
    lo, hi = min(v), max(v)
    xs = [pad + i * (w - 2 * pad) / (len(v) - 1) for i in range(len(v))]
    ys = [h / 2 if hi == lo else h - pad - (x - lo) / (hi - lo) * (h - 2 * pad) for x in v]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Tendência">'
        f'<polygon class="area" points="{xs[0]:.1f},{h} {pts} {xs[-1]:.1f},{h}"/>'
        f'<polyline class="linha" points="{pts}"/>'
        f'<circle class="ponto" cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="3.5"/></svg>'
    )


def seta_delta(valores, ref: str = "") -> str:
    """Seta ↑/↓ colorida com a variação do último ponto em relação ao anterior."""
    v = [float(x) for x in valores if pd.notna(x)]
    if len(v) < 2:
        return ""
    ant, atual = v[-2], v[-1]
    if atual > ant:
        cls, seta = "up", "↑"
    elif atual < ant:
        cls, seta = "down", "↓"
    else:
        cls, seta = "flat", "→"
    pct = f" {fmt_valor(abs(atual - ant) / abs(ant) * 100, 'pct')}" if ant else ""
    dica = f' title="{esc(ref)}"' if ref else ""
    return f'<span class="g-delta {cls}"{dica}>{seta}{pct}</span>'


def card_stat(rotulo, valor, legenda, serie=None, ref: str = "") -> str:
    """Cartão de estatística (rótulo → número → legenda) com sparkline e seta quando há série."""
    extra = ""
    if serie is not None and len(serie) >= 2:
        extra = f'<div class="g-spark">{sparkline(serie)}{seta_delta(serie, ref)}</div>'
    return (f'<div class="g-stat"><div class="g-label">{rotulo}</div><div class="g-num">{valor}</div>'
            f'<div class="g-cap">{legenda}</div>{extra}</div>')


LEGENDA_PRECO = ('<div class="g-legenda"><span><i class="ouro"></i>Menor preço</span>'
                 '<span><i class="roxo"></i>Farmazids</span><span><i class="cinza"></i>Concorrentes</span></div>')

COMPARATIVO = {
    "titulo": "Preço dos best-sellers",
    "colunas": ["produto", "Farmazids", "FarmaPonte", "VeraCruz"],
    "pergunta": (
        "Pegue 6 produtos da Farmazids (tabela medicamentos_farmazids, coluna preco, só a coleta mais recente, "
        "um registro por gtin com o MENOR preco (MIN), com preco IS NOT NULL e preco > 0) que sejam os mais vendidos no mês mais recente "
        "com vendas registradas na tabela historico_farmazids (considere o mês da maior data_venda da tabela, e não "
        "o mês atual; some quantidade_vendida por gtin) e que existam em pelo menos um concorrente. Para cada produto "
        "traga o preco_desconto_pix da FarmaPonte (tabela farmaponte_tratado) e da VeraCruz (tabela veracruz_tratado), "
        "usando só a coleta mais recente de cada tabela, com um registro por gtin que traga o MENOR "
        "preco_desconto_pix (MIN) daquele gtin, e ligando pelo gtin com LEFT JOIN; preço nulo ou zero do "
        "concorrente deve virar NULL. Devolva exatamente 4 colunas, nesta ordem e com estes apelidos: produto "
        "(nome do produto na Farmazids), preco_farmazids, preco_farmaponte, preco_veracruz."
    ),
}


def preparar_comparativo(bruto):
    """Lê as colunas por posição: produto, Farmazids, FarmaPonte, VeraCruz (preço <= 0 vira vazio)."""
    if bruto is None or bruto.shape[1] < 4:
        return None
    d = bruto.iloc[:, :4].copy()
    d.columns = COMPARATIVO["colunas"]
    for f in FARMACIAS:
        d[f] = pd.to_numeric(d[f], errors="coerce")
        d.loc[d[f] <= 0, f] = float("nan")
    d = d.dropna(subset=["produto", "Farmazids"])
    d = d[d[["FarmaPonte", "VeraCruz"]].notna().any(axis=1)]  # precisa de ao menos um concorrente
    return d.head(6).reset_index(drop=True) if not d.empty else None


def _rs(v) -> str:
    """R$ para uso dentro de HTML no st.markdown (o $ vira entidade para não ser lido como fórmula)."""
    return fmt_valor(v, "dinheiro").replace("$", "&#36;")


def regua_html(precos: dict) -> str:
    """Régua horizontal: do mais barato (esquerda) ao mais caro (direita), com a Farmazids em roxo."""
    vals = list(precos.values())
    lo, hi = min(vals), max(vals)
    barata = {f for f, p in precos.items() if abs(p - lo) < 0.005}
    pos = lambda p: 50.0 if hi - lo < 0.005 else 6 + (p - lo) / (hi - lo) * 88
    rotulo_x = lambda x: min(max(x, 12), 88)
    marcas, rotulos = [], []
    concorrentes = sorted((f for f in precos if f != "Farmazids"), key=lambda f: precos[f])
    for i, f in enumerate(concorrentes):  # rótulos alternam em duas linhas para não se sobrepor
        x, cls = pos(precos[f]), ("barata" if f in barata else "")
        dica = f'title="{esc(f)}: {_rs(precos[f])}"'
        marcas.append(f'<div class="g-regua-marca {cls}" style="left:{x:.1f}%" {dica}></div>')
        rotulos.append(f'<div class="g-regua-rot b{i % 2} {cls}" style="left:{rotulo_x(x):.1f}%">{esc(f)}</div>')
    x = pos(precos["Farmazids"])
    cls = "barata" if "Farmazids" in barata else ""
    dica = f'title="Farmazids: {_rs(precos["Farmazids"])}"'
    marcas.append(f'<div class="g-regua-marca nossa {cls}" style="left:{x:.1f}%" {dica}></div>')
    rotulos.append(f'<div class="g-regua-rot topo" style="left:{rotulo_x(x):.1f}%">Farmazids</div>')
    if hi - lo < 0.005:
        ext = f'<span style="margin:0 auto">Mesmo preço: {_rs(lo)}</span>'
    else:
        ext = f'<span>{_rs(lo)} · mais barato</span><span>mais caro · {_rs(hi)}</span>'
    return (f'<div class="g-regua"><div class="g-regua-trilho"></div>{"".join(marcas)}{"".join(rotulos)}</div>'
            f'<div class="g-regua-ext">{ext}</div>')


def card_produto(nome: str, precos: dict) -> str:
    """Cartão com as três farmácias lado a lado, o veredito e a régua de preço."""
    disp = {f: p for f, p in precos.items() if pd.notna(p)}
    faz = disp["Farmazids"]
    lo = min(disp.values())
    barata = [f for f, p in disp.items() if abs(p - lo) < 0.005]
    if "Farmazids" in barata:
        status = ("ok", "Farmazids tem o menor preço" + (" (empate)" if len(barata) > 1 else ""))
    else:
        pct = fmt_valor((faz - lo) / lo * 100, "pct")
        status = ("acima", f"Farmazids está {_rs(faz - lo)} ({pct}) acima da {esc(barata[0])}")
    colunas = []
    for f in FARMACIAS:
        p = precos.get(f)
        cls = ["g-col"] + (["nossa"] if f == "Farmazids" else [])
        if pd.isna(p):
            cls.append("sem")
            preco, dif = "—", "sem preço"
        else:
            preco = _rs(p)
            if f in barata:
                cls.append("barata")
                dif = '<span class="g-col-tag">Mais barata</span>'
            elif f == "Farmazids":
                dif = "nosso preço"
            else:
                d = (p - faz) / faz * 100
                dif = f'{"+" if d > 0 else ""}{fmt_valor(d, "pct")} vs. Farmazids'
        colunas.append(f'<div class="{" ".join(cls)}"><div class="g-col-nome">{f}</div>'
                       f'<div class="g-col-preco">{preco}</div><div class="g-col-dif">{dif}</div></div>')
    return (f'<div class="g-prod"><div class="g-prod-nome">{esc(str(nome))}</div>'
            f'<div class="g-prod-status {status[0]}">{status[1]}</div>'
            f'<div class="g-lado">{"".join(colunas)}</div>{regua_html(disp)}</div>')


def grafico_comparativo(d: pd.DataFrame):
    """Barras de preço por farmácia, uma faixa por produto; a mais barata em dourado."""
    fonte = "Geist"
    longo = d.melt(id_vars="produto", value_vars=FARMACIAS, var_name="farmacia", value_name="preco").dropna(subset=["preco"])
    menor = longo.groupby("produto")["preco"].transform("min")
    longo["barata"] = (longo["preco"] - menor).abs() < 0.005
    longo["cor"] = [GOLD if b else (PURPLE if f == "Farmazids" else CINZA_BARRA)
                    for b, f in zip(longo["barata"], longo["farmacia"])]
    longo["texto"] = longo["preco"].map(lambda v: fmt_valor(v, "dinheiro"))
    longo["situacao"] = longo["barata"].map({True: "Menor preço", False: "—"})
    longo["teto"] = longo.groupby("produto")["preco"].transform("max") * 1.35  # folga para o rótulo do valor
    base = alt.Chart(longo)
    y = alt.Y("farmacia:N", sort=FARMACIAS, title=None, axis=alt.Axis(labelLimit=120))
    barras = base.mark_bar(cornerRadiusEnd=6).encode(
        y=y, x=alt.X("preco:Q", axis=None),
        color=alt.Color("cor:N", scale=None, legend=None),
        tooltip=[alt.Tooltip("produto:N", title="Produto"), alt.Tooltip("farmacia:N", title="Farmácia"),
                 alt.Tooltip("texto:N", title="Preço no pix"), alt.Tooltip("situacao:N", title="Situação")],
    )
    rotulos = base.mark_text(align="left", dx=6, color=INK, font=fonte).encode(
        y=y, x=alt.X("preco:Q", axis=None), text="texto:N")
    folga = base.mark_point(opacity=0).encode(y=y, x=alt.X("teto:Q", axis=None))
    chart = (
        (barras + rotulos + folga)
        .properties(width=300, height=alt.Step(22))
        .facet(facet=alt.Facet("produto:N", title=None, sort=list(dict.fromkeys(d["produto"])),
                               header=alt.Header(labelFontWeight=600, labelFontSize=13, labelLimit=320,
                                                 labelAlign="left", labelAnchor="start")),
               columns=1)
        .resolve_scale(x="independent", y="independent")
        .configure_view(stroke=None)
        .configure_axis(labelFont=fonte, titleFont=fonte, grid=False, domain=False, ticks=False, labelColor=MUTED)
        .configure_header(labelFont=fonte, labelColor=INK, titleColor=INK)
    )
    return chart.properties(background="rgba(0,0,0,0)") if DARK else chart


def render_comparativo():
    """Seção da página Insights: cartão por produto (lado a lado + régua) e gráfico com a mais barata em dourado."""
    st.markdown(CSS_DESTAQUES, unsafe_allow_html=True)
    st.markdown(
        '<div style="height:48px"></div>'
        f'<h2 class="g-section">{COMPARATIVO["titulo"]}</h2>'
        '<p class="g-cap">Preço no pix de cada produto nas três farmácias (coleta mais recente). '
        'A régua mostra onde a Farmazids fica entre os concorrentes.</p>' + LEGENDA_PRECO,
        unsafe_allow_html=True,
    )
    try:
        with carregando("Consultando os dados..."):
            r = run_insight(COMPARATIVO["pergunta"])
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    d = preparar_comparativo(rows_to_df(r.get("rows") or []))
    if d is None:
        st.info("Sem dados para este comparativo no momento.")
        return
    cartoes = "".join(card_produto(row["produto"], {f: row[f] for f in FARMACIAS}) for _, row in d.iterrows())
    st.markdown(f'<div class="g-prods">{cartoes}</div>', unsafe_allow_html=True)
    # (o gráfico de barras "Preço por farmácia" foi removido: dizia o mesmo que a régua dos cartões)
    with st.expander("Ver tabela e consulta"):
        if r.get("content"):
            st.markdown(md_seguro(r["content"]))
        tabela = d.rename(columns={"produto": "Produto"})
        for f in FARMACIAS:
            tabela[f] = tabela[f].map(lambda v: fmt_valor(v, "dinheiro"))
        st.dataframe(tabela, use_container_width=True, hide_index=True)
        st.code(r["sql"], language="sql")



# ---------- Aba de boas-vindas: o que mudou de uma extração para a outra ----------
# Mesma lógica do alerta de variação de preço (Lambda):
#  - preço real = o menor entre preco_sem_desconto e preco_desconto_pix (Farmazids: preco);
#  - preço do dia = média do preço real do gtin naquele dia (a extração é o dia de data_extracao);
#  - compara a extração mais recente de cada farmácia com a imediatamente anterior (DENSE_RANK por dia).
ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "t1-farmazids-equipe05")
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "t1-farmazids-05")
BV_LIMITE_PCT = 10  # variação mínima (%) para entrar em "Maiores mudanças de preço" (= LIMITE_PCT do alerta)

BV_CTE = """
WITH base AS (
  SELECT 'Farmazids' AS farmacia, CAST(gtin AS varchar) AS gtin, nome, CAST(preco AS double) AS preco_sem_desconto,
         CAST(NULL AS double) AS preco_desconto_pix, data_extracao
  FROM medicamentos_farmazids
  UNION ALL
  SELECT 'FarmaPonte', CAST(gtin AS varchar), nome, CAST(preco_sem_desconto AS double),
         CAST(preco_desconto_pix AS double), data_extracao
  FROM farmaponte_tratado
  UNION ALL
  SELECT 'VeraCruz', CAST(gtin AS varchar), nome, CAST(preco_sem_desconto AS double),
         CAST(preco_desconto_pix AS double), data_extracao
  FROM veracruz_tratado
),
base_dia AS (
  SELECT farmacia, gtin, nome,
         CASE
           WHEN preco_desconto_pix > 0 THEN LEAST(preco_sem_desconto, preco_desconto_pix)
           ELSE preco_sem_desconto
         END AS preco_real,
         date(date_parse(data_extracao, '%d/%m/%Y %H:%i')) AS dia
  FROM base
  WHERE preco_sem_desconto > 0 AND gtin IS NOT NULL AND gtin <> ''
),
precos AS (
  SELECT farmacia, gtin, dia, MAX(nome) AS nome, AVG(preco_real) AS preco
  FROM base_dia
  GROUP BY 1, 2, 3
),
ranqueado AS (
  SELECT *, DENSE_RANK() OVER (PARTITION BY farmacia ORDER BY dia DESC) AS ordem
  FROM precos
)
"""

BV_RESUMO = {
    "colunas": ["farmacia", "coleta_atual", "coleta_anterior", "produtos", "alterados", "novos", "removidos",
                "variacao_media_pct"],
    "sql": BV_CTE + """
, datas AS (
  SELECT farmacia,
         MAX(CASE WHEN ordem = 1 THEN dia END) AS atual,
         MAX(CASE WHEN ordem = 2 THEN dia END) AS anterior
  FROM ranqueado
  GROUP BY 1
),
por_gtin AS (
  SELECT farmacia, gtin,
         MAX(CASE WHEN ordem = 1 THEN preco END) AS novo,
         MAX(CASE WHEN ordem = 2 THEN preco END) AS antigo
  FROM ranqueado
  WHERE ordem <= 2
  GROUP BY 1, 2
)
SELECT p.farmacia,
       date_format(CAST(d.atual AS timestamp), '%d/%m/%Y') AS coleta_atual,
       date_format(CAST(d.anterior AS timestamp), '%d/%m/%Y') AS coleta_anterior,
       COUNT_IF(p.novo IS NOT NULL) AS produtos,
       COUNT_IF(p.novo IS NOT NULL AND p.antigo IS NOT NULL AND ROUND(p.novo, 2) <> ROUND(p.antigo, 2)) AS alterados,
       COUNT_IF(p.novo IS NOT NULL AND p.antigo IS NULL) AS novos,
       COUNT_IF(p.novo IS NULL AND p.antigo IS NOT NULL) AS removidos,
       ROUND(AVG(CASE WHEN p.novo IS NOT NULL AND p.antigo IS NOT NULL AND ROUND(p.novo, 2) <> ROUND(p.antigo, 2)
                      THEN (p.novo - p.antigo) / p.antigo * 100 END), 1) AS variacao_media_pct
FROM por_gtin p
JOIN datas d ON d.farmacia = p.farmacia
GROUP BY p.farmacia, d.atual, d.anterior
""",
}
BV_MUDANCAS = {
    "colunas": ["produto", "farmacia", "preco_anterior", "preco_atual", "variacao_pct"],
    "sql": BV_CTE + """
SELECT n.nome AS produto,
       n.farmacia,
       ROUND(a.preco, 2) AS preco_anterior,
       ROUND(n.preco, 2) AS preco_atual,
       ROUND((n.preco - a.preco) / a.preco * 100, 2) AS variacao_pct
FROM ranqueado n
JOIN ranqueado a
  ON n.farmacia = a.farmacia AND n.gtin = a.gtin
WHERE n.ordem = 1 AND a.ordem = 2
  AND ABS((n.preco - a.preco) / a.preco * 100) >= """ + str(BV_LIMITE_PCT) + """
ORDER BY ABS((n.preco - a.preco) / a.preco * 100) DESC
LIMIT 6
""",
}


class _SqlFalhou(RuntimeError):
    """A consulta rodou no Athena mas falhou (erro de SQL, tempo esgotado...)."""


@functools.lru_cache(maxsize=None)
def get_athena():
    return boto3.client("athena", region_name=AWS_REGION,
                        config=Config(read_timeout=60, connect_timeout=10, retries={"max_attempts": 2}))


def _athena_direto(sql: str, timeout_s: int = 90) -> list:
    """Roda o SQL no Athena (mesmo banco e workgroup do alerta) e devolve o ResultSet (1ª linha = cabeçalho)."""
    athena = get_athena()
    qid = athena.start_query_execution(
        QueryString=sql, QueryExecutionContext={"Database": ATHENA_DATABASE}, WorkGroup=ATHENA_WORKGROUP,
    )["QueryExecutionId"]
    limite = time.time() + timeout_s
    while True:
        status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if status["State"] == "SUCCEEDED":
            break
        if status["State"] in ("FAILED", "CANCELLED"):
            raise _SqlFalhou(f"Athena terminou com {status['State']}: {status.get('StateChangeReason', 'sem detalhe')}")
        if time.time() > limite:
            raise _SqlFalhou("A consulta demorou mais que o esperado.")
        time.sleep(1)
    linhas, token = [], None
    while True:
        args = {"QueryExecutionId": qid, **({"NextToken": token} if token else {})}
        pagina = athena.get_query_results(**args)
        linhas += pagina["ResultSet"]["Rows"]
        token = pagina.get("NextToken")
        if not token:
            return linhas


@st.cache_data(ttl=3600, show_spinner=False)
def run_bv(sql: str) -> dict:
    """SQL fixo da aba de boas-vindas. Direto no Athena; sem permissão, pede à state machine o mesmo SQL."""
    try:
        return {"sql": sql, "rows": _athena_direto(sql)}
    except (ClientError, BotoCoreError) as exc:
        resultado = generate_reply("Execute exatamente este SQL no Athena, sem alterá-lo, e devolva as linhas:\n" + sql)
        if not resultado.get("sql"):
            raise RuntimeError(f"{exc} | {resultado['content']}") from exc
        return resultado


CSS_BV = """
<style>
.g-bv-hero { display: flex; flex-direction: column; align-items: center; text-align: center; margin: var(--spacing-16) 0 var(--section-gap); }
.g-bv-hero .g-brand { align-items: center; }
.g-bv-hero .g-logo-img { height: 170px; margin: 0 auto var(--spacing-24); }
.g-bv-hero .g-sub { margin-left: auto; margin-right: auto; }
.g-bv-hero .g-cta { justify-content: center; }
.g-mudancas { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: var(--spacing-16);
  margin: var(--spacing-16) 0 var(--spacing-24); }
.g-mud, .g-mov { background: var(--surface-card); border-radius: var(--radius-cards); padding: var(--card-padding);
  display: flex; flex-direction: column; gap: var(--spacing-12); }
.g-mud.nossa { box-shadow: inset 0 0 0 1.5px var(--color-brand); }
.g-mud-topo, .g-mov-topo { display: flex; justify-content: space-between; align-items: center; gap: var(--spacing-8); }
.g-mud-nome { font-size: var(--text-subheading); font-weight: var(--font-weight-semibold); letter-spacing: var(--tracking-subheading); }
.g-mud.nossa .g-mud-nome { color: var(--color-brand); }
.g-mud-datas, .g-chip { font-size: var(--text-caption); line-height: 1.5; letter-spacing: 0; color: var(--color-graphite);
  border: 1px solid rgba(128,128,128,.35); border-radius: var(--radius-tags); padding: 1px var(--spacing-12); white-space: nowrap; }
.g-chip.nossa { border-color: var(--color-brand); color: var(--color-brand); font-weight: var(--font-weight-semibold); }
.g-mud-grande { font-size: var(--text-heading); line-height: var(--leading-heading); letter-spacing: var(--tracking-heading);
  font-weight: var(--font-weight-semibold); }
.g-pv { font-weight: var(--font-weight-semibold); letter-spacing: 0; white-space: nowrap; }
.g-pv.cai { color: __UP__; }
.g-pv.sobe { color: __DOWN__; }
.g-pv.igual { color: var(--color-slate-mid); }
.g-barra { height: 8px; border-radius: 8px; background: rgba(128,128,128,.3); overflow: hidden; }
.g-barra i { display: block; height: 100%; background: var(--color-brand); border-radius: 8px; }
.g-mov-nome { font-weight: var(--font-weight-semibold); line-height: 1.3; min-height: 2.6em; }
.g-lado.dois { grid-template-columns: repeat(2, 1fr); }
.g-regua-seg { position: absolute; top: 38px; height: 4px; border-radius: 4px; }
.g-bv-legenda { font-size: var(--text-caption); letter-spacing: 0; color: var(--color-slate-mid); margin: var(--spacing-4) 0 0; }
</style>
""".replace("__UP__", UP_COR).replace("__DOWN__", DOWN_COR)


def _num(v) -> str:
    try:
        return f"{int(round(float(v))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _dia(v) -> str:
    """'2026-10-16' ou '16/10/2026' → '16/10'."""
    t = str(v or "").strip()[:10]
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return f"{m.group(3)}/{m.group(2)}"
    m = re.fullmatch(r"(\d{2})/(\d{2})/\d{4}", t)
    return f"{m.group(1)}/{m.group(2)}" if m else (t or "—")


def _saudacao() -> str:
    try:
        from zoneinfo import ZoneInfo
        h = datetime.now(ZoneInfo("America/Sao_Paulo")).hour
    except Exception:
        h = datetime.now().hour
    return "Bom dia" if h < 12 else ("Boa tarde" if h < 18 else "Boa noite")


def pv_html(pct) -> str:
    """Variação de preço: ↓ verde (caiu), ↑ vermelho (subiu)."""
    if pd.isna(pct):
        return '<span class="g-pv igual">—</span>'
    if pct > 0.05:
        return f'<span class="g-pv sobe">↑ {fmt_valor(pct, "pct")}</span>'
    if pct < -0.05:
        return f'<span class="g-pv cai">↓ {fmt_valor(abs(pct), "pct")}</span>'
    return '<span class="g-pv igual">→ 0%</span>'


def preparar_resumo(bruto):
    if bruto is None or bruto.shape[1] < 8:
        return None
    d = bruto.iloc[:, :8].copy()
    d.columns = BV_RESUMO["colunas"]
    for c in ("produtos", "alterados", "novos", "removidos", "variacao_media_pct"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["farmacia", "produtos"])
    d["_o"] = d["farmacia"].map({f: i for i, f in enumerate(FARMACIAS)}).fillna(9)
    d = d.sort_values("_o").drop(columns="_o")
    return d.reset_index(drop=True) if not d.empty else None


def preparar_mudancas(bruto):
    if bruto is None or bruto.shape[1] < 5:
        return None
    d = bruto.iloc[:, :5].copy()
    d.columns = BV_MUDANCAS["colunas"]
    for c in ("preco_anterior", "preco_atual"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["produto", "preco_anterior", "preco_atual"])
    d = d[(d["preco_anterior"] > 0) & (d["preco_atual"] > 0) & (d["preco_anterior"] != d["preco_atual"])]
    d["variacao_pct"] = (d["preco_atual"] - d["preco_anterior"]) / d["preco_anterior"] * 100
    d = d.reindex(d["variacao_pct"].abs().sort_values(ascending=False).index)
    return d.head(6).reset_index(drop=True) if not d.empty else None


def _caixa(rotulo: str, valor, extra: str = "") -> str:
    return (f'<div class="g-col {extra}"><div class="g-col-nome">{rotulo}</div>'
            f'<div class="g-col-preco">{_num(valor)}</div></div>')


def card_farmacia(r) -> str:
    """Cartão por farmácia: variação média, alterados/novos/removidos e % do catálogo que mudou."""
    total, alt = r["produtos"], r["alterados"]
    pct = (alt / total * 100) if total and pd.notna(alt) else 0.0
    nossa = " nossa" if r["farmacia"] == "Farmazids" else ""
    return (
        f'<div class="g-mud{nossa}"><div class="g-mud-topo"><span class="g-mud-nome">{esc(str(r["farmacia"]))}</span>'
        f'<span class="g-mud-datas">{_dia(r["coleta_anterior"])} → {_dia(r["coleta_atual"])}</span></div>'
        f'<div><div class="g-mud-grande">{pv_html(r["variacao_media_pct"])}</div>'
        f'<div class="g-cap">variação média dos preços que mudaram</div></div>'
        f'<div class="g-lado">{_caixa("Alterados", alt, "nossa" if nossa else "")}{_caixa("Novos", r["novos"])}'
        f'{_caixa("Removidos", r["removidos"])}</div>'
        f'<div><div class="g-barra"><i style="width:{min(pct, 100):.1f}%"></i></div>'
        f'<div class="g-regua-ext" style="margin:6px 0 0"><span>{fmt_valor(pct, "pct")} do catálogo mudou de preço</span>'
        f'<span>{_num(total)} produtos</span></div></div></div>'
    )


def regua_mov(antes: float, agora: float) -> str:
    """Régua de movimento: ponto cinza (antes) → ponto roxo (agora), com o trecho colorido pela direção."""
    lo, hi = min(antes, agora), max(antes, agora)
    pos = lambda p: 50.0 if hi - lo < 0.005 else 6 + (p - lo) / (hi - lo) * 88
    xa, xb = pos(antes), pos(agora)
    cor = UP_COR if agora < antes else DOWN_COR
    return (
        '<div class="g-regua"><div class="g-regua-trilho"></div>'
        f'<div class="g-regua-seg" style="left:{min(xa, xb):.1f}%;width:{abs(xa - xb):.1f}%;background:{cor}"></div>'
        f'<div class="g-regua-marca" style="left:{xa:.1f}%" title="Antes: {_rs(antes)}"></div>'
        f'<div class="g-regua-marca nossa" style="left:{xb:.1f}%" title="Agora: {_rs(agora)}"></div>'
        f'<div class="g-regua-rot b0" style="left:{min(max(xa, 12), 88):.1f}%">antes</div>'
        f'<div class="g-regua-rot topo" style="left:{min(max(xb, 12), 88):.1f}%">agora</div></div>'
    )


def card_mudanca(r) -> str:
    nossa = " nossa" if r["farmacia"] == "Farmazids" else ""
    return (
        f'<div class="g-mov"><div class="g-mov-topo"><span class="g-chip{nossa}">{esc(str(r["farmacia"]))}</span>'
        f'{pv_html(r["variacao_pct"])}</div><div class="g-mov-nome">{esc(str(r["produto"]))}</div>'
        f'<div class="g-lado dois"><div class="g-col"><div class="g-col-nome">Antes</div>'
        f'<div class="g-col-preco">{_rs(r["preco_anterior"])}</div></div>'
        f'<div class="g-col nossa"><div class="g-col-nome">Agora</div>'
        f'<div class="g-col-preco">{_rs(r["preco_atual"])}</div></div></div>'
        f'{regua_mov(r["preco_anterior"], r["preco_atual"])}</div>'
    )


def gerar_pdf_boas_vindas(saud: str, nome: str, resumo, mudancas) -> bytes:
    """PDF (A4 paisagem) com o que está na aba de boas-vindas: resumo por farmácia + maiores mudanças de preço.
    Sempre em tema claro. Precisa de: py -m pip install reportlab"""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    roxo, tinta, mudo = colors.HexColor("#6d3fc0"), colors.HexColor("#1c1c1e"), colors.HexColor("#676768")
    grade, fundo = colors.HexColor("#e6e3ee"), colors.HexColor("#f3f1f8")
    ouro, verde, verm = colors.HexColor("#c4a054"), colors.HexColor("#1f9d63"), colors.HexColor("#d64545")
    try:
        from zoneinfo import ZoneInfo
        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    except Exception:
        agora = datetime.now()
    quando = agora.strftime("%d/%m/%Y às %H:%M")

    def estilo(nome_, **kw):
        base = dict(fontName="Helvetica", fontSize=10, leading=13, textColor=tinta)
        base.update(kw)
        return ParagraphStyle(nome_, **base)

    titulo = estilo("titulo", fontName="Helvetica-Bold", fontSize=28, leading=33)
    h2 = estilo("h2", fontName="Helvetica-Bold", fontSize=15, leading=19)
    rotulo = estilo("rot", fontSize=8.5, leading=11, textColor=roxo)
    corpo = estilo("corpo", fontSize=10.5, leading=15)
    mini = estilo("mini", fontSize=8, leading=10.5, textColor=mudo)
    mini_c = estilo("mini_c", parent=mini, alignment=1)
    cab = estilo("cab", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=roxo)
    cel = estilo("cel", fontSize=9, leading=12)

    def P(t, st_=corpo):
        return Paragraph(escape(_pdf_texto(t)).replace("\n", "<br/>"), st_)

    def cor_var(p):
        return mudo if pd.isna(p) or abs(p) <= 0.05 else (verm if p > 0 else verde)

    def txt_var(p):  # sem setas: a fonte padrão do PDF não tem ↑/↓
        if pd.isna(p):
            return "sem dados"
        if abs(p) <= 0.05:
            return "estável (0%)"
        return f"{'subiu' if p > 0 else 'caiu'} {fmt_valor(abs(p), 'pct')}"

    def var_par(p, tam, negrito=True):
        cor = cor_var(p).hexval().replace("0x", "#")
        fonte = "Helvetica-Bold" if negrito else "Helvetica"
        return Paragraph(f'<font name="{fonte}" size="{tam}" color="{cor}">{escape(_pdf_texto(txt_var(p)))}</font>',
                         estilo(f"v{tam}", fontSize=tam, leading=tam + 4))

    def data_completa(v):
        t = str(v or "").strip()[:10]
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else (t or "-")

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
    caminho = Path(__file__).parent / "logo_farmazids.png"
    if caminho.exists():
        png = caminho.read_bytes()
        iw, ih = ImageReader(io.BytesIO(png)).getSize()
        k = min(8 * cm / iw, 2.2 * cm / ih)
        logo = Image(io.BytesIO(png), width=iw * k, height=ih * k)
        logo.hAlign = "LEFT"
        historia += [logo, Spacer(1, 0.5 * cm)]
    ola = f"{saud}, {nome}" if nome else f"{saud}!"
    historia += [Paragraph("BOAS-VINDAS", rotulo), P(ola, titulo), Spacer(1, 0.1 * cm),
                 P("O que mudou nos preços entre as duas últimas extrações de cada farmácia.", corpo),
                 Spacer(1, 0.6 * cm)]

    # ----- resumo por farmácia: três cartões lado a lado -----
    if resumo is not None and not resumo.empty:
        historia += [P("O que mudou", h2), Spacer(1, 0.25 * cm)]
        cartoes = []
        for _, r in resumo.iterrows():
            total, alt = r["produtos"], r["alterados"]
            pct = (alt / total * 100) if total and pd.notna(alt) else 0.0
            nossa = r["farmacia"] == "Farmazids"
            numeros = Table(
                [[P(_num(alt), estilo("n1", fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=1)),
                  P(_num(r["novos"]), estilo("n2", fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=1)),
                  P(_num(r["removidos"]), estilo("n3", fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=1))],
                 [P("Alterados", mini_c), P("Novos", mini_c), P("Removidos", mini_c)]],
                colWidths=[2.5 * cm] * 3)
            numeros.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
            cartoes.append([
                P(r["farmacia"], estilo("nf", fontName="Helvetica-Bold", fontSize=13, leading=16,
                                        textColor=roxo if nossa else tinta)),
                P(f"Extração de {data_completa(r['coleta_anterior'])} para {data_completa(r['coleta_atual'])}", mini),
                Spacer(1, 0.25 * cm), var_par(r["variacao_media_pct"], 15),
                P("variação média dos preços que mudaram", mini), Spacer(1, 0.25 * cm), numeros, Spacer(1, 0.2 * cm),
                P(f"{fmt_valor(pct, 'pct')} do catálogo mudou de preço · {_num(total)} produtos", mini),
            ])
        n = len(cartoes)
        larg = (26.7 * cm - (n - 1) * 0.4 * cm) / n
        linha, cols = [], []
        for i, c in enumerate(cartoes):
            linha.append(c)
            cols.append(larg)
            if i < n - 1:
                linha.append("")
                cols.append(0.4 * cm)
        t = Table([linha], colWidths=cols)
        estilos = [("VALIGN", (0, 0), (-1, -1), "TOP")]
        for i, (_, r) in enumerate(resumo.iterrows()):
            col = i * 2
            estilos += [("BACKGROUND", (col, 0), (col, 0), fundo), ("LINEABOVE", (col, 0), (col, 0), 2.5,
                                                                    roxo if r["farmacia"] == "Farmazids" else ouro),
                        ("LEFTPADDING", (col, 0), (col, 0), 10), ("RIGHTPADDING", (col, 0), (col, 0), 10),
                        ("TOPPADDING", (col, 0), (col, 0), 8), ("BOTTOMPADDING", (col, 0), (col, 0), 8)]
        t.setStyle(TableStyle(estilos))
        historia += [t, Spacer(1, 0.6 * cm)]

    # ----- maiores mudanças de preço -----
    if mudancas is not None and not mudancas.empty:
        linhas = [[Paragraph(c, cab) for c in ("FARMÁCIA", "PRODUTO", "ANTES", "AGORA", "VARIAÇÃO")]]
        for _, r in mudancas.iterrows():
            linhas.append([P(r["farmacia"], cel), P(r["produto"], cel), P(fmt_valor(r["preco_anterior"], "dinheiro"), cel),
                           P(fmt_valor(r["preco_atual"], "dinheiro"), cel), var_par(r["variacao_pct"], 9)])
        tab = Table(linhas, colWidths=[3.2 * cm, 13 * cm, 3 * cm, 3 * cm, 4.5 * cm], repeatRows=1)
        tab.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, grade), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                 ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
        historia.append(KeepTogether([
            P("Maiores mudanças de preço", h2), Spacer(1, 0.15 * cm),
            P(f"Os produtos que mais variaram de uma extração para a outra (variação de {BV_LIMITE_PCT}% ou mais).", mini),
            Spacer(1, 0.2 * cm), tab]))
    historia += [Spacer(1, 0.5 * cm),
                 P("O preço considerado é o menor entre o preço sem desconto e o pix, em média no dia, e a comparação é "
                   "entre a extração mais recente e a imediatamente anterior de cada farmácia.", mini)]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.6 * cm, title=f"Boas-vindas · {BOT_NAME}")
    doc.build(historia, onFirstPage=moldura, onLaterPages=moldura)
    return buf.getvalue()


def render_boas_vindas():
    """Primeira tela após o login: saudação + o que mudou entre as duas últimas extrações de preços."""
    st.markdown(CSS_DESTAQUES + CSS_BV, unsafe_allow_html=True)
    saud = _saudacao()
    nome = str(st.session_state.get("usuario") or "").split("@")[0].replace(".", " ").replace("_", " ").strip().title()
    ola = f"{saud}, <em>{esc(nome)}</em>" if nome else f"{saud}!"
    st.markdown(
        f'<div class="g-bv-hero"><div class="g-brand">{load_logo()}<span class="g-tag">Boas-vindas</span></div>'
        f'<h1 class="g-title" style="font-size:clamp(40px,6vw,64px)">{ola}</h1>'
        f'<p class="g-sub">Veja o que mudou nos preços entre as duas últimas extrações de cada farmácia.</p>'
        f'<div class="g-cta"><a class="g-btn fill" href="#novidades">Ver o que mudou</a></div></div>',
        unsafe_allow_html=True,
    )
    slot_pdf = st.container()  # o botão de PDF aparece aqui, logo abaixo da saudação, quando os dados chegam
    st.markdown(
        f'<div id="novidades"><h2 class="g-section">O que mudou</h2>'
        f'<p class="g-cap">Comparação entre a extração mais recente e a anterior de cada farmácia. O preço considerado é o menor entre o preço sem desconto e o pix, em média no dia.</p>'
        f'<p class="g-bv-legenda">↓ o preço caiu · ↑ o preço subiu</p></div>',
        unsafe_allow_html=True,
    )
    resumo = mudancas = None
    consultas = []  # só aparecem no modo diagnóstico (?debug=1)
    try:
        with carregando("Buscando o que mudou..."):
            try:
                r1 = run_bv(BV_RESUMO["sql"])
                resumo = preparar_resumo(rows_to_df(r1.get("rows") or []))
                consultas.append(("Resumo por farmácia", r1))
            except RuntimeError as exc:
                st.warning(f"Não consegui montar o resumo por farmácia: {exc}")
            try:
                r2 = run_bv(BV_MUDANCAS["sql"])
                mudancas = preparar_mudancas(rows_to_df(r2.get("rows") or []))
                consultas.append(("Maiores mudanças de preço", r2))
            except RuntimeError as exc:
                st.warning(f"Não consegui montar as maiores mudanças de preço: {exc}")
    except Exception as exc:  # noqa: BLE001 - a tela de boas-vindas nunca deve derrubar o app
        st.warning(f"Não foi possível carregar as novidades agora: {exc}")

    if resumo is not None:
        st.markdown('<div class="g-mudancas">' + "".join(card_farmacia(r) for _, r in resumo.iterrows()) + "</div>",
                    unsafe_allow_html=True)
    if mudancas is not None:
        st.markdown('<h2 class="g-section" style="font-size:var(--text-heading);margin-top:var(--spacing-24)">'
                    'Maiores mudanças de preço</h2>'
                    f'<p class="g-cap">Os produtos que mais variaram de uma extração para a outra (variação de {BV_LIMITE_PCT}% ou mais).</p>',
                    unsafe_allow_html=True)
        st.markdown('<div class="g-mudancas">' + "".join(card_mudanca(r) for _, r in mudancas.iterrows()) + "</div>",
                    unsafe_allow_html=True)
    if resumo is None and mudancas is None:
        st.info("Ainda não há duas extrações para comparar.")
    else:
        with slot_pdf:
            try:
                pdf_bytes = gerar_pdf_boas_vindas(saud, nome, resumo, mudancas)
                _, c_pdf, _ = st.columns([1.3, 1, 1.3])
                c_pdf.download_button("Baixar PDF", pdf_bytes, key="bv_pdf", type="primary", use_container_width=True,
                                      file_name=f"boas_vindas_zids_{datetime.now():%Y-%m-%d}.pdf", mime="application/pdf")
            except ImportError:
                st.caption("Para baixar o PDF, instale: py -m pip install reportlab")
            except Exception as exc:  # noqa: BLE001
                st.caption(f"Não foi possível gerar o PDF: {exc}")

    c1, c2, _ = st.columns([1.4, 1.2, 4], gap="small")
    if c1.button("Conversar com o Zids", key="bv_chat", type="primary", use_container_width=True):
        st.session_state.page = "chat"
        st.rerun()
    if c2.button("Ver insights", key="bv_insights", use_container_width=True):
        st.session_state.page = "insights"
        st.rerun()
    if st.query_params.get("debug") == "1" and consultas:  # diagnóstico: abra o app com ?debug=1
        with st.expander("Diagnóstico: SQL gerado e linhas brutas"):
            for titulo, r in consultas:
                st.markdown(f"**{titulo}**")
                st.code(r["sql"], language="sql")
                st.dataframe(rows_to_df(r.get("rows") or []), use_container_width=True, hide_index=True)


def render_insights():
    iniciar_insights()  # dispara as 6 consultas juntas; os cards abaixo só esperam o resultado
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
            limpar_insights()
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
            f'<img src="{ZIDS_INSIGHTS_GIF}" alt="{BOT_NAME}" style="object-position:50% 50%"></div></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div style="height:32px"></div>', unsafe_allow_html=True)
    cols = st.columns(2)
    for i, spec in enumerate(INSIGHTS):
        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(f'<div class="g-label">{spec["titulo"]}</div>', unsafe_allow_html=True)
                if spec.get("descricao"):
                    st.caption(spec["descricao"])
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
    render_comparativo()



# ---------- Página: Simulador de preço ----------
# O usuário escolhe um produto, informa o custo (ou a margem atual) e move o controle de variação:
# o app mostra a posição da Farmazids frente à FarmaPonte e à Vera Cruz e quanto de margem se perde.
# Três consultas (cacheadas por 1 h em run_bv), todas por GTIN e na coleta mais recente; a conta roda no app.
SIM_CSS = """
<style>
.g-sim-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: var(--spacing-16); margin: var(--spacing-16) 0; }
.g-sim-card { background: var(--surface-card); border-radius: var(--radius-cards); padding: var(--card-padding);
  display: flex; flex-direction: column; gap: var(--spacing-4); }
.g-sim-card.nossa { box-shadow: inset 0 0 0 1.5px var(--color-brand); }
.g-sim-rot { font-size: var(--text-caption); line-height: 1.4; letter-spacing: 0; color: var(--color-slate-mid); text-transform: uppercase; }
.g-sim-val { font-size: var(--text-heading); line-height: var(--leading-heading); letter-spacing: var(--tracking-heading);
  font-weight: var(--font-weight-semibold); }
.g-sim-val.perde { color: __DOWN__; }
.g-sim-val.ganha { color: __UP__; }
.g-sim-sub { font-size: var(--text-caption); line-height: 1.5; letter-spacing: 0; color: var(--color-graphite); }
.g-sim-nota { font-size: var(--text-caption); letter-spacing: 0; color: var(--color-slate-mid); margin: var(--spacing-8) 0; }
</style>
""".replace("__UP__", UP_COR).replace("__DOWN__", DOWN_COR)

SIM_CSS_ESCURO = """
<style>
/* Campos no modo escuro: pinta o campo inteiro (o último bloco do widget, depois do rótulo) e tudo que há dentro dele.
   Não depende dos nomes internos do BaseWeb, que mudam entre versões do Streamlit. */
[data-testid="stTextInput"] > div:last-child, [data-testid="stTextInput"] > div:last-child div,
[data-testid="stNumberInput"] > div:last-child, [data-testid="stNumberInput"] > div:last-child div,
[data-testid="stSelectbox"] > div:last-child, [data-testid="stSelectbox"] > div:last-child div,
[data-testid="stTextInput"] [data-baseweb="input"], [data-testid="stTextInput"] [data-baseweb="base-input"],
[data-testid="stNumberInput"] [data-baseweb="input"], [data-testid="stNumberInput"] [data-baseweb="base-input"],
[data-testid="stSelectbox"] [data-baseweb="select"], [data-testid="stSelectbox"] [data-baseweb="select"] div {
  background-color: #2a2236 !important; background-image: none !important; }
[data-testid="stTextInput"] [data-baseweb="input"], [data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="stSelectbox"] [data-baseweb="select"] > div { border: 1px solid rgba(255,255,255,.14) !important; }
/* Texto digitado, valor escolhido e placeholder */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input, [data-testid="stSelectbox"] input,
[data-testid="stSelectbox"] > div:last-child * {
  color: #e6e1f0 !important; -webkit-text-fill-color: #e6e1f0 !important; caret-color: #e6e1f0 !important; }
[data-testid="stNumberInput"] input, [data-testid="stSelectbox"] input { background-color: transparent !important; }
/* Campo de texto (Buscar medicamento): pinta o próprio input e os dois blocos que o envolvem, seja qual for o nome interno */
input[type="text"], input[type="search"] {
  background-color: #2a2236 !important; color: #e6e1f0 !important; -webkit-text-fill-color: #e6e1f0 !important;
  caret-color: #e6e1f0 !important; border-radius: 8px; }
div:has(> input[type="text"]), div:has(> div > input[type="text"]),
div:has(> input[type="search"]), div:has(> div > input[type="search"]) {
  background-color: #2a2236 !important; background-image: none !important; border-color: rgba(255,255,255,.14) !important; }
input[type="text"]:-webkit-autofill { -webkit-box-shadow: 0 0 0 1000px #2a2236 inset !important; -webkit-text-fill-color: #e6e1f0 !important; }
[data-testid="stTextInput"] input::placeholder, [data-testid="stNumberInput"] input::placeholder { color: #a9a4b8 !important; -webkit-text-fill-color: #a9a4b8 !important; }
[data-testid="stSelectbox"] svg, [data-testid="stNumberInput"] svg { color: #c9c5d3 !important; fill: #c9c5d3 !important; }
[data-testid="stNumberInput"] button { background-color: #3a3048 !important; color: #c9c5d3 !important; }
[data-testid="stNumberInput"] button:hover { background-color: #4a3d5e !important; }
/* Lista que se abre no seletor de produto */
[data-baseweb="popover"] ul, [data-baseweb="menu"] { background-color: #1c1528 !important; }
[data-baseweb="popover"] li, [data-baseweb="menu"] li { background-color: transparent !important; color: #e6e1f0 !important; }
[data-baseweb="popover"] li:hover, [data-baseweb="menu"] li:hover, [data-baseweb="menu"] li[aria-selected="true"] { background-color: #2a2236 !important; }
</style>
"""

_MENOR_PRECO_SQL = ("LEAST(COALESCE(preco_sem_desconto, preco_desconto_pix), "
                    "COALESCE(preco_desconto_pix, preco_sem_desconto))")


def _dia_recente_sql(tabela: str) -> str:
    dia = "date(date_parse(data_extracao, '%d/%m/%Y %H:%i'))"
    return f"{dia} = (SELECT MAX({dia}) FROM {tabela})"


def _termo_busca(texto: str) -> str:
    """Texto digitado → padrão de LIKE sem acento (só letras, números e . + -; palavras viram %)."""
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    t = re.sub(r"[^a-z0-9 .+-]", " ", t)
    return "%".join(t.split())


def sql_busca_produto(termo: str) -> str:
    """Produtos do catálogo da Farmazids (coleta mais recente) cujo nome contém o termo, sem diferenciar acento."""
    return ("SELECT gtin, MAX(nome) AS nome FROM medicamentos_farmazids "
            "WHERE regexp_replace(normalize(LOWER(nome), NFD), '\\p{M}', '') LIKE '%" + _termo_busca(termo) + "%' AND "
            + _dia_recente_sql("medicamentos_farmazids") + " GROUP BY gtin ORDER BY 2 LIMIT 30")


def sql_precos_produto(gtin: str) -> str:
    """Preço do produto nas três farmácias (coleta mais recente), casado pelo GTIN."""
    def bloco(rotulo: str, tabela: str, preco: str, disp: str) -> str:
        return (f"SELECT '{rotulo}' AS farmacia, MAX(nome) AS nome, {preco} AS preco, {disp} AS disponibilidade, "
                f"(SELECT date_format(MAX(date(date_parse(data_extracao, '%d/%m/%Y %H:%i'))), '%d/%m/%Y') FROM {tabela}) AS coleta "
                f"FROM {tabela} WHERE gtin = '{gtin}' AND {_dia_recente_sql(tabela)}")
    return " UNION ALL ".join([
        bloco("Farmazids", "medicamentos_farmazids", "MAX(preco)", "CAST(NULL AS varchar)"),
        bloco("FarmaPonte", "farmaponte_tratado", f"MIN({_MENOR_PRECO_SQL})", "MAX(disponibilidade)"),
        bloco("VeraCruz", "veracruz_tratado", f"MIN({_MENOR_PRECO_SQL})", "MAX(disponibilidade)"),
    ]) + " LIMIT 10"


def sql_unidades_mes(gtin: str) -> str:
    """Unidades vendidas pela Farmazids no mês da maior data_venda da carga mais recente."""
    carga = '"$file_modified_time" = (SELECT MAX("$file_modified_time") FROM historico_farmazids)'
    return ("SELECT SUM(h.quantidade_vendida) AS unidades, "
            f"(SELECT date_format(MAX(data_venda), '%m/%Y') FROM historico_farmazids WHERE {carga}) AS mes "
            f"FROM historico_farmazids h WHERE h.farmacia = 'farmazids' AND h.gtin = '{gtin}' AND h.{carga} "
            f"AND date_format(h.data_venda, '%Y-%m') = "
            f"(SELECT date_format(MAX(data_venda), '%Y-%m') FROM historico_farmazids WHERE {carga}) LIMIT 1")


def _carregar_precos(gtin: str):
    d = rows_to_df(run_bv(sql_precos_produto(gtin)).get("rows") or [])
    if d is None or d.shape[1] < 5:
        return None
    d = d.iloc[:, :5].copy()
    d.columns = ["farmacia", "nome", "preco", "disponibilidade", "coleta"]
    d["preco"] = pd.to_numeric(d["preco"], errors="coerce")
    return d.set_index("farmacia")


def _carregar_unidades(gtin: str):
    """(unidades, 'mm/aaaa') do último mês com vendas; (None, None) se não houver ou a consulta falhar."""
    try:
        d = rows_to_df(run_bv(sql_unidades_mes(gtin)).get("rows") or [])
        if d is None or d.shape[1] < 2:
            return None, None
        u = pd.to_numeric(d.iloc[0, 0], errors="coerce")
        return (None if pd.isna(u) else float(u)), d.iloc[0, 1]
    except Exception:  # noqa: BLE001 - as unidades são opcionais: o simulador funciona sem elas
        return None, None


def _indisponivel(v) -> bool:
    return any(p in str(v or "").lower() for p in ("indispon", "esgot", "sem estoque"))


def simular(preco: float, var_pct: float, concorrentes: dict, custo=None, unidades: float = 0.0, ganho_pct: float = 0.0) -> dict:
    """Posição no mercado e margem para um novo preço. Margem = (preço − custo) / preço."""
    novo = round(preco * (1 + var_pct / 100), 2)
    precos_c = {f: p for f, p in concorrentes.items() if pd.notna(p)}
    posicao = lambda p: 1 + sum(1 for c in precos_c.values() if c < p - 0.005)
    empate = lambda p: any(abs(c - p) < 0.005 for c in precos_c.values())
    r = {
        "novo": novo, "total": 1 + len(precos_c),
        "pos_hoje": posicao(preco), "pos_novo": posicao(novo),
        "empate_hoje": empate(preco), "empate_novo": empate(novo),
        "menor_conc": min(precos_c.values()) if precos_c else None,
        "igualar": {f: (p / preco - 1) * 100 for f, p in precos_c.items()},
        "custo": None,
    }
    if custo is not None and custo > 0:
        m_atual, m_novo = preco - custo, novo - custo
        lucro_atual = unidades * m_atual
        lucro_novo = unidades * (1 + ganho_pct / 100) * m_novo
        r.update(
            custo=custo, perda_un=preco - novo,
            m_atual_un=m_atual, m_novo_un=m_novo,
            m_atual_pct=m_atual / preco * 100, m_novo_pct=(m_novo / novo * 100) if novo > 0 else None,
            lucro_atual=lucro_atual, lucro_novo=lucro_novo, delta=lucro_novo - lucro_atual,
            equilibrio=((m_atual / m_novo - 1) * 100) if m_atual > 0 and m_novo > 0 else None,
        )
    return r


def _pct_sinal(v: float) -> str:
    return ("+" if v > 0.05 else "") + fmt_valor(v, "pct")


def _card_sim(rotulo: str, valor: str, sub: str = "", cls: str = "", nossa: bool = False) -> str:
    return (f'<div class="g-sim-card{" nossa" if nossa else ""}"><div class="g-sim-rot">{rotulo}</div>'
            f'<div class="g-sim-val {cls}">{valor}</div><div class="g-sim-sub">{sub}</div></div>')


def render_simulador():
    st.markdown(CSS_DESTAQUES + CSS_BV + SIM_CSS + (SIM_CSS_ESCURO if DARK else ""), unsafe_allow_html=True)
    st.markdown(
        '<span class="g-tag">Simulador</span>'
        '<h1 class="g-title" style="font-size:clamp(36px,5vw,56px)">Simulador de preço</h1>'
        '<p class="g-sub">Teste “e se eu baixar X% neste produto?”: veja em que posição a Farmazids fica entre as '
        'farmácias e quanto de margem se perde.</p>',
        unsafe_allow_html=True,
    )

    termo = st.text_input("Buscar medicamento", key="sim_termo", placeholder="Ex.: dipirona 500mg, glifage, losartana",
                          help="Busca no catálogo da Farmazids, sem diferenciar acentos. Aperte Enter para buscar.")
    if len(_termo_busca(termo).replace("%", "")) < 2:
        st.info("Digite ao menos 2 letras do nome do medicamento para começar.")
        return
    try:
        with carregando("Buscando o medicamento..."):
            achados = rows_to_df(run_bv(sql_busca_produto(termo)).get("rows") or [])
    except RuntimeError as exc:
        st.warning(f"Não consegui buscar o medicamento agora: {exc}")
        return
    if achados is None or achados.empty:
        st.info("Nenhum medicamento do catálogo da Farmazids encontrado com esse nome.")
        return
    nomes = dict(zip(achados["gtin"], achados["nome"]))
    gtin = st.selectbox("Produto", list(nomes), format_func=lambda g: nomes[g], key=f"sim_prod_{_termo_busca(termo)}",
                        help=None if len(nomes) < 30 else "Mostrando os 30 primeiros: refine a busca para ver outros.")
    if not re.fullmatch(r"\d{6,14}", str(gtin)):
        st.warning("Este produto não tem um GTIN válido para comparar entre as farmácias.")
        return

    try:
        with carregando("Consultando os preços..."):
            precos = _carregar_precos(gtin)
            unid_padrao, mes_ref = _carregar_unidades(gtin)
    except RuntimeError as exc:
        st.warning(f"Não consegui consultar os preços agora: {exc}")
        return
    if precos is None or pd.isna(precos.loc["Farmazids", "preco"] if "Farmazids" in precos.index else float("nan")):
        st.warning("Não há preço da Farmazids para este produto na coleta mais recente.")
        return

    preco = float(precos.loc["Farmazids", "preco"])
    conc = {f: (float(precos.loc[f, "preco"]) if f in precos.index and pd.notna(precos.loc[f, "preco"]) else float("nan"))
            for f in FARMACIAS[1:]}
    nome = str(precos.loc["Farmazids", "nome"] or nomes[gtin])
    if not any(pd.notna(p) for p in conc.values()):
        st.info("Nenhum concorrente tem este produto (mesmo GTIN) na coleta mais recente: não há posição para comparar.")
        return

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    var = st.slider("Variação no preço da Farmazids", -30.0, 10.0, -5.0, 0.5, format="%.1f%%", key=f"sim_var_{gtin}")
    if DARK:  # trilho dourado até o valor escolhido, resto em cinza-arroxeado
        pos = (var + 30.0) / 40.0 * 100
        st.markdown(
            f"<style>.st-key-sim_var_{gtin} div[style*='linear-gradient'] {{ background: linear-gradient(to right, "
            f"#d9b869 0%, #d9b869 {pos:.2f}%, rgba(255,255,255,.16) {pos:.2f}%, rgba(255,255,255,.16) 100%) !important; }}"
            f".st-key-sim_var_{gtin} [role='slider'] {{ background-color: #d9b869 !important; box-shadow: none !important; }}"
            f".st-key-sim_var_{gtin} [data-testid='stSliderThumbValue'] {{ color: #d9b869 !important; }}</style>",
            unsafe_allow_html=True,
        )

    c1, c2, c3 = st.columns(3, gap="large")
    modo = c1.radio("Informar o custo como", ["Custo unitário (R$)", "Margem atual (%)"], horizontal=True, key=f"sim_modo_{gtin}")
    if modo.startswith("Custo"):
        custo = c1.number_input("Custo unitário (R$)", min_value=0.0, value=None, step=0.5, format="%.2f", key=f"sim_custo_{gtin}")
    else:
        m = c1.number_input("Margem atual (%)", min_value=0.0, max_value=99.9, value=None, step=1.0, format="%.1f", key=f"sim_marg_{gtin}")
        custo = None if m is None else preco * (1 - m / 100)
    unidades = c2.number_input("Unidades vendidas por mês", min_value=0.0, value=float(unid_padrao or 0), step=1.0,
                               format="%.0f", key=f"sim_unid_{gtin}",
                               help=f"Preenchido com as vendas da Farmazids em {mes_ref}." if mes_ref and unid_padrao else
                                    "Não encontrei vendas deste produto no histórico: informe o volume mensal.")
    ganho = c3.number_input("Aumento esperado nas vendas (%)", min_value=-100.0, max_value=500.0, value=0.0, step=5.0,
                            format="%.0f", key=f"sim_ganho_{gtin}", help="Efeito do novo preço sobre o volume. 0% = vende o mesmo.")

    r = simular(preco, var, conc, custo, unidades, ganho)

    # --- posição no mercado ---
    st.markdown(f'<h2 class="g-section" style="font-size:var(--text-heading);margin-top:var(--spacing-24)">{esc(nome)}</h2>',
                unsafe_allow_html=True)
    ant, dep = st.columns(2, gap="medium")
    ant.markdown('<div class="g-label">Hoje</div>', unsafe_allow_html=True)
    ant.markdown(card_produto(nome, {"Farmazids": preco, **conc}), unsafe_allow_html=True)
    dep.markdown(f'<div class="g-label">Com o novo preço ({_pct_sinal(var)})</div>', unsafe_allow_html=True)
    dep.markdown(card_produto(nome, {"Farmazids": r["novo"], **conc}), unsafe_allow_html=True)

    suf = lambda emp: " (empate)" if emp else ""
    dif = r["novo"] - r["menor_conc"]
    dif_txt = (f"{_rs(abs(dif))} {'abaixo' if dif < -0.005 else 'acima'} do concorrente mais barato"
               if abs(dif) >= 0.005 else "igual ao concorrente mais barato")
    cards = [
        _card_sim("Posição no mercado", f'{r["pos_novo"]}º de {r["total"]}{suf(r["empate_novo"])}',
                  f'hoje: {r["pos_hoje"]}º de {r["total"]}{suf(r["empate_hoje"])}', nossa=True),
        _card_sim("Novo preço", _rs(r["novo"]), f'hoje {_rs(preco)} · {_rs(r["novo"] - preco)} por unidade'.replace("R$ -", "−R$ ")),
        _card_sim("Frente ao mais barato", _rs(r["menor_conc"]), dif_txt),
    ]
    st.markdown('<div class="g-sim-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)

    igualar = [f"{esc(f)} ({_rs(conc[f])}): {_pct_sinal(v)}" for f, v in sorted(r["igualar"].items(), key=lambda kv: kv[1], reverse=True)]
    st.markdown(f'<p class="g-sim-nota">Variação necessária para igualar o preço de cada concorrente: {" · ".join(igualar)}.</p>',
                unsafe_allow_html=True)
    indisp = [f for f in conc if f in precos.index and _indisponivel(precos.loc[f, "disponibilidade"]) and pd.notna(conc[f])]
    if indisp:
        st.markdown(f'<p class="g-sim-nota">Indisponível hoje: {", ".join(indisp)}. O preço aparece, mas o produto não pode ser comprado agora.</p>',
                    unsafe_allow_html=True)

    # --- margem ---
    st.markdown('<h2 class="g-section" style="font-size:var(--text-heading);margin-top:var(--spacing-24)">Quanto de margem se perde</h2>',
                unsafe_allow_html=True)
    if r["custo"] is None:
        st.info("Informe o custo unitário (ou a margem atual) para calcular a margem e o lucro mensal.")
    else:
        m_novo_pct = fmt_valor(r["m_novo_pct"], "pct") if r["m_novo_pct"] is not None else "—"
        cls = "perde" if r["perda_un"] > 0.005 else ("ganha" if r["perda_un"] < -0.005 else "")
        cards = [
            _card_sim("Margem por unidade", _rs(r["m_novo_un"]), f'hoje {_rs(r["m_atual_un"])}'),
            _card_sim("Margem (%)", m_novo_pct, f'hoje {fmt_valor(r["m_atual_pct"], "pct")}'),
            _card_sim("Margem perdida por unidade", _rs(max(r["perda_un"], 0)) if r["perda_un"] >= 0 else f'+{_rs(-r["perda_un"])}',
                      f'{_pct_sinal(-(r["perda_un"] / r["m_atual_un"] * 100)) if r["m_atual_un"] > 0 else "—"} da margem de hoje', cls),
        ]
        if unidades > 0:
            cards.append(_card_sim("Lucro mensal", _rs(r["lucro_novo"]),
                                   f'hoje {_rs(r["lucro_atual"])} · {"+" if r["delta"] > 0 else ""}{_rs(r["delta"])} por mês'.replace("R$ -", "−R$ "),
                                   "perde" if r["delta"] < -0.005 else ("ganha" if r["delta"] > 0.005 else "")))
        st.markdown('<div class="g-sim-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)
        if r["m_novo_un"] <= 0:
            st.warning("Com esse preço a Farmazids venderia abaixo do custo.")
        elif r["equilibrio"] is not None and r["perda_un"] > 0.005 and unidades > 0:
            st.markdown(f'<p class="g-sim-nota">Para manter o lucro mensal de hoje, as vendas precisariam crescer {fmt_valor(r["equilibrio"], "pct")}.</p>',
                        unsafe_allow_html=True)
    coleta = ", ".join(f"{f}: {precos.loc[f, 'coleta']}" for f in precos.index if pd.notna(precos.loc[f, "coleta"]))
    st.markdown('<p class="g-sim-nota">Preço dos concorrentes: o menor entre o preço sem desconto e o pix, na coleta mais recente '
                f'({esc(coleta)}). Margem = (preço − custo) ÷ preço. Os preços dos concorrentes ficam como estão.</p>',
                unsafe_allow_html=True)
    if st.query_params.get("debug") == "1":
        with st.expander("Diagnóstico: SQL das consultas"):
            for sql in (sql_busca_produto(termo), sql_precos_produto(gtin), sql_unidades_mes(gtin)):
                st.code(sql, language="sql")


# Pré-carrega os insights em segundo plano assim que a pessoa entra (uma vez por sessão):
# quando ela abrir a aba Insights, as consultas já estão prontas ou quase.
if not st.session_state.get("insights_pre"):
    st.session_state.insights_pre = True
    iniciar_insights()

if st.session_state.page == "inicio":
    render_boas_vindas()
    st.stop()

if st.session_state.page == "insights":
    render_insights()
    st.stop()

# ---------- Página: Tendências (Google Trends x vendas) ----------
# O usuário escolhe um medicamento, o app busca a tendência de busca na hora (com cache de 7 dias),
# cruza com as vendas semanais e mostra se a busca costuma ANTECEDER as vendas.
# Não precisa de Lambda novo: o próprio Streamlit consulta o Trends e o Athena.


def limpar_termo(nome: str) -> str:
    """Sugere um termo de busca a partir do nome do produto (marca ou substância, sem dose nem quantidade)."""
    # Deixa em minúsculas para padronizar
    n = str(nome).lower()
    # Corta o nome no primeiro número (dosagem ou quantidade), ex.: "glifage xr 500mg" vira "glifage xr "
    n = re.split(r"\d", n)[0]
    # Tira palavras que só descrevem a forma do remédio
    n = re.sub(r"\b(comprimidos?|cápsulas?|capsulas?|gotas|xarope|solução|solucao|creme|gel)\b", " ", n)
    # Remove espaços repetidos
    return " ".join(n.split())


def sql_vendas_semana(gtin: str) -> str:
    """Unidades vendidas pela Farmazids por semana (segunda a domingo), na carga mais recente do histórico."""
    carga = '"$file_modified_time" = (SELECT MAX("$file_modified_time") FROM historico_farmazids)'
    return ("SELECT CAST(date_trunc('week', CAST(h.data_venda AS date)) AS date) AS semana, "
            "SUM(h.quantidade_vendida) AS unidades "
            f"FROM historico_farmazids h WHERE h.farmacia = 'farmazids' AND h.gtin = '{gtin}' AND h.{carga} "
            "GROUP BY 1 ORDER BY 1 LIMIT 300")


def preparar_vendas(bruto):
    """Resultado do Athena vira uma série semanal; semanas sem venda entram como zero."""
    if bruto is None or bruto.shape[1] < 2:
        return None
    d = bruto.iloc[:, :2].copy()
    d.columns = ["semana", "unidades"]
    d["semana"] = pd.to_datetime(d["semana"], errors="coerce")
    d["unidades"] = pd.to_numeric(d["unidades"], errors="coerce")
    d = d.dropna()
    if d.empty:
        return None
    serie = d.set_index("semana")["unidades"]
    # Cria todas as semanas do período e preenche com 0 as que não tiveram venda
    todas = pd.date_range(serie.index.min(), serie.index.max(), freq="7D")
    return serie.reindex(todas, fill_value=0.0)


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def buscar_trends(termo: str) -> pd.Series:
    """Índice semanal (0 a 100) de busca no Brasil nos últimos 5 anos. Guardado por 7 dias por termo.
    Se falhar, levanta RuntimeError. Erros não entram no cache, então a próxima tentativa busca de novo."""
    try:
        from pytrends.request import TrendReq  # importado aqui para o app abrir mesmo sem a biblioteca
    except ImportError as exc:
        raise RuntimeError("A biblioteca pytrends não está instalada. Rode: py -m pip install pytrends") from exc

    ultimo_erro = None
    for tentativa in range(3):  # até 3 tentativas, esperando um pouco mais a cada falha
        try:
            pt = TrendReq(hl="pt-BR", tz=180, timeout=(10, 25))
            pt.build_payload([termo], timeframe="today 5-y", geo="BR")
            df = pt.interest_over_time()
            if df.empty or termo not in df.columns:
                raise ValueError("sem volume de busca suficiente para esse termo")
            if "isPartial" in df.columns:
                df = df[~df["isPartial"].astype(bool)]  # descarta a semana ainda incompleta
            serie = df[termo].astype(float)
            # O Trends marca a semana pelo DOMINGO e o Athena pela SEGUNDA: somamos 1 dia para alinhar
            serie.index = serie.index + pd.Timedelta(days=1)
            return serie
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            time.sleep(2 * (tentativa + 1))
    raise RuntimeError(f"Não consegui obter a tendência no Google Trends ({ultimo_erro}). Tente de novo em alguns minutos.")


def _busca_atrasada(trends: pd.Series, k: int) -> pd.Series:
    """Desloca a busca k semanas para frente: o valor de hoje passa a 'valer' para a semana de hoje + k."""
    t = trends.copy()
    t.index = t.index + pd.Timedelta(weeks=k)
    return t


def cruzar(vendas: pd.Series, trends: pd.Series, max_lag: int = 8) -> pd.DataFrame:
    """Correlação entre as vendas de uma semana e a busca de k semanas antes, para k de 0 a max_lag."""
    linhas = []
    for k in range(max_lag + 1):
        junto = pd.concat([vendas, _busca_atrasada(trends, k)], axis=1, join="inner").dropna()
        junto.columns = ["vendas", "busca"]
        # Exige pelo menos 12 semanas em comum e alguma variação nas duas séries
        if len(junto) >= 12 and junto["vendas"].std() > 0 and junto["busca"].std() > 0:
            linhas.append({"atraso": k, "correlacao": junto["vendas"].corr(junto["busca"]), "semanas": len(junto)})
    return pd.DataFrame(linhas)


def projetar(vendas: pd.Series, trends: pd.Series, k: int) -> pd.Series:
    """Reta vendas = a + b * busca(k semanas antes), aplicada às semanas depois da última venda conhecida."""
    import numpy as np

    busca_k = _busca_atrasada(trends, k)
    junto = pd.concat([vendas, busca_k], axis=1, join="inner").dropna()
    junto.columns = ["vendas", "busca"]
    b, a = np.polyfit(junto["busca"], junto["vendas"], 1)  # b é a inclinação e a é o ponto de partida
    futuro = busca_k[busca_k.index > vendas.index.max()]  # semanas ainda sem venda, mas com busca conhecida
    return (a + b * futuro).clip(lower=0)


def render_tendencias():
    st.markdown(CSS_DESTAQUES + CSS_BV + SIM_CSS + (SIM_CSS_ESCURO if DARK else ""), unsafe_allow_html=True)
    st.markdown(
        '<span class="g-tag">Tendências</span>'
        '<h1 class="g-title" style="font-size:clamp(36px,5vw,56px)">Busca x vendas</h1>'
        '<p class="g-sub">Veja se as buscas no Google costumam subir antes das vendas de um medicamento, '
        'para antecipar a demanda.</p>',
        unsafe_allow_html=True,
    )
    termo_busca = st.text_input("Buscar medicamento", key="tr_busca", placeholder="Ex.: dipirona, glifage, losartana")
    if len(_termo_busca(termo_busca).replace("%", "")) < 2:
        st.info("Digite ao menos 2 letras do nome do medicamento para começar.")
        return
    try:
        with carregando("Buscando o medicamento..."):
            achados = rows_to_df(run_bv(sql_busca_produto(termo_busca)).get("rows") or [])
    except RuntimeError as exc:
        st.warning(f"Não consegui buscar o medicamento agora: {exc}")
        return
    if achados is None or achados.empty:
        st.info("Nenhum medicamento do catálogo da Farmazids encontrado com esse nome.")
        return
    nomes = dict(zip(achados["gtin"], achados["nome"]))
    gtin = st.selectbox("Produto", list(nomes), format_func=lambda g: nomes[g], key=f"tr_prod_{_termo_busca(termo_busca)}")
    if not re.fullmatch(r"\d{6,14}", str(gtin)):
        st.warning("Este produto não tem um GTIN válido.")
        return
    # O termo é sugerido pelo nome, mas a pessoa pode trocar (ex.: de "glifage" para "metformina")
    termo = st.text_input("Termo pesquisado no Google", value=limpar_termo(nomes[gtin]), key=f"tr_termo_{gtin}",
                          help="Troque pela marca ou substância que as pessoas realmente digitam.").strip()
    if len(termo) < 2:
        return

    # --- vendas semanais (Athena) ---
    try:
        with carregando("Consultando as vendas..."):
            vendas = preparar_vendas(rows_to_df(run_bv(sql_vendas_semana(gtin)).get("rows") or []))
    except RuntimeError as exc:
        st.warning(f"Não consegui consultar as vendas agora: {exc}")
        return
    if vendas is None or len(vendas) < 12:
        st.info("Há poucas semanas de venda deste produto para cruzar com as buscas (mínimo de 12 semanas).")
        return

    # --- tendência de busca (Google Trends, com cache de 7 dias) ---
    try:
        with carregando("Buscando no Google Trends..."):
            trends = buscar_trends(termo)
    except RuntimeError as exc:
        st.warning(str(exc))
        return

    # --- cruzamento: em qual atraso a busca melhor acompanha as vendas ---
    cruz = cruzar(vendas, trends)
    if cruz.empty:
        st.info("Não há semanas em comum suficientes entre as vendas e as buscas para cruzar.")
        return
    melhor = cruz.loc[cruz["correlacao"].idxmax()]
    k, corr, semanas = int(melhor["atraso"]), float(melhor["correlacao"]), int(melhor["semanas"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Atraso com maior correlação", f"{k} semanas" if k else "sem atraso")
    c2.metric("Correlação", f"{corr:.2f}".replace(".", ","))
    c3.metric("Semanas comparadas", semanas)
    if corr < 0.4:
        st.info("A busca no Google não acompanha as vendas deste produto de forma clara. Tente outro termo.")
    elif k >= 1:
        st.success(f"A busca costuma subir cerca de {k} semanas antes das vendas. Isso permite antecipar a demanda.")
    else:
        st.info("A busca e as vendas andam juntas, sem antecedência. Ajuda a entender, mas não a antecipar.")
    if semanas < 26:
        st.warning(f"Só há {semanas} semanas de histórico em comum. Com tão pouco tempo, a correlação pode ser coincidência.")

    # --- projeção das próximas semanas (só quando há relação razoável) ---
    prev = projetar(vendas, trends, k) if corr >= 0.4 else None

    # --- gráfico: as duas séries na mesma escala de 0 a 100 ---
    pico = float(vendas.max()) or 1.0
    partes = [
        pd.DataFrame({"data": vendas.index, "indice": (vendas / pico * 100).values, "serie": "Vendas", "tipo": "observado"}),
        pd.DataFrame({"data": trends.index, "indice": trends.values, "serie": "Busca no Google", "tipo": "observado"}),
    ]
    if prev is not None and not prev.empty:
        partes.append(pd.DataFrame({"data": prev.index, "indice": (prev / pico * 100).values,
                                    "serie": "Vendas", "tipo": "previsto"}))
    dados = pd.concat(partes)
    dados = dados[dados["data"] >= vendas.index.min() - pd.Timedelta(weeks=4)]  # foca no período com vendas
    graf = alt.Chart(dados).mark_line(strokeWidth=2.5).encode(
        x=alt.X("data:T", title=None, axis=alt.Axis(format="%m/%Y", labelAngle=0)),
        y=alt.Y("indice:Q", title="Índice (0 a 100)"),
        color=alt.Color("serie:N", title=None, scale=alt.Scale(domain=["Vendas", "Busca no Google"], range=[PURPLE, GOLD]),
                        legend=alt.Legend(orient="bottom")),
        strokeDash=alt.StrokeDash("tipo:N", legend=None,
                                  scale=alt.Scale(domain=["observado", "previsto"], range=[[1, 0], [5, 4]])),
        tooltip=[alt.Tooltip("data:T", title="Semana", format="%d/%m/%Y"), alt.Tooltip("serie:N", title="Série"),
                 alt.Tooltip("tipo:N", title="Tipo"), alt.Tooltip("indice:Q", title="Índice", format=".0f")],
    ).properties(height=340)
    if DARK:
        graf = graf.configure_axis(labelColor=MUTED, titleColor=MUTED, gridColor=GRID).configure_legend(
            labelColor=INK).properties(background="rgba(0,0,0,0)")
    with st.container(border=True):
        st.markdown('<div class="g-label">Vendas e buscas, cada uma na própria escala (0 a 100)</div>', unsafe_allow_html=True)
        st.altair_chart(graf, use_container_width=True, theme=None if DARK else "streamlit")

    if prev is not None and not prev.empty:
        st.markdown('<div class="g-label">Projeção de vendas (unidades por semana)</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Semana": prev.index.strftime("%d/%m/%Y"), "Unidades previstas": prev.round(0).astype(int).values}),
                     use_container_width=True, hide_index=True)
    st.caption("A projeção é uma indicação baseada em uma reta simples entre busca e vendas, não uma previsão firme. "
               "A tendência fica guardada por 7 dias por termo.")
    if st.button("Atualizar tendência deste termo", key=f"tr_refresh_{gtin}"):
        buscar_trends.clear()
        st.rerun()


if st.session_state.page == "tendencias":
    render_tendencias()
    st.stop()


if st.session_state.page == "simulador":
    render_simulador()
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
    st.markdown(CSS_DESTAQUES, unsafe_allow_html=True)
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
    serie = d.sort_values("data").tail(14)  # últimos pontos, em ordem cronológica (para as sparklines)
    ref = "variação do último mês vs. o anterior" if tipo == "vendas" else "variação da última coleta vs. a anterior"
    ult, ini = d.iloc[0], d.iloc[-1]
    f_ult, f_ini = ult["data"].strftime(ordem_fmt), ini["data"].strftime(ordem_fmt)
    k = len(d)

    if tipo == "vendas":
        frase = (f"Há <b>{n(total)}</b> vendas registradas em <b>{k}</b> meses, de {f_ini} a {f_ult}. "
                 f"No mês mais recente ({f_ult}) foram vendidos <b>{n(ult['produtos'])}</b> produtos diferentes "
                 f"em <b>{n(ult['farmacias'])}</b> farmácias.")
        cartoes = [("Vendas registradas", n(total), f"em {k} meses", serie["vendas"].tolist()),
                   ("Produtos vendidos", n(ult["produtos"]), f"no mês {f_ult}", serie["produtos"].tolist()),
                   ("Farmácias", n(ult["farmacias"]), f"no mês {f_ult}", serie["farmacias"].tolist()),
                   ("Último mês", f_ult, "com vendas")]
    else:
        cat = f" em <b>{n(ult['categorias'])}</b> categorias" if tipo == "coletas" else ""
        frase = (f"Na <b>{origem}</b> há <b>{n(ult['produtos'])}</b> medicamentos extraídos{cat} na coleta mais "
                 f"recente ({f_ult}). Foram feitas <b>{k}</b> coletas, de {f_ini} a {f_ult}.")
        cartoes = [("Medicamentos", n(ult["produtos"]), "na última coleta", serie["produtos"].tolist())]
        if tipo == "coletas":
            cartoes.append(("Categorias", n(ult["categorias"]), "na última coleta", serie["categorias"].tolist()))
        cartoes += [("Coletas feitas", n(k), f"de {f_ini} a {f_ult}"), ("Última coleta", f_ult, "dado mais recente")]

    html = "".join(card_stat(a, b, c, s[0] if s else None, ref) for a, b, c, *s in cartoes)
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
        limpar_insights()
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


# ---------- Vários chats: cada conversa tem o próprio histórico e, por isso, o próprio contexto ----------
# O Zids só recebe as últimas trocas do chat ATIVO (montar_historico), então trocar de chat troca o contexto.
TITULO_PADRAO = "Novo chat"


def _criar_chat() -> str:
    cid = uuid.uuid4().hex[:8]
    st.session_state.chats[cid] = {"titulo": TITULO_PADRAO, "messages": [], "atualizado": time.time()}
    st.session_state.chat_ativo = cid
    return cid


def _titulo_do_chat(pergunta: str, limite: int = 36) -> str:
    t = " ".join(pergunta.split())
    return t if len(t) <= limite else t[:limite].rstrip() + "…"


def _rotulo_botao(texto: str) -> str:
    """Escapa caracteres de markdown (e o $, lido como fórmula) no título que vira rótulo de botão."""
    for ch in ("\\", "$", "*", "_", "`"):
        texto = texto.replace(ch, "\\" + ch)
    return texto


if not st.session_state.get("chats"):
    st.session_state.chats = {}
    _criar_chat()
elif st.session_state.get("chat_ativo") not in st.session_state.chats:
    st.session_state.chat_ativo = max(st.session_state.chats, key=lambda c: st.session_state.chats[c]["atualizado"])

if "sidebar_aberta" not in st.session_state:
    st.session_state.sidebar_aberta = True

if st.session_state.sidebar_aberta:
    with st.sidebar:
        # Força a barra a aparecer, mesmo que o Streamlit a tenha deixado recolhida no navegador (estado nativo)
        st.markdown(
            """<style>
[data-testid="stSidebar"] { display: block !important; visibility: visible !important; transform: none !important;
  margin-left: 0 !important; width: min(21rem, 85vw) !important; min-width: min(21rem, 85vw) !important; }
[data-testid="stSidebarContent"], [data-testid="stSidebarUserContent"] { visibility: visible !important; opacity: 1 !important; }
</style>""",
            unsafe_allow_html=True,
        )
        topo, fechar = st.columns([0.8, 0.2], vertical_alignment="center", gap="small")
        topo.markdown('<div class="g-label">Conversas</div>', unsafe_allow_html=True)
        if fechar.button("«", key="fechar_chats", help="Recolher a barra de chats"):
            st.session_state.sidebar_aberta = False
            st.rerun()
        if st.button("＋ Novo chat", key="novo_chat", type="primary", use_container_width=True):
            if st.session_state.chats[st.session_state.chat_ativo]["messages"]:  # já está num chat vazio? então fica nele
                _criar_chat()
            st.rerun()
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        for cid, c in sorted(st.session_state.chats.items(), key=lambda kv: kv[1]["atualizado"], reverse=True):
            ativo = cid == st.session_state.chat_ativo
            col_t, col_x = st.columns([0.85, 0.15], vertical_alignment="center", gap="small")
            if col_t.button(_rotulo_botao(c["titulo"]), key=f"chatsel{'_on' if ativo else ''}_{cid}", use_container_width=True):
                st.session_state.chat_ativo = cid
                st.rerun()
            if col_x.button("✕", key=f"chatdel_{cid}", help="Excluir este chat"):
                del st.session_state.chats[cid]
                if not st.session_state.chats:
                    _criar_chat()
                st.rerun()
else:
    st.markdown('<style>[data-testid="stSidebar"] { display: none !important; }</style>', unsafe_allow_html=True)
    if st.button("☰", key="abrir_chats", help="Abrir a barra de chats"):
        st.session_state.sidebar_aberta = True
        st.rerun()

# ---------- Perguntar por voz: gravação no navegador + Amazon Transcribe Streaming ----------
# O áudio é transcrito AQUI, no app; a state machine continua recebendo só texto ({"pergunta", "historico"}).
# O texto transcrito aparece numa caixa editável e só vai ao chatbot quando a pessoa clica em "Enviar pergunta".
TRANSCRIBE_REGION = os.environ.get("TRANSCRIBE_REGION", AWS_REGION)
VOZ_CSS_ESCURO = """
<style>
[data-testid="stTextArea"] [data-baseweb="textarea"], [data-testid="stTextArea"] [data-baseweb="base-input"] {
  background-color: #2a2236 !important; border: 1px solid rgba(255,255,255,.14) !important; }
[data-testid="stTextArea"] textarea { background-color: transparent !important; color: #e6e1f0 !important; -webkit-text-fill-color: #e6e1f0 !important; }
</style>
"""


class _ColetorTranscricao(TranscriptResultStreamHandler):
    """Junta os trechos finais (não parciais) devolvidos pelo Transcribe."""

    def __init__(self, stream):
        super().__init__(stream)
        self.partes: list = []

    async def handle_transcript_event(self, event):
        for resultado in event.transcript.results:
            if not resultado.is_partial and resultado.alternatives:
                self.partes.append(resultado.alternatives[0].transcript)


def _wav_para_pcm(wav: bytes) -> tuple:
    """WAV do st.audio_input → (PCM 16 bits mono, taxa em Hz)."""
    with wave.open(io.BytesIO(wav), "rb") as w:
        canais, largura, taxa = w.getnchannels(), w.getsampwidth(), w.getframerate()
        pcm = w.readframes(w.getnframes())
    if largura != 2:
        raise ValueError("formato de áudio não suportado (esperado PCM de 16 bits)")
    if canais > 1:  # fica só com o primeiro canal
        amostras = array("h")
        amostras.frombytes(pcm)
        pcm = amostras[::canais].tobytes()
    return pcm, taxa


async def _transcrever_async(pcm: bytes, taxa: int) -> str:
    cliente = TranscribeStreamingClient(region=TRANSCRIBE_REGION)
    stream = await cliente.start_stream_transcription(language_code="pt-BR", media_sample_rate_hz=taxa, media_encoding="pcm")
    coletor = _ColetorTranscricao(stream.output_stream)

    async def enviar():
        passo = int(taxa * 2 * 0.2)  # blocos de 200 ms
        for i in range(0, len(pcm), passo):
            await stream.input_stream.send_audio_event(audio_chunk=pcm[i:i + passo])
        await stream.input_stream.end_stream()

    await asyncio.gather(enviar(), coletor.handle_events())
    return " ".join(coletor.partes).strip()


def transcrever_audio(wav: bytes) -> str:
    """Transcreve (pt-BR) o áudio gravado. Levanta exceção com mensagem legível se não for possível."""
    if TranscribeStreamingClient is None:
        raise RuntimeError("falta instalar a biblioteca amazon-transcribe")
    pcm, taxa = _wav_para_pcm(wav)
    return asyncio.run(_transcrever_async(pcm, taxa))


def render_voz():
    """Gravador + texto transcrito para conferir. Devolve a pergunta quando a pessoa clica em Enviar."""
    if not hasattr(st, "audio_input"):  # versões antigas do Streamlit
        return None
    if DARK:
        st.markdown(VOZ_CSS_ESCURO, unsafe_allow_html=True)
    n = st.session_state.get("voz_n", 0)
    with st.expander("Perguntar por voz"):
        audio = st.audio_input("Grave a pergunta; ao parar, ela é transcrita", key=f"voz_audio_{n}", sample_rate=16000)
        if audio is None:
            return None
        dados = audio.getvalue()
        h = hashlib.sha1(dados).hexdigest()
        if st.session_state.get("voz_hash") != h:  # áudio novo: transcreve uma única vez
            st.session_state.voz_hash = h
            try:
                with carregando("Transcrevendo o áudio..."):
                    texto = transcrever_audio(dados)
                erro = "" if texto else "Não entendi o áudio. Grave de novo, mais perto do microfone."
            except Exception as exc:  # noqa: BLE001 - qualquer falha vira um aviso, nunca derruba o chat
                texto, erro = "", f"Não consegui transcrever o áudio: {exc}"
            st.session_state.voz_erro = erro
            st.session_state[f"voz_texto_{n}"] = texto
        if st.session_state.get("voz_erro"):
            st.warning(st.session_state.voz_erro)
            return None
        texto = st.text_area("Confira a pergunta antes de enviar (você pode corrigir o texto)", key=f"voz_texto_{n}", height=90)
        c1, c2, _ = st.columns([1.3, 1, 3])
        enviar = c1.button("Enviar pergunta", key=f"voz_env_{n}", type="primary", disabled=not texto.strip(), use_container_width=True)
        descartar = c2.button("Descartar", key=f"voz_desc_{n}", use_container_width=True)
    if enviar or descartar:
        st.session_state.voz_n = n + 1  # troca a chave: o gravador volta vazio
        st.session_state.pop("voz_hash", None)
        st.session_state.pop("voz_erro", None)
        if descartar:
            st.rerun()
        return texto.strip()
    return None


chat = st.session_state.chats[st.session_state.chat_ativo]
mensagens = chat["messages"]

clicked = None
if not mensagens:
    for i, text in enumerate(SUGGESTIONS):
        if st.button(text, key=f"sug_{i}"):
            clicked = text

for i_msg, m in enumerate(mensagens):
    with st.chat_message(m["role"]):
        render_message(m, uid=f"{st.session_state.chat_ativo}_{i_msg}")

voz_box = st.empty()
with voz_box.container():
    voz = render_voz()
prompt = st.chat_input("Escreva sua pergunta") or clicked or voz
if voz:
    voz_box.empty()  # esconde o gravador enquanto a pergunta é processada
if prompt:
    historico = montar_historico(mensagens)  # só as últimas trocas DESTE chat
    mensagens.append({"role": "user", "content": prompt})
    if chat["titulo"] == TITULO_PADRAO:
        chat["titulo"] = _titulo_do_chat(prompt)
    with st.chat_message("user"):
        st.markdown(md_seguro(prompt))
    with st.chat_message("assistant"):
        with carregando("Consultando os dados..."):
            reply = generate_reply(prompt, historico)
            reply["chart"] = wants_chart(prompt)
            reply["pergunta"] = prompt
        render_message(reply, uid=f"{st.session_state.chat_ativo}_{len(mensagens)}")
    mensagens.append({"role": "assistant", **reply})
    chat["atualizado"] = time.time()
    st.rerun()  # atualiza a barra lateral (título novo e chat mais recente no topo)
