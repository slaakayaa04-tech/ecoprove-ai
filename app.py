"""EcoProve AI - Streamlit web app.

Reads the reliability score file, rebuilds the monthly Merkle trees
(same scheme as merkle_kok.py) and verifies records against the
EcoProveRegistry smart contract on Ethereum Sepolia (read-only, no wallet).

Run:  streamlit run app.py
"""
import base64
import html
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from Crypto.Hash import keccak
from web3 import Web3

# ---------------------------------------------------------------- settings
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = str(BASE_DIR / "data" / "reliability_scores_v1.csv")
BG_IMAGE_PATH = BASE_DIR / "assets" / "climatechain_bg.png"
CONTRACT = "0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89"
RPC_URL = "https://ethereum-sepolia-rpc.publicnode.com"
ETHERSCAN_ADDR = f"https://sepolia.etherscan.io/address/{CONTRACT}"
CITY_LABELS = ["TEST", "Ankara"]  # TEST = trial roots, Ankara = final roots

EMERALD, CYAN, CORAL = "#10b981", "#06b6d4", "#f43f5e"
AMBER, CRIMSON, SLATE = "#f59e0b", "#ef4444", "#94a3b8"
SOURCE_COLORS = [EMERALD, CYAN, CORAL, AMBER, "#a78bfa"]
STATUS_COLORS = {"OK": EMERALD, "Review": AMBER, "Quarantine": CRIMSON, "No_Reference": SLATE}

# Plain-language explanations (used in tooltips)
TIP = {
    "records": "How many daily values we have for this month. One value per source per day.",
    "score": "Reliability Score (0–100). Close to 100 = the data sources agree and the value "
             "changes in a normal way over time (high confidence). Lower numbers = the sources "
             "disagree or the value jumps unusually.",
    "ok": "OK: the sources agree and the value looks normal. Safe to use.",
    "review": "Review: some disagreement or an unusual change. A person should check it "
              "before using it.",
    "quarantine": "Quarantine: strong disagreement or a clear anomaly. The value is flagged "
                  "and should not be used for decisions until it is checked.",
    "seal": "On-chain seal: every month, all records are turned into one short digital "
            "fingerprint (a Merkle root) and stored on the blockchain, where it cannot be "
            "overwritten. If anyone changes even one number later, the fingerprint no longer "
            "matches, so the change is detected.",
    "city": "TEST = trial fingerprints we stored while building the system. "
            "Ankara = final fingerprints of the real data.",
}

ABI = [
    {"name": "getRoot", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "city", "type": "string"}, {"name": "period", "type": "string"}],
     "outputs": [{"name": "root", "type": "bytes32"}, {"name": "count", "type": "uint32"},
                 {"name": "timestamp", "type": "uint64"}]},
    {"name": "verify", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "city", "type": "string"}, {"name": "period", "type": "string"},
                {"name": "leaf", "type": "bytes32"}, {"name": "proof", "type": "bytes32[]"}],
     "outputs": [{"name": "", "type": "bool"}]},
]


# ---------------------------------------------- Merkle (same as merkle_kok.py)
def k(b):
    return keccak.new(digest_bits=256, data=b).digest()


def leaf_from_values(date, source, tmean, score, status):
    return k(f"{date}|{source}|{tmean}|{score}|{status}".encode())


def yaprak(r):
    return leaf_from_values(r.date, r.source, r.tmean, r.score, r.status)


def katman(L):
    s = []
    for i in range(0, len(L), 2):
        if i + 1 == len(L):
            s.append(L[i])                                          # odd node goes up
        else:
            s.append(k(min(L[i], L[i + 1]) + max(L[i], L[i + 1])))  # sorted pair
    return s


def kok(L):
    while len(L) > 1:
        L = katman(L)
    return L[0]


def kanit(L, idx):
    p = []
    while len(L) > 1:
        e = idx ^ 1
        if e < len(L):
            p.append(L[e])
        L = katman(L)
        idx //= 2
    return p


def hx(b):
    return "0x" + b.hex()


# ------------------------------------------------------------------- data
@st.cache_data
def load_data():
    d = pd.read_csv(CSV_PATH, keep_default_na=False)
    d = d.sort_values(["date", "source"]).reset_index(drop=True)
    d["ay"] = d.date.str[:7]
    return d


@st.cache_data
def month_leaves(ay):
    d = load_data()
    return [yaprak(r) for r in d[d.ay == ay].itertuples()]


def numeric(df, cols):
    out = df.copy()
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


# -------------------------------------------------------------- blockchain
@st.cache_resource
def get_contract():
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 20}))
    return w3.eth.contract(address=Web3.to_checksum_address(CONTRACT), abi=ABI)


@st.cache_data(ttl=60, show_spinner=False)
def latest_block():
    try:
        return get_contract().w3.eth.block_number
    except Exception:
        return None


def chain_error_text(e):
    msg = str(e)
    if "not found" in msg:
        return "not_found"
    return f"Could not reach the Sepolia network. Please try again in a few seconds. ({msg[:150]})"


def read_root(city, period):
    root, count, ts = get_contract().functions.getRoot(city, period).call()
    return bytes(root), count, ts


def verify_on_chain(city, period, leaf, proof):
    return get_contract().functions.verify(city, period, leaf, proof).call()


@st.cache_data(ttl=120, show_spinner=False)
def chain_lookup(city, period):
    """Root info from the contract: state = found / not_found / error."""
    try:
        root, count, ts = read_root(city, period)
        return {"state": "found", "root": hx(root), "count": count, "ts": ts}
    except Exception as e:
        return {"state": "not_found" if "not found" in str(e) else "error"}


@st.cache_data
def all_local_roots():
    d = load_data()
    return {ay: (hx(kok(month_leaves(ay))), int((d.ay == ay).sum()))
            for ay in sorted(d.ay.unique())}


