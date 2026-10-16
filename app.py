import base64
import json
import os
import time
import uuid
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
BANNER = "Novo: pergunte ao Zids sobre preços e vendas"
BUBBLES = ["Olá, eu sou o Zids.", "O que você quer saber sobre preços?"]
# Substitua pelos seus números reais
STATS = [
    ("Medicamentos", "10.000+", "no banco de dados"),
    ("Tempo de resposta", "2 s", "em média por pergunta"),
    ("Satisfação", "90%", "das conversas avaliadas"),
]
SUGGESTIONS = [
    "Qual o preço médio da dipirona na FarmaPonte?",
    "Onde a dipirona está mais barata entre os concorrentes?",
    "Quais os 5 medicamentos mais vendidos neste mês?",
]

st.set_page_config(page_title=f"{BOT_NAME}", page_icon="💜", layout="wide")

# ---------- Estilo (tokens do Grove AI) ----------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono&family=Libre+Caslon+Text&display=swap');

:root {
  /* Colors (o verde Forest Grove do guia foi trocado por roxo) */
  --color-brand: #6d3fc0;
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
  --surface-canvas: #ffffff;
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
.block-container { max-width: var(--page-max-width); padding: 0 var(--spacing-24) 8rem; }

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
.g-logo { font-size: var(--text-subheading); font-weight: var(--font-weight-semibold); letter-spacing: var(--tracking-subheading); }
.g-logo b { color: var(--color-brand); }

.g-logo-img { height: 88px; width: auto; display: block; margin-bottom: var(--spacing-24); }

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



stats = "".join(
    f'<div class="g-stat"><div class="g-label">{l}</div><div class="g-num">{n}</div><div class="g-cap">{c}</div></div>'
    for l, n, c in STATS
)
bubbles = f'<div class="g-b1">{BUBBLES[0]}</div><div class="g-b2">{BUBBLES[1]}</div>'

html = (
    f'<div class="g-banner">{BANNER}</div>'
    f'<div class="g-nav"><div class="g-logo"><b>●</b> {BOT_NAME}</div>'
    '</div>'
    f'<div class="g-hero"><div>{load_logo()}<span class="g-tag">{TAG}</span>'
    f'<h1 class="g-title">Conheça o <em>{BOT_NAME}</em></h1><p class="g-sub">{SUBHEAD}</p>'
    f'<div class="g-cta"><a class="g-btn fill" href="#conversar">Começar a conversar</a>'
    f'<a class="g-btn" href="#resultados">Ver resultados</a></div></div>'
    f'<div class="g-mock"><div class="ph"><img src="app/static/ZIDS.gif" alt="{BOT_NAME}"></div>{bubbles}</div></div>'
    f'<div id="resultados" class="g-stats">{stats}</div>'
    f'<div id="conversar"><h2 class="g-section">Converse com o {BOT_NAME}</h2>'
    f'<p class="g-cap" style="margin-bottom:24px">Escolha uma pergunta ou escreva a sua.</p></div>'
)
st.markdown(html, unsafe_allow_html=True)


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


def generate_reply(pergunta: str) -> dict:
    # O primeiro estado da state machine (Iniciar) lê somente $.pergunta
    payload = {"pergunta": pergunta}
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


PURPLE = "#6d3fc0"
PALETTE = ["#6d3fc0", "#1c1c1e", "#a98ee0", "#676768", "#c7b5ec", "#303033"]
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


def render_message(m: dict):
    st.markdown(m["content"])
    df = rows_to_df(m.get("rows") or []) if m.get("sql") else None
    if m.get("chart"):
        chart = build_chart(df, m.get("pergunta", "")) if df is not None else None
        if chart is not None:
            st.altair_chart(chart.properties(height=320), use_container_width=True)
        else:
            st.info("Não há dados numéricos suficientes para montar um gráfico com essa pergunta.")
    if m.get("sql"):
        with st.expander("Ver consulta e dados"):
            st.code(m["sql"], language="sql")
            if df is not None:
                st.dataframe(df, use_container_width=True, hide_index=True)


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
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Consultando os dados..."):
            reply = generate_reply(prompt)
            reply["chart"] = wants_chart(prompt)
            reply["pergunta"] = prompt
        render_message(reply)
    st.session_state.messages.append({"role": "assistant", **reply})
    if clicked:
        st.rerun()