def threshold_eval(df, var, op, thr):
    """Per record: does the value cross the threshold? Per day: do the sources agree?"""
    d = numeric(df, [var])
    d = d[d[var].notna()].copy()
    d["crossed"] = d[var] < thr if op == "<" else d[var] >= thr
    days = d.groupby("date").agg(n=("crossed", "size"), yes=("crossed", "sum"),
                                 flagged=("status", lambda s: bool((s != "OK").any())))
    days["disagree"] = (days.n >= 2) & (days.yes > 0) & (days.yes < days.n)
    return d, days


# ------------------------------------------------------------------- styles
@st.cache_data
def get_bg_data_uri():
    if BG_IMAGE_PATH.exists():
        b64 = base64.b64encode(BG_IMAGE_PATH.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    return ""


def build_css():
    bg_uri = get_bg_data_uri()
    bg_img_layer = f", url('{bg_uri}')" if bg_uri else ""
    hero_img_layer = f", url('{bg_uri}')" if bg_uri else ""
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

html, body, .stApp, .stMarkdown, .stMarkdown p, .stMarkdown li, .stCaption,
h1, h2, h3, h4, h5, label, input, textarea, .stTabs button p, .stButton button p {{
    font-family: 'Plus Jakarta Sans', sans-serif !important;
}}

/* ---------- Soft Aurora + ClimateChain Circuit Background ---------- */
.stApp {{
    background-image:
        linear-gradient(rgba(167, 243, 208, 0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(167, 243, 208, 0.03) 1px, transparent 1px),
        radial-gradient(circle at 15% 20%, rgba(52, 211, 153, 0.22) 0%, transparent 55%),
        radial-gradient(circle at 85% 18%, rgba(45, 212, 191, 0.18) 0%, transparent 55%),
        radial-gradient(circle at 50% 75%, rgba(16, 185, 129, 0.16) 0%, transparent 60%),
        linear-gradient(160deg, rgba(7, 42, 34, 0.88) 0%, rgba(11, 61, 48, 0.84) 50%, rgba(8, 47, 43, 0.90) 100%){bg_img_layer} !important;
    background-size: 48px 48px, 48px 48px, auto, auto, auto, cover, cover !important;
    background-position: 0 0, 0 0, center, center, center, center, center !important;
    background-attachment: fixed !important;
}}
[data-testid="stAppViewContainer"], [data-testid="stMain"], .main {{background: transparent !important;}}
[data-testid="stHeader"] {{background: rgba(7, 42, 34, 0.45) !important; backdrop-filter: blur(10px);}}
.block-container, [data-testid="stMainBlockContainer"] {{padding-top: 1.5rem !important;}}

h3 {{font-weight: 700 !important; color: #f0fdf4 !important; letter-spacing: -0.01em;}}
p, li {{color: #dcfce7;}}
a {{color: #6ee7b7 !important;}}
.stCaption, [data-testid="stCaptionContainer"] {{color: #bbf7d0 !important; opacity: .88;}}

/* ---------- Soft Frosted Glass Base ---------- */
.glass, .card, .flow-step, .net, .hero,
[data-testid="stExpander"] details {{
    background: rgba(10, 46, 36, 0.62) !important;
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    border: 1px solid rgba(110, 231, 183, 0.22) !important;
    border-radius: 14px !important;
}}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {{
    background: rgba(7, 38, 30, 0.68) !important;
    backdrop-filter: blur(18px) !important; -webkit-backdrop-filter: blur(18px) !important;
    border-right: 1px solid rgba(110, 231, 183, 0.24) !important;
}}
[data-testid="stSidebarContent"] {{background: transparent !important;}}
.brand {{font-size: 1.35rem; font-weight: 800;
        background: linear-gradient(90deg, #f0fdf4, #86efac, #67e8f9);
        -webkit-background-clip: text; background-clip: text; color: transparent;}}
.brand-sub {{font-size: .82rem; color: #bbf7d0; margin-bottom: .6rem;}}

/* ---------- Live network widget ---------- */
.net {{padding: .9rem 1rem; margin-top: .4rem;}}
.net-title {{font-size: .7rem; font-weight: 700; color: #86efac; text-transform: uppercase;
            letter-spacing: .1em; margin-bottom: .55rem;}}
.net-row {{display: flex; align-items: center; gap: .55rem; font-weight: 600; color: #f0fdf4;
          font-size: .92rem;}}
.net-sub {{font-size: .78rem; color: #bbf7d0; margin-top: .35rem; line-height: 1.4; opacity: .9;}}
.dot {{width: 10px; height: 10px; border-radius: 50%; background: #34d399; flex: none;
      animation: pulse 1.8s infinite;}}
.dot.off {{background: #94a3b8; animation: none;}}
@keyframes pulse {{
  0% {{box-shadow: 0 0 0 0 rgba(52, 211, 153, .65);}}
  70% {{box-shadow: 0 0 0 10px rgba(52, 211, 153, 0);}}
  100% {{box-shadow: 0 0 0 0 rgba(52, 211, 153, 0);}}
}}
.addr {{display: inline-flex; align-items: center; gap: .35rem; margin-top: .65rem;
       padding: .35rem .8rem; border-radius: 999px; background: rgba(16, 185, 129, .14);
       border: 1px solid rgba(110, 231, 183, .40); color: #bbf7d0 !important;
       font-family: ui-monospace, monospace; font-size: .8rem; text-decoration: none !important;
       transition: all .2s ease;}}
.addr:hover {{background: rgba(16, 185, 129, .26); box-shadow: 0 0 14px rgba(16, 185, 129, .35);}}

/* ---------- Hero with ClimateChain circuit banner ---------- */
.hero {{padding: 2rem 2.2rem 1.7rem; margin-bottom: 1rem;
       background-image:
           linear-gradient(115deg, rgba(6, 56, 42, 0.90) 0%, rgba(8, 74, 55, 0.80) 55%,
                           rgba(10, 82, 66, 0.72) 100%){hero_img_layer} !important;
       background-size: cover, cover !important;
       background-position: center, right center !important;
       box-shadow: 0 8px 32px rgba(6, 48, 36, .28), inset 0 1px 0 rgba(255, 255, 255, .08);}}
.hero .title {{font-size: 2.7rem; font-weight: 800; margin: 0; line-height: 1.1;
              letter-spacing: -0.02em;
              background: linear-gradient(90deg, #ffffff 0%, #bbf7d0 55%, #99f6e4 100%);
              -webkit-background-clip: text; background-clip: text; color: transparent;}}
.hero .sub {{color: #ecfdf5; font-size: 1.08rem; margin: .6rem 0 0; max-width: 860px;
            line-height: 1.55;}}
.pill {{display: inline-block; background: rgba(255, 255, 255, 0.14);
       border: 1px solid rgba(255, 255, 255, 0.24); backdrop-filter: blur(6px);
       color: #ffffff; padding: .32rem .85rem; border-radius: 999px;
       margin: 1rem .4rem 0 0; font-size: .86rem; font-weight: 500;}}
.purpose {{margin-top: 1.2rem; background: rgba(8, 47, 43, 0.58);
          border: 1px solid rgba(134, 239, 172, 0.28); border-left: 4px solid #6ee7b7;
          backdrop-filter: blur(8px);
          border-radius: 10px; padding: .75rem 1rem; color: #f0fdf4; font-size: .95rem;
          line-height: 1.5; max-width: 920px;}}
.purpose b {{color: #86efac;}}

/* ---------- How it works ---------- */
.flow {{display: flex; align-items: stretch; gap: .6rem; flex-wrap: wrap; margin-bottom: 1.2rem;}}
.flow-step {{flex: 1 1 180px; display: flex; gap: .7rem; align-items: flex-start;
            padding: .85rem .95rem; transition: all .2s ease;}}
.flow-step:hover {{transform: translateY(-2px); border-color: rgba(110, 231, 183, .5) !important;
                  box-shadow: 0 6px 20px rgba(16, 185, 129, .22);}}
.flow-num {{flex: none; width: 30px; height: 30px; border-radius: 50%;
           background: linear-gradient(135deg, #10b981, #14b8a6); color: #042f2e;
           font-weight: 800; display: flex; align-items: center; justify-content: center;
           font-size: .9rem; box-shadow: 0 0 12px rgba(16, 185, 129, .4);}}
.flow-step b {{color: #f0fdf4; font-size: .98rem;}}
.flow-step span {{color: #bbf7d0; font-size: .83rem; line-height: 1.4;}}
.flow-arrow {{align-self: center; color: #86efac; font-size: 1.5rem; font-weight: 700;}}
@media (max-width: 900px) {{.flow-arrow {{display: none;}}}}

/* ---------- KPI cards ---------- */
.card {{--accent: #34d399; padding: .95rem 1rem; height: 100%; min-width: 0;
       transition: all 0.2s ease; box-shadow: 0 4px 14px rgba(0, 0, 0, .14);}}
.card:hover {{transform: translateY(-2px); border-color: var(--accent) !important;
             box-shadow: 0 6px 20px color-mix(in srgb, var(--accent) 32%, transparent);}}
.card.accent {{border-top: 3px solid var(--accent) !important;
              box-shadow: 0 4px 16px color-mix(in srgb, var(--accent) 16%, transparent);}}
.card .label {{font-size: .7rem; font-weight: 700; color: #bbf7d0; text-transform: uppercase;
              letter-spacing: .07em; display: flex; align-items: center; gap: .3rem;
              flex-wrap: wrap;}}
.card .value {{font-size: 1.85rem; font-weight: 800; margin-top: .25rem; line-height: 1.15;
              overflow-wrap: anywhere;}}
.card .note {{font-size: .8rem; color: #bbf7d0; opacity: .82; margin-top: .15rem; line-height: 1.4;}}

/* ---------- Tooltip (?) ---------- */
.tip {{display: inline-flex; align-items: center; justify-content: center; width: 16px;
      height: 16px; border-radius: 50%; background: rgba(110, 231, 183, .18);
      border: 1px solid rgba(110, 231, 183, .45); color: #bbf7d0; font-size: .64rem;
      font-weight: 800; cursor: help; position: relative; text-transform: none;
      letter-spacing: 0; flex: none;}}
.tip:hover::after {{content: attr(data-tip); position: absolute; top: 22px; left: 50%;
      transform: translateX(-50%); width: 250px; background: #06382c; color: #f0fdf4;
      border: 1px solid rgba(110, 231, 183, .45); padding: .6rem .75rem; border-radius: 10px;
      font-size: .78rem; font-weight: 400; line-height: 1.45; z-index: 1000;
      white-space: normal; text-align: left; box-shadow: 0 6px 20px rgba(0, 0, 0, .3);}}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"] {{gap: .35rem; background: rgba(8, 42, 33, .58);
    padding: .35rem; border-radius: 12px; border: 1px solid rgba(110, 231, 183, .22);
    backdrop-filter: blur(12px);}}
.stTabs [data-baseweb="tab"] {{border-radius: 9px; padding: .45rem .95rem;}}
.stTabs [aria-selected="true"] {{background: rgba(16, 185, 129, .22);}}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{display: none;}}

/* ---------- Results ---------- */
.result {{border-radius: 14px; padding: 1.1rem 1.3rem; margin: .6rem 0; color: #ffffff;}}
.result .big {{font-size: 1.45rem; font-weight: 800;}}
.result-ok {{background: linear-gradient(135deg, rgba(5, 122, 85, .9), rgba(16, 185, 129, .85));
            box-shadow: 0 4px 20px rgba(16, 185, 129, .32);}}
.result-bad {{background: linear-gradient(135deg, rgba(185, 28, 28, .9), rgba(239, 68, 68, .85));
             box-shadow: 0 4px 20px rgba(239, 68, 68, .32);}}
.step {{font-size: .76rem; font-weight: 700; color: #86efac; text-transform: uppercase;
       letter-spacing: .1em; margin-top: 1.2rem;}}
.legend {{display: flex; gap: 1rem; flex-wrap: wrap; font-size: .84rem; color: #dcfce7;
         margin: .2rem 0 .4rem;}}
.legend i {{display: inline-block; width: 10px; height: 10px; border-radius: 3px;
           margin-right: .35rem;}}
</style>
"""


# ------------------------------------------------------------- UI helpers
def tip(text):
    return f'<span class="tip" data-tip="{html.escape(text, quote=True)}">?</span>'


def card(col, label, value, color="#ecfdf5", note="", help_text="", accent=None):
    cls = "card accent" if accent else "card"
    style = f' style="--accent:{accent}"' if accent else ""
    t = tip(help_text) if help_text else ""
    col.markdown(f'<div class="{cls}"{style}><div class="label">{label}{t}</div>'
                 f'<div class="value" style="color:{color}">{value}</div>'
                 f'<div class="note">{note}</div></div>', unsafe_allow_html=True)


def result_box(ok, title, text):
    cls = "result-ok" if ok else "result-bad"
    st.markdown(f'<div class="result {cls}"><div class="big">{title}</div>'
                f'<div>{text}</div></div>', unsafe_allow_html=True)


def step(text):
    st.markdown(f'<div class="step">{text}</div>', unsafe_allow_html=True)


def style_fig(fig, height=330):
    grid = "rgba(167, 243, 208, 0.10)"
    fig.update_layout(
        template="plotly_dark", height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=36, b=8),
        font=dict(family="Plus Jakarta Sans, sans-serif", color="#d1fae5", size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    title_text="", bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="#022c22", bordercolor="#10b981",
                        font=dict(color="#ecfdf5", family="Plus Jakarta Sans, sans-serif")),
    )
    fig.update_xaxes(gridcolor=grid, zeroline=False, linecolor="rgba(167, 243, 208, 0.25)")
    fig.update_yaxes(gridcolor=grid, zeroline=False, linecolor="rgba(167, 243, 208, 0.25)")
    return fig


def show_fig(fig):
    cfg = {"displayModeBar": False}
    try:
        st.plotly_chart(fig, width="stretch", config=cfg)
    except Exception:
        st.plotly_chart(fig, use_container_width=True, config=cfg)


def show_table(df):
    try:
        st.dataframe(df, width="stretch", hide_index=True)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True)


STATUS_LEGEND = (f'<div class="legend"><span><i style="background:{EMERALD}"></i>OK — safe to use'
                 f'</span><span><i style="background:{AMBER}"></i>Review — check first</span>'
                 f'<span><i style="background:{CRIMSON}"></i>Quarantine — flagged, do not use'
                 f'</span></div>')


# ===================================================================== UI
st.set_page_config(page_title="EcoProve AI", page_icon="🌍", layout="wide")
st.markdown(build_css(), unsafe_allow_html=True)

try:
    data = load_data()
except FileNotFoundError:
    st.error(f"Data file not found: {CSV_PATH}")
    st.stop()

months = sorted(data.ay.unique())

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown('<div class="brand">🌍 EcoProve AI</div>'
                '<div class="brand-sub">Trust Layer for Climate Data · Ankara, Türkiye</div>',
                unsafe_allow_html=True)
    month = st.selectbox("Month", months,
                         help="Pick a month. Overview, Source Comparison and Verify on Chain "
                              "show this month. Source Trust and Seal Registry show all months.")
    city = st.selectbox("City Label on Chain", CITY_LABELS, help=TIP["city"])

    block = latest_block()
    dot = "dot" if block else "dot off"
    block_txt = f"Latest block #{block:,}" if block else "Network not reachable right now"
    st.markdown(f"""
<div class="net">
  <div class="net-title">Live Network Status</div>
  <div class="net-row"><span class="{dot}"></span>Ethereum Sepolia (Testnet)</div>
  <div class="net-sub">{block_txt}</div>
  <a class="addr" href="{ETHERSCAN_ADDR}" target="_blank">📄 {CONTRACT[:8]}…{CONTRACT[-6:]} ↗</a>
  <div class="net-sub">The monthly fingerprints of the daily records are stored in this
  smart contract.</div>
</div>
""", unsafe_allow_html=True)
    st.caption("Copy Contract Address")
    st.code(CONTRACT, language=None)

m = data[data.ay == month].reset_index(drop=True)
mn = numeric(m, ["score", "tmean"])

# --------------------------------------------------------------------- hero
st.markdown("""
<div class="hero">
  <div class="title">🌍 EcoProve AI</div>
  <div class="sub">How much can you trust a climate number? We compare three data sources,
  give every daily value a Reliability Score, and seal the result on the blockchain so
  anyone can check it was never changed.</div>
  <div class="purpose">🎯 <b>Why it matters:</b> parametric crop insurance pays out when a
  threshold is crossed (for example "below 0 °C"), and clean-energy planners rely on
  temperature and wind thresholds too. When data sources disagree, the decision can change.
  EcoProve shows how reliable each value is, and proves it was not edited afterwards.</div>
  <span class="pill">📡 3 Data Sources</span>
  <span class="pill">🧠 Reliability Score 0–100</span>
  <span class="pill">🌳 Monthly Merkle Roots</span>
  <span class="pill">🔗 Sealed on Ethereum Sepolia</span>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="flow">
  <div class="flow-step"><div class="flow-num">1</div><div><b>Collect</b><br>
    <span>Daily climate data from ERA5, NASA POWER and a NOAA weather station.</span></div></div>
  <div class="flow-arrow">→</div>
  <div class="flow-step"><div class="flow-num">2</div><div><b>Score</b><br>
    <span>Compare the sources and check changes over time → Reliability Score.</span></div></div>
  <div class="flow-arrow">→</div>
  <div class="flow-step"><div class="flow-num">3</div><div><b>Seal</b><br>
    <span>One digital fingerprint per month is stored on the blockchain.</span></div></div>
  <div class="flow-arrow">→</div>
  <div class="flow-step"><div class="flow-num">4</div><div><b>Verify</b><br>
    <span>Anyone can check that a record was not changed. Free, no wallet.</span></div></div>
</div>
""", unsafe_allow_html=True)

tab1, tab2, tab_thr, tab_trust, tab3, tab_reg, tab4 = st.tabs([
    "📊 Overview", "🔀 Source Comparison", "🎯 Threshold Check", "🏆 Source Trust",
    "🔗 Verify on Chain", "📜 Seal Registry", "ℹ️ About & Limits"])

# ---------------------------------------------------------------- Overview
with tab1:
    counts = m.status.value_counts()
    c1, c2, c3, c4, c5 = st.columns(5)
    card(c1, "Records", len(m), note=f"{m.source.nunique()} sources · {month}",
         help_text=TIP["records"], accent=CYAN)
    card(c2, "Avg Score", f"{mn.score.mean():.1f}", EMERALD, "out of 100",
         help_text=TIP["score"], accent=EMERALD)
    card(c3, "OK", int(counts.get("OK", 0)), EMERALD, "safe to use",
         help_text=TIP["ok"], accent=EMERALD)
    card(c4, "Review", int(counts.get("Review", 0)), AMBER, "needs a check",
         help_text=TIP["review"], accent=AMBER)
    card(c5, "Quarantine", int(counts.get("Quarantine", 0)), CRIMSON, "flagged",
         help_text=TIP["quarantine"], accent=CRIMSON)

    st.markdown("### Daily Reliability Score")
    st.caption("Each line is one data source. Higher means more trustworthy. "
               "A dip shows a day where the sources disagree or the value changes unusually.")
    fig = px.line(mn, x="date", y="score", color="source", markers=True,
                  line_shape="spline", color_discrete_sequence=SOURCE_COLORS,
                  hover_data={"status": True},
                  labels={"date": "Date", "score": "Reliability Score (0–100)",
                          "source": "Source", "status": "Status"})
    fig.update_traces(line=dict(width=3), marker=dict(size=6))
    fig.update_yaxes(range=[0, 102])
    show_fig(style_fig(fig, 360))

    left, right = st.columns([1, 2])
    with left:
        st.markdown("### Status Breakdown")
        sdf = pd.DataFrame({"Status": counts.index, "Records": counts.values})
        bars = px.bar(sdf, x="Status", y="Records", color="Status",
                      color_discrete_map=STATUS_COLORS,
                      category_orders={"Status": ["OK", "Review", "Quarantine", "No_Reference"]})
        bars.update_layout(showlegend=False, bargap=0.35)
        bars.update_traces(marker_line_width=0)
        show_fig(style_fig(bars, 290))
    with right:
        st.markdown("### Status Map (Day × Source)")
        st.markdown(STATUS_LEGEND, unsafe_allow_html=True)
        hm = m.assign(day=m.date.str[8:10])
        heat = px.scatter(hm, x="day", y="source", color="status",
                          color_discrete_map=STATUS_COLORS,
                          hover_data={"date": True, "tmean": True, "score": True, "day": False},
                          labels={"day": "Day of Month", "source": "", "status": "Status"},
                          category_orders={"day": sorted(hm.day.unique())})
        heat.update_traces(marker=dict(symbol="square", size=17, line=dict(width=0)))
        heat.update_layout(showlegend=False)
        show_fig(style_fig(heat, 260))

    with st.expander("📋 Show All Records"):
        show_table(m.drop(columns=["ay"]))
        st.download_button("⬇️ Download This Month (CSV)",
                           m.drop(columns=["ay"]).to_csv(index=False).encode("utf-8"),
                           file_name=f"ecoprove_{month}.csv", mime="text/csv")

# ------------------------------------------------------- Source Comparison
with tab2:
    skip = {"date", "source", "status", "ay"}
    num_cols = [c for c in m.columns if c not in skip
                and pd.to_numeric(m[c], errors="coerce").notna().any()]
    default = num_cols.index("tmean") if "tmean" in num_cols else 0
    var = st.selectbox("Variable", num_cols, index=default,
                       help="Pick a measurement (for example tmean = daily mean temperature).")
    vn = numeric(m, [var])

    st.markdown(f"### {var} — Sources Side by Side ({month})")
    st.caption("If the lines are close, the sources agree. A gap means at least one "
               "source reports something different for that day.")
    comp = px.line(vn, x="date", y=var, color="source", markers=True, line_shape="spline",
                   color_discrete_sequence=SOURCE_COLORS,
                   labels={"date": "Date", "source": "Source"})
    comp.update_traces(line=dict(width=3), marker=dict(size=6))
    show_fig(style_fig(comp, 360))

    pv = vn.pivot_table(index="date", columns="source", values=var)
    if pv.shape[1] >= 2:
        spread = (pv.max(axis=1) - pv.min(axis=1)).reset_index(name="spread")
        st.markdown("### Daily Disagreement Between Sources")
        st.caption("Highest value minus lowest value on each day. Taller bar = bigger disagreement.")
        sp = px.bar(spread, x="date", y="spread",
                    labels={"date": "Date", "spread": f"Spread of {var} (max − min)"})
        sp.update_traces(marker_color=CYAN, marker_line_width=0)
        show_fig(style_fig(sp, 250))

    st.markdown("### Day Inspector")
    st.caption("Pick one day to see what every source reported, side by side.")
    day = st.selectbox("Day", sorted(m.date.unique()),
                       help="All values, scores and statuses of the sources for this day.")
    dd = m[m.date == day].drop(columns=["ay"]).set_index("source").T.astype(str)
    show_table(dd.reset_index().rename(columns={"index": "Field"}))
    st.info("When sources disagree on the same day, the Reliability Score goes down "
            "and the record can be marked Review or Quarantine.")

# --------------------------------------------------------- Verify on Chain
with tab3:
    st.markdown("### Is This Record Still the Same as When It Was Sealed?")
    st.markdown(f"Every month, all records are combined into one digital fingerprint and stored "
                f"on the blockchain {tip(TIP['seal'])}. Here you can check any single record "
                f"against that fingerprint. It is free and you do not need a wallet.",
                unsafe_allow_html=True)

    step("Step 1 · Pick a Record")
    labels = [f"{r.date} · {r.source} · Tmean {r.tmean} °C · Score {r.score} · {r.status}"
              for r in m.itertuples()]
    idx = st.selectbox("Record", range(len(m)), format_func=lambda i: labels[i],
                       help="One row = one day from one data source.")
    row = m.iloc[idx]

    leaves = month_leaves(month)
    leaf = leaves[idx]
    proof = kanit(leaves, idx)
    local_root = kok(leaves)

    with st.expander("🔍 Technical Details (Leaf, Proof, Local Root)"):
        st.caption("Leaf = fingerprint of this one record. Proof = the few extra fingerprints "
                   "needed to rebuild the monthly fingerprint. Local root = the monthly "
                   "fingerprint rebuilt on this computer.")
        st.code(f"leaf text : {row.date}|{row.source}|{row.tmean}|{row.score}|{row.status}\n"
                f"leaf      : {hx(leaf)}\n"
                f"local root: {hx(local_root)}\n"
                f"proof ({len(proof)} hashes):\n" + "\n".join(hx(p) for p in proof))
        proof_doc = {
            "network": "Ethereum Sepolia (chainId 11155111)", "contract": CONTRACT,
            "function": "verify(string city, string period, bytes32 leaf, bytes32[] proof)",
            "city": city, "period": month,
            "leaf_text": f"{row.date}|{row.source}|{row.tmean}|{row.score}|{row.status}",
            "leaf_hash": "keccak256(leaf_text)", "leaf": hx(leaf),
            "proof": [hx(p) for p in proof], "local_root": hx(local_root)}
        st.download_button("⬇️ Download Proof (JSON)", json.dumps(proof_doc, indent=2),
                           file_name=f"proof_{row.date}_{row.source}.json",
                           mime="application/json",
                           help="Anyone can use this file to ask the smart contract directly, "
                                "without this website.")

    step("Step 2 · Verify on Chain")
    if st.button("🔗 Verify on Chain", type="primary",
                 help="Asks the smart contract if this record matches the sealed fingerprint."):
        try:
            with st.spinner("Asking the smart contract on Sepolia..."):
                chain_root, count, ts = read_root(city, month)
                ok = verify_on_chain(city, month, leaf, proof)
            when = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if ok:
                result_box(True, "✅ Verified",
                           "This record is exactly the same as when it was sealed.")
            else:
                result_box(False, "❌ Not Verified",
                           "This record does not match the sealed fingerprint.")
            match = chain_root == local_root
            r1, r2, r3 = st.columns(3)
            card(r1, "Sealed Records", count, note=f"{city} / {month}", accent=CYAN,
                 help_text="How many records were inside the monthly fingerprint.")
            card(r2, "Sealed At", when.split(" ")[0], note=when.split(" ", 1)[1], accent=CYAN,
                 help_text="When the fingerprint was written to the blockchain.")
            card(r3, "Root Match", "Yes" if match else "No", EMERALD if match else CRIMSON,
                 "local = on chain", accent=EMERALD if match else CRIMSON,
                 help_text="Yes = the data file on this site is the same file that was sealed.")
            st.caption(f"Root on chain: `{hx(chain_root)}`")
        except Exception as e:
            t = chain_error_text(e)
            if t == "not_found":
                st.warning(f"No fingerprint on chain yet for **{city} / {month}**. "
                           "Try another month or city label.")
            else:
                st.error(t)

    step("Step 3 · Tamper Test")
    st.caption("Try to cheat: change a value below. The record's fingerprint changes, so the "
               "blockchain should now say Not Verified.")
    c1, c2, c3 = st.columns(3)
    new_tmean = c1.text_input("Tmean (°C)", value=str(row.tmean),
                              help="Daily mean temperature of this record.")
    new_score = c2.text_input("Score", value=str(row.score), help=TIP["score"])
    statuses = sorted(set(data.status.unique()) | {"OK", "Review", "Quarantine"})
    new_status = c3.selectbox("Status", statuses, index=statuses.index(row.status),
                              help="OK / Review / Quarantine.")
    fake_leaf = leaf_from_values(row.date, row.source, new_tmean, new_score, new_status)
    if fake_leaf != leaf:
        st.caption(f"✏️ Changed fingerprint: `{hx(fake_leaf)}`")
    else:
        st.caption("Nothing changed yet. Edit a value above.")

    if st.button("🧪 Verify Changed Record",
                 help="Sends the changed record with the original proof to the smart contract."):
        try:
            with st.spinner("Asking the smart contract on Sepolia..."):
                ok = verify_on_chain(city, month, fake_leaf, proof)
            if ok:
                result_box(True, "✅ Verified", "The value was not changed.")
            else:
                result_box(False, "❌ Not Verified — Tampering Detected",
                           "The record was changed after it was sealed. "
                           "The blockchain rejects it.")
        except Exception as e:
            t = chain_error_text(e)
            if t == "not_found":
                st.warning(f"No fingerprint on chain yet for **{city} / {month}**.")
            else:
                st.error(t)

    st.markdown(f"Smart contract: [{CONTRACT}]({ETHERSCAN_ADDR})")

# ------------------------------------------------------------ About & Limits
with tab4:
    st.markdown("### How to Use This Site")
    st.markdown("""
| Tab | What you can do |
|---|---|
| 📊 **Overview** | See this month at a glance: scores, statuses, which days had problems. |
| 🔀 **Source Comparison** | Compare the three sources for any variable and inspect a single day. |
| 🎯 **Threshold Check** | Pick a decision rule (for example frost: below 0 °C) and see on which days the sources give different answers. |
| 🏆 **Source Trust** | See which source was most reliable over the whole period. |
| 🔗 **Verify on Chain** | Check one record against the blockchain and try the tamper test. |
| 📜 **Seal Registry** | See which months are sealed on the blockchain and whether they match the data. |
""")
    st.markdown("### What Problem Does EcoProve Solve?")
    st.markdown("Different climate data sources often give **different numbers for the same "
                "day**. One source may say it was −1 °C, another +1 °C. For a decision that "
                "uses a threshold (\"Was there frost?\"), this changes the answer. EcoProve "
                "does not say which number is right. It shows **how reliable** each value is "
                "and makes the result **traceable and tamper-evident**.")

    st.markdown("### Who Can Use It?")
    u1, u2, u3 = st.columns(3)
    card(u1, "Crop Insurance", "🌾", note="Weather-index insurance pays when a threshold is "
         "crossed (frost, heat). Insurers and farmers can see if the data behind a payout "
         "is reliable.", accent=EMERALD)
    card(u2, "Energy Planning", "☀️", note="Solar and wind planners can avoid days with low "
         "data reliability when they build models.", accent=CYAN)
    card(u3, "Climate Reporting", "📄", note="Cities and companies can show auditors that "
         "the data in a report was not changed after it was published.", accent=AMBER)

    st.markdown("### Key Terms")
    st.markdown(f"""
- **Reliability Score (0–100):** {TIP['score']}
- **OK / Review / Quarantine:** OK = safe to use · Review = check before use · Quarantine = flagged, do not use until checked.
- **Merkle root (digital fingerprint):** one short code that represents all records of a month. Change one number and the code changes.
- **On-chain seal:** the monthly fingerprint is stored in a smart contract. Nobody, including us, can overwrite it.
- **Testnet (Sepolia):** a free public test version of Ethereum. It works like the real network but uses test money.
""")

    st.markdown("### Honest Limits")
    st.markdown("""
- The blockchain proves a record **was not changed** after sealing. It does **not** prove the value is correct.
- Cross-checking is done by the **scoring code**; the blockchain only **seals** the result.
- The sources are not fully independent (reanalysis products also use observations).
- One city (Ankara) and a limited number of years.
- Testnet (Sepolia), not mainnet.
""")
    st.markdown(f"### Links\n- Smart contract on Etherscan: [{CONTRACT}]({ETHERSCAN_ADDR})")
    st.caption("AI assistance: Claude (Anthropic) was used during development.")


# --------------------------------------------------------- Threshold Check
with tab_thr:
    st.markdown("### Does the Data Source Change the Decision?")
    st.markdown("Many climate decisions use a simple rule, for example *\"Was there frost?\"* "
                "(temperature below 0 °C). Pick a rule below. For every day, we check the rule "
                "with each source. If the sources give **different answers**, the decision "
                "depends on which source you trust. That is exactly where EcoProve helps.")

    all_num = [c for c in data.columns if c not in {"date", "source", "status", "ay", "score"}
               and pd.to_numeric(data[c], errors="coerce").notna().any()]
    presets = []
    if "tmin" in all_num:
        presets.append(("❄️ Frost Day — tmin below 0 °C", "tmin", "<", 0.0))
    if "tmax" in all_num:
        presets.append(("🔥 Hot Day — tmax at or above 30 °C", "tmax", ">=", 30.0))
    if "tmean" in all_num:
        presets.append(("🧊 Freezing Day — tmean below 0 °C", "tmean", "<", 0.0))
    presets.append(("✏️ Custom Rule", None, None, None))

    a, b = st.columns([2, 1])
    choice = a.selectbox("Decision Rule", range(len(presets)),
                         format_func=lambda i: presets[i][0],
                         help="A threshold rule like the ones used in weather-index insurance.")
    scope = b.radio("Period", ["Selected Month", "All Months"], horizontal=True,
                    help="Check only the month in the sidebar, or the whole data file.")
    _, var_t, op_t, thr_t = presets[choice]
    if var_t is None:
        x1, x2, x3 = st.columns(3)
        var_t = x1.selectbox("Variable", all_num, key="thr_var")
        op_lbl = x2.selectbox("Condition", ["below (<)", "at or above (≥)"], key="thr_op")
        op_t = "<" if op_lbl.startswith("below") else ">="
        thr_t = x3.number_input("Threshold", value=0.0, step=0.5, key="thr_val")

    src_df = m if scope == "Selected Month" else data
    rec, days = threshold_eval(src_df, var_t, op_t, thr_t)
    sym = "<" if op_t == "<" else "≥"

    if rec.empty:
        st.warning("No numeric values for this variable in the selected period.")
    else:
        n_days = len(days)
        n_dis = int(days.disagree.sum())
        n_dis_flag = int((days.disagree & days.flagged).sum())
        n_any = int((days.yes > 0).sum())
        k1, k2, k3, k4 = st.columns(4)
        card(k1, "Days Checked", n_days, note=f"rule: {var_t} {sym} {thr_t:g}", accent=CYAN,
             help_text="Number of days with at least one source value for this variable.")
        card(k2, "Rule Met (Any Source)", n_any, EMERALD, "days", accent=EMERALD,
             help_text="Days where at least one source says the rule is met.")
        card(k3, "Sources Disagree", n_dis, AMBER,
             f"{(n_dis / n_days * 100 if n_days else 0):.1f}% of days", accent=AMBER,
             help_text="Days where one source says YES and another says NO. On these days "
                       "the decision depends on the data source.")
        card(k4, "Disagreement Flagged", f"{n_dis_flag}/{n_dis}", CRIMSON,
             "marked Review / Quarantine", accent=CRIMSON,
             help_text="Of the disagreement days, how many had at least one record that "
                       "EcoProve marked Review or Quarantine.")

        st.markdown(f"### Rule Result per Day and Source ({var_t} {sym} {thr_t:g})")
        st.caption("Green = rule met, grey = not met. Amber bands = days where the sources "
                   "disagree.")
        rec = rec.assign(Result=rec.crossed.map({True: "Rule met", False: "Not met"}))
        fig_t = px.scatter(rec, x="date", y="source", color="Result",
                           color_discrete_map={"Rule met": EMERALD, "Not met": "#475569"},
                           hover_data={var_t: True, "score": True, "status": True},
                           labels={"date": "Date", "source": ""})
        fig_t.update_traces(marker=dict(symbol="square", size=11 if scope == "All Months" else 17,
                                        line=dict(width=0)))
        dis_dates = list(days.index[days.disagree])
        if len(dis_dates) <= 120:
            for dt in dis_dates:
                t0 = pd.Timestamp(dt)
                fig_t.add_vrect(x0=t0 - pd.Timedelta(hours=12), x1=t0 + pd.Timedelta(hours=12),
                                fillcolor=AMBER, opacity=0.22, line_width=0, layer="below")
        show_fig(style_fig(fig_t, 280))

        if n_dis:
            st.markdown("### Days Where the Sources Disagree")
            dis_tbl = rec[rec.date.isin(dis_dates)][["date", "source", var_t, "Result",
                                                     "score", "status"]]
            show_table(dis_tbl.rename(columns={"date": "Date", "source": "Source",
                                               "score": "Score", "status": "Status"}))
        else:
            st.success("All sources give the same answer on every day for this rule.")

# ------------------------------------------------------------ Source Trust
with tab_trust:
    first, last = months[0], months[-1]
    st.markdown("### Which Source Was Most Reliable?")
    st.caption(f"Based on all records in the data file ({first} to {last}).")
    dn = numeric(data, ["score"])
    trust = dn.groupby("source").agg(
        records=("score", "size"), avg=("score", "mean"),
        ok=("status", lambda s: (s == "OK").mean() * 100),
        review=("status", lambda s: (s == "Review").mean() * 100),
        quar=("status", lambda s: (s == "Quarantine").mean() * 100),
    ).reset_index().sort_values("avg", ascending=False).reset_index(drop=True)

    medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
    cols = st.columns(max(len(trust), 1))
    for i, r in trust.iterrows():
        card(cols[i], f"{medals[min(i, 4)]} {r.source}", f"{r.avg:.1f}",
             SOURCE_COLORS[i % len(SOURCE_COLORS)],
             f"avg score · {r.ok:.0f}% OK · {r.quar:.0f}% Quarantine",
             accent=SOURCE_COLORS[i % len(SOURCE_COLORS)],
             help_text="Average Reliability Score of this source over the whole period, "
                       "and the share of its records in each status.")

    l, r_ = st.columns(2)
    with l:
        st.markdown("### Status Share per Source")
        share = px.histogram(data, y="source", color="status", barnorm="percent",
                             color_discrete_map=STATUS_COLORS, orientation="h",
                             category_orders={"status": ["OK", "Review", "Quarantine",
                                                         "No_Reference"]},
                             labels={"source": "", "status": "Status"})
        share.update_layout(xaxis_title="% of records", bargap=0.35)
        share.update_traces(marker_line_width=0)
        show_fig(style_fig(share, 300))
    with r_:
        st.markdown("### Average Score per Month")
        monthly = dn.groupby(["ay", "source"], as_index=False).score.mean()
        mfig = px.line(monthly, x="ay", y="score", color="source", markers=True,
                       line_shape="spline", color_discrete_sequence=SOURCE_COLORS,
                       labels={"ay": "Month", "score": "Avg Reliability Score",
                               "source": "Source"})
        mfig.update_traces(line=dict(width=3), marker=dict(size=7))
        show_fig(style_fig(mfig, 300))

    show_table(trust.rename(columns={"source": "Source", "records": "Records",
                                     "avg": "Avg Score", "ok": "OK %", "review": "Review %",
                                     "quar": "Quarantine %"}).round(1))

# ----------------------------------------------------------- Seal Registry
with tab_reg:
    st.markdown("### Seal Registry — Which Months Are on the Blockchain?")
    st.markdown(f"For every month in the data file we rebuild the digital fingerprint "
                f"{tip(TIP['seal'])} and compare it with the one stored in the smart contract "
                f"under the city label **{city}**.", unsafe_allow_html=True)

    if st.button("🔄 Check All Months on Chain", type="primary",
                 help="Reads the smart contract once per month. Free, no wallet."):
        st.session_state["registry_city"] = city

    if st.session_state.get("registry_city") == city:
        local = all_local_roots()
        rows = []
        with st.spinner("Reading the smart contract..."):
            for ay, (lroot, cnt) in local.items():
                info = chain_lookup(city, ay)
                if info["state"] == "found":
                    status = "✅ Sealed — matches" if info["root"] == lroot \
                        else "⚠️ Sealed — different data"
                    when = datetime.fromtimestamp(info["ts"], timezone.utc).strftime(
                        "%Y-%m-%d %H:%M UTC")
                elif info["state"] == "not_found":
                    status, when = "⏳ Not sealed yet", "—"
                else:
                    status, when = "📡 Network error", "—"
                rows.append({"Month": ay, "Records": cnt,
                             "Local Fingerprint": f"{lroot[:10]}…{lroot[-6:]}",
                             "On-Chain Status": status, "Sealed At": when})
        reg = pd.DataFrame(rows)
        n_total = len(reg)
        n_match = int(reg["On-Chain Status"].str.startswith("✅").sum())
        n_diff = int(reg["On-Chain Status"].str.startswith("⚠️").sum())
        n_wait = int(reg["On-Chain Status"].str.startswith("⏳").sum())
        g1, g2, g3, g4 = st.columns(4)
        card(g1, "Months in File", n_total, accent=CYAN,
             help_text="How many months the data file covers.")
        card(g2, "Sealed & Matching", n_match, EMERALD, accent=EMERALD,
             help_text="The fingerprint on the blockchain equals the one rebuilt from the file.")
        card(g3, "Different Data", n_diff, CRIMSON, accent=CRIMSON,
             help_text="A fingerprint exists on the blockchain, but the file has changed since "
                       "it was sealed.")
        card(g4, "Not Sealed Yet", n_wait, AMBER, accent=AMBER,
             help_text="No fingerprint for this month and city label on the blockchain yet.")
        st.progress(n_match / n_total if n_total else 0.0,
                    text=f"{n_match} of {n_total} months sealed and matching")
        show_table(reg)
        st.caption(f"Smart contract: {CONTRACT} · Each month is one blockchain transaction.")
    else:
        st.info("Press the button to read the seal status of every month from the blockchain.")
