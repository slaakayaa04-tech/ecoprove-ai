"""EcoProve AI - Streamlit web app.

Reads the reliability score file, rebuilds the monthly Merkle trees
(same scheme as merkle_kok.py) and verifies records against the
EcoProveRegistry smart contract on Ethereum Sepolia (read-only, no wallet).

Run:  streamlit run app.py
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from Crypto.Hash import keccak
from web3 import Web3
from web3.exceptions import ContractLogicError

# ---------------------------------------------------------------- settings
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "data" / "reliability_scores_v1.csv"
FORECAST_CSV = BASE_DIR / "data" / "tahmin_yillik_2026.csv"
FORECAST_SUMMARY_CSV = BASE_DIR / "data" / "tahmin_yillik_ozet_2026.csv"
FAULT_SUMMARY_CSV = BASE_DIR / "data" / "sahte_hata_ozet.csv"
FAULT_DETAILS_CSV = BASE_DIR / "data" / "sahte_hata_sonuc.csv"
SENSITIVITY_CSV = BASE_DIR / "data" / "esik_duyarlilik.csv"
DEMO_CASES_CSV = BASE_DIR / "data" / "demo_ornekleri.csv"
BG_IMAGE_PATH = BASE_DIR / "assets" / "climatechain_bg.png"

CONTRACT = "0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89"
RPC_URL = "https://ethereum-sepolia-rpc.publicnode.com"
ETHERSCAN_ADDR = f"https://sepolia.etherscan.io/address/{CONTRACT}"
CITY_LABELS = ["Ankara", "TEST"]

EMERALD, CYAN, CORAL = "#10b981", "#06b6d4", "#f43f5e"
AMBER, CRIMSON, SLATE = "#f59e0b", "#ef4444", "#94a3b8"
SOURCE_COLORS = [EMERALD, CYAN, CORAL, AMBER, "#a78bfa"]

STATUS_ORDER = ["Trusted", "Review", "Quarantined", "Missing"]
STATUS_COLORS = {
    "Trusted": EMERALD,
    "Review": AMBER,
    "Quarantined": CRIMSON,
    "Missing": SLATE,
}
STATUS_SYMBOLS = {
    "Trusted": "circle",
    "Review": "diamond",
    "Quarantined": "x",
    "Missing": "square-open",
}

# Single source of truth for status definitions (aligned on z_eff thresholds)
STATUS_META = {
    "Trusted": {
        "short": "z ≤ 3 · score 84–100",
        "legend": "● Trusted (z ≤ 3, score 84–100) — safe to use",
        "tip": "Trusted (z_eff ≤ 3, score 84–100): sources agree and the value lies within the expected band.",
    },
    "Review": {
        "short": "3 < z ≤ 6 · score 50–84",
        "legend": "◆ Review (3 < z ≤ 6, score 50–84) — check before use",
        "tip": "Review (3 < z_eff ≤ 6, score 50–84): noticeable disagreement or deviation; inspect before decision use.",
    },
    "Quarantined": {
        "short": "z > 6 · score 0–49",
        "legend": "✕ Quarantined (z > 6, score 0–49) — archived with reason",
        "tip": "Quarantined (z_eff > 6, score 0–49): strong anomaly or sensor fault. Never deleted — archived with its reason.",
    },
    "Missing": {
        "short": "station silent",
        "legend": "□ Missing — station silent",
        "tip": "Missing: the weather station reported no value on this day (kept in the calendar so gaps remain visible).",
    },
}

TIP = {
    "records": "Number of daily source records in this month (3 sources × days in month).",
    "score": "Reliability Score (0–100) derived from penalty z_eff: 100 × 2^(-(z_eff/6)^2).",
    "ok": STATUS_META["Trusted"]["tip"],
    "review": STATUS_META["Review"]["tip"],
    "quarantine": STATUS_META["Quarantined"]["tip"],
    "missing": STATUS_META["Missing"]["tip"],
    "seal": "Every month, all daily records are hashed into one 32-byte keccak256 Merkle root and sealed on Ethereum Sepolia.",
    "city": "Ankara = production roots for all 80 months (2020–2026). TEST = initial trial roots (2023-01..03).",
}

NUM_COLS = ["tmean", "expected_low", "expected_high", "z_eff", "score"]

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
            s.append(L[i])
        else:
            s.append(k(min(L[i], L[i + 1]) + max(L[i], L[i + 1])))
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
def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


@st.cache_data
def _load_raw_strings_cached(csv_path: str, mtime: float) -> pd.DataFrame:
    """Preserves exact string formatting required for deterministic Merkle leaves."""
    d = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    d = d.sort_values(["date", "source"]).reset_index(drop=True)
    d["ay"] = d.date.str[:7]
    return d


@st.cache_data
def _load_data_cached(csv_path: str, mtime: float) -> pd.DataFrame:
    """Loads numeric columns as proper floats so sorting and charts work accurately."""
    d = pd.read_csv(csv_path)
    for c in NUM_COLS:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.sort_values(["date", "source"]).reset_index(drop=True)
    d["ay"] = d.date.str[:7]
    return d


def load_raw_strings() -> pd.DataFrame:
    return _load_raw_strings_cached(str(CSV_PATH), _mtime(CSV_PATH))


def load_data() -> pd.DataFrame:
    return _load_data_cached(str(CSV_PATH), _mtime(CSV_PATH))


@st.cache_data
def _month_leaves_cached(ay: str, mtime: float):
    raw = _load_raw_strings_cached(str(CSV_PATH), mtime)
    return [yaprak(r) for r in raw[raw.ay == ay].itertuples()]


def month_leaves(ay: str):
    return _month_leaves_cached(ay, _mtime(CSV_PATH))


@st.cache_data
def _all_local_roots_cached(mtime: float):
    raw = _load_raw_strings_cached(str(CSV_PATH), mtime)
    return {
        ay: (hx(kok(_month_leaves_cached(ay, mtime))), int((raw.ay == ay).sum()))
        for ay in sorted(raw.ay.unique())
    }


def all_local_roots():
    return _all_local_roots_cached(_mtime(CSV_PATH))


@st.cache_data
def load_csv_cached(path_str: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path_str)


def read_aux_csv(path: Path) -> pd.DataFrame:
    return load_csv_cached(str(path), _mtime(path))


# -------------------------------------------------------------- blockchain
@st.cache_resource
def get_contract():
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 15}))
    return w3.eth.contract(address=Web3.to_checksum_address(CONTRACT), abi=ABI)


@st.cache_data(ttl=30, show_spinner=False)
def latest_block():
    try:
        return get_contract().w3.eth.block_number
    except Exception:
        return None


def is_not_found_error(e: Exception) -> bool:
    if isinstance(e, ContractLogicError):
        return "not found" in str(e).lower()
    return "not found" in str(e).lower()


def chain_error_text(e: Exception) -> str:
    if is_not_found_error(e):
        return "not_found"
    return f"Could not reach the Sepolia network. Please try again in a few seconds. ({str(e)[:140]})"


def read_root(city: str, period: str):
    root, count, ts = get_contract().functions.getRoot(city, period).call()
    return bytes(root), count, ts


def verify_on_chain(city: str, period: str, leaf: bytes, proof: list[bytes]) -> bool:
    return get_contract().functions.verify(city, period, leaf, proof).call()


@st.cache_data(ttl=300, show_spinner=False)
def _chain_lookup_cached(city: str, period: str):
    """Caches only definitive contract responses ('found' or 'not_found').
    Raises on transient network errors so Streamlit never caches a failed RPC call.
    """
    try:
        root, count, ts = read_root(city, period)
        return {"state": "found", "root": hx(root), "count": count, "ts": ts}
    except Exception as e:
        if is_not_found_error(e):
            return {"state": "not_found"}
        raise


def chain_lookup(city: str, period: str):
    try:
        return _chain_lookup_cached(city, period)
    except Exception:
        return {"state": "error"}


def fetch_registry(city: str) -> pd.DataFrame:
    local = all_local_roots()
    months_list = list(local.keys())
    with ThreadPoolExecutor(max_workers=8) as ex:
        infos = list(ex.map(lambda ay: chain_lookup(city, ay), months_list))
    rows = []
    for ay, info in zip(months_list, infos):
        lroot, cnt = local[ay]
        if info["state"] == "found":
            status = "✅ Sealed — matches" if info["root"] == lroot else "⚠️ Sealed — different data"
            when = datetime.fromtimestamp(info["ts"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        elif info["state"] == "not_found":
            status, when = "⏳ Not sealed yet", "—"
        else:
            status, when = "📡 Network error", "—"
        rows.append({
            "Month": ay,
            "Records": cnt,
            "Local Fingerprint": f"{lroot[:10]}…{lroot[-6:]}",
            "On-Chain Status": status,
            "Sealed At": when,
        })
    return pd.DataFrame(rows)


@st.cache_data
def threshold_eval_cached(csv_mtime: float, scope_month: str | None, var: str, op: str, thr: float):
    df = load_data()
    if scope_month is not None:
        df = df[df.ay == scope_month]
    d = df[df[var].notna()].copy()
    if d.empty:
        return d, pd.DataFrame()
    d["crossed"] = d[var] < thr if op == "<" else d[var] >= thr
    days = d.groupby("date").agg(
        n=("crossed", "size"),
        yes=("crossed", "sum"),
        flagged=("status", lambda s: bool((s != "Trusted").any())),
    )
    days["disagree"] = (days.n >= 2) & (days.yes > 0) & (days.yes < days.n)
    return d, days


# ------------------------------------------------------------------- styles
@st.cache_data
def get_bg_data_uri(mtime: float) -> str:
    if BG_IMAGE_PATH.exists():
        b64 = base64.b64encode(BG_IMAGE_PATH.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    return ""


def is_light_mode() -> bool:
    return st.session_state.get("theme_mode") == "☀️ Light"


@st.cache_data
def build_css(bg_mtime: float, is_light: bool = False) -> str:
    bg_uri = get_bg_data_uri(bg_mtime)
    bg_img_layer = f", url('{bg_uri}')" if bg_uri else ""
    hero_img_layer = f", url('{bg_uri}')" if bg_uri else ""
    light_overrides = """
/* ---------- Light Theme Overrides ---------- */
.stApp {
    background: linear-gradient(160deg, #f8fafc 0%, #f0fdf4 55%, #ecfdf5 100%) !important;
    background-image: none !important;
}
[data-testid="stHeader"] {background: rgba(255, 255, 255, 0.85) !important; backdrop-filter: blur(10px);}
h1, h2, h3, h4, h5 {color: #064e3b !important;}
p, li, label, [data-testid="stWidgetLabel"] p {color: #1e293b !important;}
a {color: #059669 !important;}
.stCaption, [data-testid="stCaptionContainer"] {color: #475569 !important; opacity: 1;}
.glass, .card, .net {
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06) !important;
}
[data-testid="stExpander"] details {
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
}
[data-testid="stExpander"] summary p {color: #0f172a !important; font-weight: 600;}
[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #e2e8f0 !important;
}
.brand {color: #064e3b !important;}
.brand span {background: linear-gradient(90deg, #065f46, #059669, #0284c7);
             -webkit-background-clip: text; background-clip: text; color: transparent;}
.brand-sub {color: #475569 !important;}
.net-title {color: #059669 !important;}
.net-row {color: #0f172a !important;}
.net-sub {color: #475569 !important;}
.addr {background: #ecfdf5 !important; border: 1px solid #6ee7b7 !important; color: #065f46 !important;}
.card .label {color: #475569 !important;}
.card .note {color: #64748b !important; opacity: 1;}
.stTabs [data-baseweb="tab-list"] {background: #f1f5f9 !important; border: 1px solid #cbd5e1 !important;}
.stTabs [data-baseweb="tab"] p {color: #334155 !important; font-weight: 600;}
.stTabs [aria-selected="true"] {background: #ffffff !important; box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);}
.stTabs [aria-selected="true"] p {color: #059669 !important;}
.step {color: #059669 !important;}
.legend {color: #1e293b !important;}
""" if is_light else ""
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

.stMarkdown, .stMarkdown p, .stMarkdown li, .stCaption,
h1, h2, h3, h4, h5, .stTabs button p, .stButton button p {{
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
.block-container, [data-testid="stMainBlockContainer"] {{padding-top: 1.2rem !important;}}

h3 {{font-weight: 700 !important; color: #f0fdf4 !important; letter-spacing: -0.01em;}}
p, li {{color: #dcfce7;}}
a {{color: #6ee7b7 !important;}}
.stCaption, [data-testid="stCaptionContainer"] {{color: #bbf7d0 !important; opacity: .9;}}

/* ---------- Soft Frosted Glass Base (no backdrop-filter on expanders to avoid fixed clipping) ---------- */
.glass, .card, .net, .hero {{
    background: rgba(10, 46, 36, 0.66) !important;
    backdrop-filter: blur(14px) !important;
    -webkit-backdrop-filter: blur(14px) !important;
    border: 1px solid rgba(110, 231, 183, 0.22) !important;
    border-radius: 14px !important;
}}
[data-testid="stExpander"] details {{
    background: rgba(10, 46, 36, 0.92) !important;
    border: 1px solid rgba(110, 231, 183, 0.22) !important;
    border-radius: 14px !important;
}}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {{
    background: rgba(7, 38, 30, 0.78) !important;
    border-right: 1px solid rgba(110, 231, 183, 0.24) !important;
}}
[data-testid="stSidebarContent"] {{background: transparent !important;}}
.brand {{font-size: 1.35rem; font-weight: 800; color: #f0fdf4;}}
.brand span {{background: linear-gradient(90deg, #f0fdf4, #86efac, #67e8f9);
              -webkit-background-clip: text; background-clip: text; color: transparent;}}
.brand-sub {{font-size: .82rem; color: #bbf7d0; margin-bottom: .6rem;}}

/* ---------- Live network widget ---------- */
.net {{padding: .85rem .95rem; margin-top: .5rem;}}
.net-title {{font-size: .7rem; font-weight: 700; color: #86efac; text-transform: uppercase;
            letter-spacing: .1em; margin-bottom: .45rem;}}
.net-row {{display: flex; align-items: center; gap: .55rem; font-weight: 600; color: #f0fdf4;
          font-size: .9rem;}}
.net-sub {{font-size: .78rem; color: #bbf7d0; margin-top: .3rem; line-height: 1.4; opacity: .9;}}
.dot {{width: 10px; height: 10px; border-radius: 50%; background: #34d399; flex: none;
      animation: pulse 1.8s infinite;}}
.dot.off {{background: #94a3b8; animation: none;}}
@keyframes pulse {{
  0% {{box-shadow: 0 0 0 0 rgba(52, 211, 153, .65);}}
  70% {{box-shadow: 0 0 0 10px rgba(52, 211, 153, 0);}}
  100% {{box-shadow: 0 0 0 0 rgba(52, 211, 153, 0);}}
}}
.addr {{display: inline-flex; align-items: center; gap: .35rem; margin-top: .55rem;
       padding: .35rem .75rem; border-radius: 999px; background: rgba(16, 185, 129, .14);
       border: 1px solid rgba(110, 231, 183, .40); color: #bbf7d0 !important;
       font-family: ui-monospace, monospace; font-size: .78rem; text-decoration: none !important;}}

/* ---------- Compact Hero ---------- */
.hero {{padding: 1.35rem 1.7rem 1.2rem; margin-bottom: .9rem;
       background-image:
           linear-gradient(115deg, rgba(6, 56, 42, 0.90) 0%, rgba(8, 74, 55, 0.80) 55%,
                           rgba(10, 82, 66, 0.72) 100%){hero_img_layer} !important;
       background-size: cover, cover !important;
       background-position: center, right center !important;
       box-shadow: 0 8px 28px rgba(6, 48, 36, .25);}}
.hero .title {{font-size: 2.15rem; font-weight: 800; margin: 0; line-height: 1.15;
              letter-spacing: -0.02em; color: #ffffff;}}
.hero .title span {{background: linear-gradient(90deg, #ffffff 0%, #bbf7d0 55%, #99f6e4 100%);
                    -webkit-background-clip: text; background-clip: text; color: transparent;}}
.hero .sub {{color: #ecfdf5; font-size: .98rem; margin: .4rem 0 0; max-width: 820px;
            line-height: 1.45;}}
.pill {{display: inline-block; background: rgba(255, 255, 255, 0.14);
       border: 1px solid rgba(255, 255, 255, 0.24);
       color: #ffffff; padding: .26rem .75rem; border-radius: 999px;
       margin: .65rem .35rem 0 0; font-size: .8rem; font-weight: 500;}}

/* ---------- KPI cards ---------- */
.card {{--accent: #34d399; padding: .85rem .95rem; height: 100%; min-width: 0; margin-bottom: .55rem;
       transition: border-color 0.2s ease, box-shadow 0.2s ease; box-shadow: 0 4px 14px rgba(0, 0, 0, .14);}}
@media (hover: hover) {{
  .card:hover {{transform: translateY(-2px); border-color: var(--accent) !important;
               box-shadow: 0 6px 20px color-mix(in srgb, var(--accent) 32%, transparent);}}
}}
.card.accent {{border-top: 3px solid var(--accent) !important;}}
.card .label {{font-size: .7rem; font-weight: 700; color: #bbf7d0; text-transform: uppercase;
              letter-spacing: .06em; display: flex; align-items: center; gap: .3rem;}}
.card .value {{font-size: 1.65rem; font-weight: 800; margin-top: .2rem; line-height: 1.15;
              overflow-wrap: anywhere;}}
.card .note {{font-size: .78rem; color: #bbf7d0; opacity: .85; margin-top: .15rem; line-height: 1.35;}}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"] {{gap: .35rem; background: rgba(8, 42, 33, .65);
    padding: .35rem; border-radius: 12px; border: 1px solid rgba(110, 231, 183, .22);
    flex-wrap: wrap;}}
.stTabs [data-baseweb="tab"] {{border-radius: 9px; padding: .45rem .9rem;}}
.stTabs [aria-selected="true"] {{background: rgba(16, 185, 129, .24);}}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{display: none;}}

/* ---------- Results ---------- */
.result {{border-radius: 14px; padding: 1rem 1.2rem; margin: .55rem 0; color: #ffffff;}}
.result .big {{font-size: 1.3rem; font-weight: 800;}}
.result-ok {{background: linear-gradient(135deg, rgba(5, 122, 85, .92), rgba(16, 185, 129, .88));}}
.result-bad {{background: linear-gradient(135deg, rgba(185, 28, 28, .92), rgba(239, 68, 68, .88));}}
.step {{font-size: .76rem; font-weight: 700; color: #86efac; text-transform: uppercase;
       letter-spacing: .1em; margin-top: 1.1rem;}}
.legend {{display: flex; gap: 1rem; flex-wrap: wrap; font-size: .82rem; color: #dcfce7;
         margin: .2rem 0 .45rem;}}
.legend i {{display: inline-block; width: 10px; height: 10px; border-radius: 3px;
           margin-right: .35rem;}}

{light_overrides}

/* ---------- Responsive / Mobile ---------- */
@media (max-width: 768px) {{
  .stApp {{ background-attachment: scroll !important; }}
  .hero {{ padding: 1.1rem 1.2rem; }}
  .hero .title {{ font-size: 1.65rem; }}
  .hero .sub {{ font-size: .9rem; }}
  .card .value {{ font-size: 1.35rem; }}
  .pill {{ font-size: .74rem; margin: .45rem .25rem 0 0; }}
}}
</style>
"""


# ------------------------------------------------------------- UI helpers
def card(col, label, value, color="#ecfdf5", note="", help_text="", accent=None):
    if color == "#ecfdf5" and is_light_mode():
        color = "#0f172a"
    cls = "card accent" if accent else "card"
    style = f' style="--accent:{accent}"' if accent else ""
    title_attr = f' title="{ (help_text or "").replace(chr(34), "&quot;") }"' if help_text else ""
    badge = ' <span style="opacity:.7;font-size:.75rem;cursor:help">ⓘ</span>' if help_text else ""
    col.markdown(
        f'<div class="{cls}"{style}{title_attr}><div class="label">{label}{badge}</div>'
        f'<div class="value" style="color:{color}">{value}</div>'
        f'<div class="note">{note}</div></div>',
        unsafe_allow_html=True,
    )


def result_box(ok, title, text):
    cls = "result-ok" if ok else "result-bad"
    st.markdown(f'<div class="result {cls}"><div class="big">{title}</div>'
                f'<div>{text}</div></div>', unsafe_allow_html=True)


def step(text):
    st.markdown(f'<div class="step">{text}</div>', unsafe_allow_html=True)


def sub_nav(label: str, options: list[str], key: str) -> str:
    if hasattr(st, "segmented_control"):
        val = st.segmented_control(label, options, default=options[0], key=key, label_visibility="collapsed")
        return val or options[0]
    return st.radio(label, options, horizontal=True, key=key, label_visibility="collapsed")


def style_fig(fig, height=330):
    light = is_light_mode()
    grid = "rgba(15, 23, 42, 0.08)" if light else "rgba(167, 243, 208, 0.10)"
    line_col = "rgba(15, 23, 42, 0.20)" if light else "rgba(167, 243, 208, 0.25)"
    font_col = "#1e293b" if light else "#d1fae5"
    hover_bg = "#ffffff" if light else "#022c22"
    hover_fg = "#0f172a" if light else "#ecfdf5"
    fig.update_layout(
        template="plotly_white" if light else "plotly_dark",
        height=height,
        dragmode=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=24, b=48),
        font=dict(family="Plus Jakarta Sans, sans-serif", color=font_col, size=13),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.18,
            xanchor="left",
            x=0,
            title_text="",
            bgcolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(
            bgcolor=hover_bg,
            bordercolor="#10b981",
            font=dict(color=hover_fg, family="Plus Jakarta Sans, sans-serif"),
        ),
    )
    fig.update_xaxes(gridcolor=grid, zeroline=False, fixedrange=True, linecolor=line_col)
    fig.update_yaxes(gridcolor=grid, zeroline=False, fixedrange=True, linecolor=line_col)
    return fig


def show_fig(fig):
    cfg = {"displayModeBar": False, "scrollZoom": False}
    try:
        st.plotly_chart(fig, width="stretch", config=cfg)
    except Exception:
        st.plotly_chart(fig, use_container_width=True, config=cfg)


DEFAULT_COL_CFG = {
    "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
    "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
    "Score (0–100)": st.column_config.ProgressColumn("Score (0–100)", min_value=0, max_value=100, format="%d"),
    "Reliability Score": st.column_config.ProgressColumn("Reliability Score", min_value=0, max_value=100, format="%d"),
    "tmean": st.column_config.NumberColumn("Tmean (°C)", format="%.2f"),
    "expected_low": st.column_config.NumberColumn("Expected Low (°C)", format="%.2f"),
    "expected_high": st.column_config.NumberColumn("Expected High (°C)", format="%.2f"),
    "z_eff": st.column_config.NumberColumn("Penalty (z_eff)", format="%.2f"),
}


def show_table(df: pd.DataFrame, custom_cfg: dict | None = None):
    cfg = {k: v for k, v in DEFAULT_COL_CFG.items() if k in df.columns}
    if custom_cfg:
        cfg.update(custom_cfg)
    try:
        st.dataframe(df, width="stretch", hide_index=True, column_config=cfg)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True, column_config=cfg)


STATUS_LEGEND = (
    '<div class="legend">'
    + "".join(
        f'<span><i style="background:{STATUS_COLORS[s]}"></i>{STATUS_META[s]["legend"]}</span>'
        for s in STATUS_ORDER
    )
    + "</div>"
)


# ============================================================ Tab Fragments
@st.fragment
def render_overview_group(month: str):
    data = load_data()
    m = data[data.ay == month].reset_index(drop=True)
    view = sub_nav(
        "Overview Section",
        ["📊 Monthly Overview", "🔀 Source Comparison", "🏆 Multi-Year Source Trust"],
        key="nav_overview",
    )

    if view == "📊 Monthly Overview":
        counts = m.status.value_counts()
        ok_cnt = int(counts.get("Trusted", 0))
        rev_cnt = int(counts.get("Review", 0))
        quar_cnt = int(counts.get("Quarantined", 0))
        miss_cnt = int(counts.get("Missing", 0))

        # 3 + 3 two-row responsive KPI layout
        r1c1, r1c2, r1c3 = st.columns(3)
        card(r1c1, "Records", len(m), note=f"{m.source.nunique()} sources · {month}",
             help_text=TIP["records"], accent=CYAN)
        card(r1c2, "Avg Score", f"{m.score.mean():.1f}" if m.score.notna().any() else "—",
             EMERALD, "out of 100", help_text=TIP["score"], accent=EMERALD)
        card(r1c3, "Trusted", ok_cnt, EMERALD, STATUS_META["Trusted"]["short"],
             help_text=TIP["ok"], accent=EMERALD)

        r2c1, r2c2, r2c3 = st.columns(3)
        card(r2c1, "Review", rev_cnt, AMBER, STATUS_META["Review"]["short"],
             help_text=TIP["review"], accent=AMBER)
        card(r2c2, "Quarantined", quar_cnt, CRIMSON, STATUS_META["Quarantined"]["short"],
             help_text=TIP["quarantine"], accent=CRIMSON)
        card(r2c3, "Missing", miss_cnt, SLATE, STATUS_META["Missing"]["short"],
             help_text=TIP["missing"], accent=SLATE)

        st.markdown("### Daily Reliability Score")
        st.caption("Each curve represents one data source (0–100). Dips highlight days with inter-source divergence or values outside the expected band.")
        fig = px.line(
            m, x="date", y="score", color="source", markers=True,
            line_shape="spline", color_discrete_sequence=SOURCE_COLORS,
            hover_data={"status": True, "tmean": ":.2f", "z_eff": ":.2f"},
            labels={"date": "Date", "score": "Reliability Score (0–100)",
                    "source": "Source", "status": "Status"},
        )
        fig.update_traces(line=dict(width=2.8), marker=dict(size=6))
        fig.update_yaxes(range=[0, 102])
        show_fig(style_fig(fig, 340))

        left, right = st.columns([1, 2])
        with left:
            st.markdown("### Status Breakdown")
            present_statuses = [s for s in STATUS_ORDER if int(counts.get(s, 0)) > 0]
            sdf = pd.DataFrame({
                "Status": present_statuses,
                "Records": [int(counts.get(s, 0)) for s in present_statuses],
            })
            bars = px.bar(
                sdf, x="Status", y="Records", color="Status",
                color_discrete_map=STATUS_COLORS,
                category_orders={"Status": present_statuses},
                text="Records",
            )
            bars.update_layout(showlegend=False, bargap=0.38)
            bars.update_traces(marker_line_width=0, textposition="outside")
            bars.update_yaxes(range=[0, max(sdf["Records"].max() * 1.18, 5)])
            show_fig(style_fig(bars, 290))
        with right:
            st.markdown("### Status Map (Day × Source)")
            st.markdown(STATUS_LEGEND, unsafe_allow_html=True)
            hm = m.assign(day=m.date.str[8:10])
            heat = px.scatter(
                hm, x="day", y="source", color="status", symbol="status",
                color_discrete_map=STATUS_COLORS,
                symbol_map=STATUS_SYMBOLS,
                hover_data={"date": True, "tmean": ":.2f", "score": True, "day": False},
                labels={"day": "Day of Month", "source": "", "status": "Status"},
                category_orders={"day": sorted(hm.day.unique()), "status": STATUS_ORDER},
            )
            heat.update_traces(marker=dict(size=12, line=dict(width=1, color="#042f2e")))
            heat.update_layout(showlegend=False)
            show_fig(style_fig(heat, 270))

        with st.expander("📋 Show All Records"):
            show_table(m.drop(columns=["ay"]))
            st.download_button(
                "⬇️ Download This Month (CSV)",
                m.drop(columns=["ay"]).to_csv(index=False).encode("utf-8"),
                file_name=f"ecoprove_{month}.csv",
                mime="text/csv",
            )

    elif view == "🔀 Source Comparison":
        skip = {"date", "source", "status", "ay"}
        num_cols = [c for c in m.columns if c not in skip and m[c].notna().any()]
        default = num_cols.index("tmean") if "tmean" in num_cols else 0
        var = st.selectbox(
            "Variable", num_cols, index=default,
            help="Select a numeric field (e.g., tmean = daily mean temperature in °C).",
        )

        st.markdown(f"### {var} — Sources Side by Side ({month})")
        st.caption("Tightly aligned curves indicate strong inter-source agreement; wider gaps indicate divergence.")
        comp = px.line(
            m, x="date", y=var, color="source", markers=True, line_shape="spline",
            color_discrete_sequence=SOURCE_COLORS,
            labels={"date": "Date", "source": "Source"},
        )
        comp.update_traces(line=dict(width=2.8), marker=dict(size=6))
        show_fig(style_fig(comp, 340))

        pv = m.pivot_table(index="date", columns="source", values=var)
        if pv.shape[1] >= 2:
            spread = (pv.max(axis=1) - pv.min(axis=1)).reset_index(name="spread")
            st.markdown("### Daily Spread Between Sources (Max − Min)")
            sp = px.bar(
                spread, x="date", y="spread",
                labels={"date": "Date", "spread": f"Spread of {var}"},
            )
            sp.update_traces(marker_color=CYAN, marker_line_width=0)
            show_fig(style_fig(sp, 240))

        st.markdown("### Day Inspector")
        day = st.selectbox("Select Day", sorted(m.date.unique()))
        day_df = m[m.date == day].drop(columns=["ay"]).reset_index(drop=True)
        show_table(day_df)

    else:
        months = sorted(data.ay.unique())
        first, last = months[0], months[-1]
        st.markdown(f"### Long-Term Source Reliability ({first} to {last})")
        trust = data.groupby("source").agg(
            records=("source", "size"),
            avg=("score", "mean"),
            ok=("status", lambda s: (s == "Trusted").mean() * 100),
            review=("status", lambda s: (s == "Review").mean() * 100),
            quar=("status", lambda s: (s == "Quarantined").mean() * 100),
            missing=("status", lambda s: int((s == "Missing").sum())),
        ).reset_index().sort_values("avg", ascending=False).reset_index(drop=True)

        medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
        cols = st.columns(max(len(trust), 1))
        for i, r in trust.iterrows():
            card(
                cols[i], f"{medals[min(i, 4)]} {r.source}", f"{r.avg:.1f}",
                SOURCE_COLORS[i % len(SOURCE_COLORS)],
                f"avg score · {r.ok:.1f}% Trusted · {int(r.missing)} Missing days",
                accent=SOURCE_COLORS[i % len(SOURCE_COLORS)],
            )

        l_col, r_col = st.columns(2)
        with l_col:
            st.markdown("### Status Share per Source")
            share = px.histogram(
                data, y="source", color="status", barnorm="percent",
                color_discrete_map=STATUS_COLORS, orientation="h",
                category_orders={"status": STATUS_ORDER},
                labels={"source": "", "status": "Status"},
            )
            share.update_layout(xaxis_title="% of records", bargap=0.35)
            share.update_traces(marker_line_width=0)
            show_fig(style_fig(share, 300))
        with r_col:
            st.markdown("### Average Score per Month")
            monthly = data.groupby(["ay", "source"], as_index=False)["score"].mean()
            mfig = px.line(
                monthly, x="ay", y="score", color="source",
                line_shape="spline", color_discrete_sequence=SOURCE_COLORS,
                labels={"ay": "Month", "score": "Avg Score", "source": "Source"},
            )
            mfig.update_traces(line=dict(width=2.5))
            show_fig(style_fig(mfig, 300))

        show_table(trust.rename(columns={
            "source": "Source", "records": "Total Days",
            "avg": "Avg Score", "ok": "Trusted %", "review": "Review %",
            "quar": "Quarantined %", "missing": "Missing Days",
        }).round(2))


@st.fragment
def render_ai_group(month: str):
    data = load_data()
    m = data[data.ay == month].reset_index(drop=True)
    view = sub_nav(
        "AI & Validation Section",
        ["📈 AI Forecast vs Actual", "🧪 Fault Benchmark & Quarantine", "🎯 Decision Threshold Check"],
        key="nav_ai",
    )

    if view == "📈 AI Forecast vs Actual":
        st.markdown("### Walk-Forward AI Forecast vs Actual Temperature (2023 – 2026)")
        st.caption(
            "Each test year is predicted strictly from earlier years (zero same-day leakage): "
            "2023 trained on 2020–2022 · 2024 on 2020–2023 · 2025 on 2020–2024 · 2026 on 2020–2025."
        )

        if FORECAST_CSV.exists() and FORECAST_SUMMARY_CSV.exists():
            fc_df = read_aux_csv(FORECAST_CSV)
            fsum = read_aux_csv(FORECAST_SUMMARY_CSV)

            yr_options = [
                "2026 (Trained on 2020–2025)",
                "2025 (Trained on 2020–2024)",
                "2024 (Trained on 2020–2023)",
                "2023 (Trained on 2020–2022)",
                f"Selected Sidebar Month ({month})",
            ]
            c_sel1, c_sel2 = st.columns([2, 2])
            yr_choice = c_sel1.selectbox("Select Walk-Forward Test Period", yr_options)
            show_baselines = c_sel2.checkbox("Overlay Persistence & Climatology baselines", value=False)

            if yr_choice.startswith("Selected Sidebar"):
                sel_year = int(month[:4])
                sub_fc = fc_df[fc_df["date"].str.startswith(month)].copy()
                period_label = f"Month {month}"
            else:
                sel_year = int(yr_choice[:4])
                sub_fc = fc_df[fc_df["yil"] == sel_year].copy()
                period_label = yr_choice

            match_rows = fsum[fsum["test_yili"] == sel_year]
            if not match_rows.empty and not sub_fc.empty:
                r_row = match_rows.iloc[0]
                f1, f2, f3, f4 = st.columns(4)
                card(f1, f"{sel_year} LightGBM MAE", f"{r_row['MAE_lightgbm']:.2f} °C", EMERALD,
                     f"trained on {r_row['egitim']}", accent=EMERALD)
                card(f2, f"{sel_year} Persistence MAE", f"{r_row['MAE_persistence']:.2f} °C", AMBER,
                     "yesterday = today baseline", accent=AMBER)
                card(f3, f"{sel_year} Climatology MAE", f"{r_row['MAE_iklimatoloji']:.2f} °C", CORAL,
                     "historical day average", accent=CORAL)
                card(f4, "90% Band Coverage", f"{r_row['aralik_kapsama'] * 100:.1f}%", CYAN,
                     f"avg width {r_row['aralik_genislik']:.1f} °C", accent=CYAN)

                st.markdown(f"#### Actual Reference vs LightGBM Forecast — {period_label}")
                st.caption("Compares daily actual reference temperature against our walk-forward LightGBM point forecast and 90% expected interval [q05, q95].")

                fig_fc = go.Figure()
                fig_fc.add_trace(go.Scatter(
                    x=sub_fc["date"], y=sub_fc["ust"],
                    mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
                ))
                fig_fc.add_trace(go.Scatter(
                    x=sub_fc["date"], y=sub_fc["alt"],
                    mode="lines", line=dict(width=0), fill="tonexty",
                    fillcolor="rgba(56, 189, 248, 0.16)",
                    name="90% Expected Band [q05–q95]",
                ))
                fig_fc.add_trace(go.Scatter(
                    x=sub_fc["date"], y=sub_fc["gercek"],
                    mode="lines+markers" if len(sub_fc) <= 40 else "lines",
                    name="Actual Temperature (°C)",
                    line=dict(color="#0f172a" if is_light_mode() else "#ffffff", width=2.4),
                ))
                fig_fc.add_trace(go.Scatter(
                    x=sub_fc["date"], y=sub_fc["lightgbm"],
                    mode="lines+markers" if len(sub_fc) <= 40 else "lines",
                    name="Our AI Forecast — LightGBM (°C)",
                    line=dict(color="#fbbf24", width=2.8),
                ))
                if show_baselines:
                    fig_fc.add_trace(go.Scatter(
                        x=sub_fc["date"], y=sub_fc["persistence"],
                        mode="lines", name="Persistence Baseline (°C)",
                        line=dict(color="#a78bfa", width=1.6, dash="dot"),
                    ))
                    fig_fc.add_trace(go.Scatter(
                        x=sub_fc["date"], y=sub_fc["iklimatoloji"],
                        mode="lines", name="Climatology Baseline (°C)",
                        line=dict(color=CORAL, width=1.6, dash="dash"),
                    ))
                fig_fc.update_layout(xaxis_title="Date", yaxis_title="Daily Mean Temperature (°C)")
                show_fig(style_fig(fig_fc, 380))

                sub_fc["abs_err"] = (sub_fc["lightgbm"] - sub_fc["gercek"]).abs().round(2)
                sub_fc["in_band"] = ((sub_fc["gercek"] >= sub_fc["alt"]) & (sub_fc["gercek"] <= sub_fc["ust"])).map(
                    {True: "✅ Inside [q05, q95]", False: "⚠️ Outside Band"}
                )
                with st.expander(f"📋 Show Daily Actual vs Forecast Table ({len(sub_fc)} days)"):
                    show_table(sub_fc[["date", "gercek", "lightgbm", "abs_err", "alt", "ust", "in_band", "persistence", "iklimatoloji"]].rename(columns={
                        "date": "Date", "gercek": "Actual (°C)", "lightgbm": "Our AI Forecast (°C)",
                        "abs_err": "Abs Error (°C)", "alt": "Expected Low q05 (°C)",
                        "ust": "Expected High q95 (°C)", "in_band": "90% Band Check",
                        "persistence": "Persistence (°C)", "iklimatoloji": "Climatology (°C)",
                    }))
            else:
                st.info(
                    f"**{month}** is part of the initial `2020–2021` baseline training window used to learn seasonal patterns "
                    "without data leakage. Select any year from **2023 to 2026** (or pick a sidebar month from 2022–2026) "
                    "to view out-of-sample walk-forward predictions."
                )

            st.markdown("#### Walk-Forward Summary Across Test Years (2023 – 2026)")
            show_table(fsum[fsum["test_yili"] >= 2023].rename(columns={
                "test_yili": "Test Year", "egitim": "Training Period", "gun": "Days",
                "MAE_persistence": "Persistence MAE (°C)", "MAE_lightgbm": "Our AI (LightGBM) MAE (°C)",
                "MAE_iklimatoloji": "Climatology MAE (°C)", "aralik_kapsama": "Band Coverage",
                "aralik_genislik": "Band Width (°C)", "sicak5_hata": "Top-5% Hot Days MAE (°C)",
            }))

    elif view == "🧪 Fault Benchmark & Quarantine":
        st.markdown("### Synthetic Fault Injection & Real Heatwave Benchmark")
        st.caption(
            "Evaluates whether EcoProve catches single-sensor faults (spikes, unit errors, stuck sensors, gradual drift) "
            "without falsely quarantining real multi-source heatwaves (+7 °C across all three providers)."
        )

        if DEMO_CASES_CSV.exists():
            st.markdown("#### 1 · Three Key Scenarios (Normal vs Sensor Fault vs Real Heatwave)")
            demo_df = read_aux_csv(DEMO_CASES_CSV).copy()
            scen_map = {
                "1) Normal gün": "1) Normal Day (Sources Agree)",
                "2) NOAA sensörü 45.8 C gönderiyor": "2) NOAA Sensor Spike (45.8 °C Fault)",
                "3) Gerçek ekstrem (3 kaynak da +7 C)": "3) Real Heatwave (+7 °C Across All 3 Sources)",
            }
            demo_df["senaryo"] = demo_df["senaryo"].map(lambda x: scen_map.get(x, x))
            show_table(demo_df.rename(columns={
                "senaryo": "Scenario", "kaynak": "Source", "tmean": "Reported Tmean (°C)",
                "expected_low": "Expected Low (°C)", "expected_high": "Expected High (°C)",
                "z_eff": "Penalty (z_eff)", "score": "Reliability Score", "status": "Decision Status",
            }))

        if FAULT_SUMMARY_CSV.exists():
            f_df = read_aux_csv(FAULT_SUMMARY_CSV)
            gen_f1 = float(f_df.loc[f_df["tur"] == "GENEL_F1", "yakalama_review_veya_karantina"].iloc[0])
            base_f1 = float(f_df.loc[f_df["tur"] == "BASELINE_F1", "yakalama_review_veya_karantina"].iloc[0])
            best_f1 = gen_f1
            min_ext_quar = 0.0
            if SENSITIVITY_CSV.exists():
                s_df_tmp = read_aux_csv(SENSITIVITY_CSV)
                best_f1 = float(s_df_tmp["F1"].max())
                min_ext_quar = float(s_df_tmp.loc[s_df_tmp["F1"].idxmax(), "gercek_ekstrem_karantina"])

            parts = f_df[~f_df["tur"].isin(["GENEL_F1", "BASELINE_F1"])].copy()
            spike_rate = float(parts.loc[parts["tur"].isin(["sicrama", "birim_hatasi"]), "yakalama_review_veya_karantina"].mean() * 100)

            b1, b2, b3, b4 = st.columns(4)
            card(b1, "EcoProve F1 (Single Run)", f"{gen_f1:.3f}", EMERALD,
                 f"10-seed best F1: {best_f1:.3f}", accent=EMERALD)
            card(b2, "Heston Baseline F1", f"{base_f1:.3f}", CRIMSON,
                 "single-series |z| > 3", accent=CRIMSON)
            card(b3, "Spikes & Unit Errors", f"{spike_rate:.0f}%", EMERALD,
                 "caught immediately", accent=EMERALD)
            card(b4, "Real Heatwaves Kept", f"{(1.0 - min_ext_quar) * 100:.1f}%", CYAN,
                 "not falsely quarantined", accent=CYAN)

            name_map = {
                "sicrama": "Sudden Spike (±15 °C)",
                "birim_hatasi": "Unit Error (°C ↔ °F)",
                "takili_sensor": "Stuck Sensor (7 days)",
                "drift": "Gradual Drift (20 days)",
            }
            parts["Fault Type"] = parts["tur"].map(lambda x: name_map.get(x, x))
            parts["Caught (%)"] = (parts["yakalama_review_veya_karantina"] * 100).round(1)
            st.markdown("#### 2 · Detection Rate by Injected Fault Type")
            f_bar = px.bar(
                parts, x="Fault Type", y="Caught (%)", color="Fault Type",
                color_discrete_sequence=SOURCE_COLORS, text="Caught (%)",
            )
            f_bar.update_traces(texttemplate="%{text:.1f}%", textposition="outside", marker_line_width=0)
            f_bar.update_yaxes(range=[0, 116])
            f_bar.update_layout(showlegend=False)
            show_fig(style_fig(f_bar, 290))

        if FAULT_DETAILS_CSV.exists():
            fd = read_aux_csv(FAULT_DETAILS_CSV).copy()
            fd["score"] = (100 * (2.0 ** (-((fd["z_eff"] / 6.0) ** 2)))).round().astype(int)
            d_counts = fd["durum"].value_counts()
            n_quar = int(d_counts.get("Quarantined", 0))
            n_rev = int(d_counts.get("Review", 0))
            n_heat = int((fd["etiket"] == "gercek_ekstrem").sum())

            st.markdown(f"#### 3 · 🚨 Quarantine Archive & Injected Fault Timeline ({n_quar} Quarantined · {n_rev} Review)")
            label_map = {
                "temiz": "Clean Day",
                "sicrama": "Sudden Spike (±15 °C)",
                "birim_hatasi": "Unit Error (°C ↔ °F)",
                "takili_sensor": "Stuck Sensor",
                "drift": "Gradual Drift (+6 °C)",
                "gercek_ekstrem": "Real Heatwave (+7 °C all 3 sources)",
            }
            fd["Reason / Scenario"] = fd["etiket"].map(lambda x: label_map.get(x, x))

            fig_f = go.Figure()
            fig_f.add_trace(go.Scatter(
                x=fd["date"], y=fd["temiz_deger"], mode="lines",
                name="Original Clean NOAA (°C)",
                line=dict(color="rgba(167, 243, 208, 0.45)", width=2, dash="dot"),
            ))
            for st_name, col_hex in [("Trusted", EMERALD), ("Review", AMBER), ("Quarantined", CRIMSON)]:
                sub = fd[fd["durum"] == st_name]
                if not sub.empty:
                    fig_f.add_trace(go.Scatter(
                        x=sub["date"], y=sub["sensor_bozuk"], mode="markers",
                        name=f"{st_name} ({len(sub)} days)",
                        marker=dict(
                            color=col_hex,
                            size=9 if st_name != "Trusted" else 5,
                            symbol=STATUS_SYMBOLS.get(st_name, "circle"),
                        ),
                        customdata=sub[["Reason / Scenario", "temiz_deger", "z_eff", "score"]],
                        hovertemplate=(
                            "<b>%{x}</b><br>Reported: %{y:.2f} °C (Clean: %{customdata[1]:.2f} °C)<br>"
                            "Scenario: %{customdata[0]}<br>z_eff: %{customdata[2]:.2f} · Score: %{customdata[3]}<extra></extra>"
                        ),
                    ))
            fig_f.update_layout(xaxis_title="Date (2023 Benchmark)", yaxis_title="NOAA Temperature (°C)")
            show_fig(style_fig(fig_f, 350))

            opt_q = f"🚨 Quarantined ({n_quar})"
            opt_qr = f"⚠️ Flagged ({n_quar + n_rev})"
            opt_hw = f"🔥 Heatwaves ({n_heat})"
            opt_all = f"📋 All ({len(fd)})"
            filt = sub_nav("Filter Archive", [opt_q, opt_qr, opt_hw, opt_all], key="fault_filter")

            if filt == opt_q:
                sub_tbl = fd[fd["durum"] == "Quarantined"]
            elif filt == opt_qr:
                sub_tbl = fd[fd["durum"].isin(["Quarantined", "Review"])]
            elif filt == opt_hw:
                sub_tbl = fd[fd["etiket"] == "gercek_ekstrem"]
            else:
                sub_tbl = fd

            show_table(sub_tbl[["date", "Reason / Scenario", "sensor_bozuk", "temiz_deger", "z_eff", "score", "durum"]].rename(columns={
                "date": "Date", "sensor_bozuk": "Reported Tmean (°C)", "temiz_deger": "Clean Tmean (°C)",
                "z_eff": "Penalty (z_eff)", "score": "Score (0–100)", "durum": "Decision Status",
            }))

        if SENSITIVITY_CSV.exists():
            with st.expander("📊 Show Multi-Seed Threshold Sensitivity Table (Precision / Recall / F1)"):
                s_df = read_aux_csv(SENSITIVITY_CSV).copy()
                s_df["mod"] = s_df["mod"].map({
                    "guven_ACIK": "Adaptive Trust ON",
                    "guven_KAPALI": "Adaptive Trust OFF (Default)",
                }).fillna(s_df["mod"])
                show_table(s_df.rename(columns={
                    "mod": "Scoring Mode",
                    "T_review": "Review Threshold (z)",
                    "T_quar": "Quarantine Threshold (z)",
                    "precision": "Precision",
                    "recall": "Recall",
                    "F1": "F1 Score",
                    "yanlis_alarm": "False Alarm Rate (Clean Data)",
                    "gercek_ekstrem_karantina": "Real Heatwave Quarantined Rate",
                }))

    else:
        st.markdown("### Does the Data Source Change the Decision?")
        st.caption(
            "Parametric crop insurance and energy models rely on binary temperature thresholds (e.g., frost below 0 °C). "
            "Here we identify days where sources disagree on whether the threshold was crossed."
        )

        all_num = [c for c in data.columns if c not in {"date", "source", "status", "ay", "score"} and data[c].notna().any()]
        presets = []
        if "tmin" in all_num:
            presets.append(("❄️ Frost Day — tmin below 0 °C", "tmin", "<", 0.0))
        if "tmax" in all_num:
            presets.append(("🔥 Hot Day — tmax at or above 30 °C", "tmax", ">=", 30.0))
        if "tmean" in all_num:
            presets.append(("🧊 Freezing Day — tmean below 0 °C", "tmean", "<", 0.0))
        presets.append(("✏️ Custom Rule", None, None, None))

        a_col, b_col = st.columns([2, 1])
        choice = a_col.selectbox("Decision Rule", range(len(presets)), format_func=lambda i: presets[i][0])
        scope = b_col.radio("Period", ["Selected Month", "All 80 Months"], horizontal=True)
        _, var_t, op_t, thr_t = presets[choice]
        if var_t is None:
            x1, x2, x3 = st.columns(3)
            var_t = x1.selectbox("Variable", all_num, key="thr_var")
            op_lbl = x2.selectbox("Condition", ["below (<)", "at or above (≥)"], key="thr_op")
            op_t = "<" if op_lbl.startswith("below") else ">="
            thr_t = x3.number_input("Threshold", value=0.0, step=0.5, key="thr_val")

        scope_m = month if scope == "Selected Month" else None
        rec, days = threshold_eval_cached(_mtime(CSV_PATH), scope_m, var_t, op_t, float(thr_t))
        sym = "<" if op_t == "<" else "≥"

        if rec.empty:
            st.warning("No numeric values for this variable in the selected period.")
        else:
            n_days = len(days)
            n_dis = int(days.disagree.sum())
            n_dis_flag = int((days.disagree & days.flagged).sum())
            n_any = int((days.yes > 0).sum())
            k1, k2, k3, k4 = st.columns(4)
            card(k1, "Days Checked", n_days, note=f"rule: {var_t} {sym} {thr_t:g}", accent=CYAN)
            card(k2, "Rule Met (Any Source)", n_any, EMERALD, "days", accent=EMERALD)
            card(k3, "Sources Disagree", n_dis, AMBER,
                 f"{(n_dis / n_days * 100 if n_days else 0):.1f}% of days", accent=AMBER)
            card(k4, "Disagreement Flagged", f"{n_dis_flag}/{n_dis}", CRIMSON,
                 "marked Review / Quarantined", accent=CRIMSON)

            st.markdown(f"### Rule Result per Day and Source ({var_t} {sym} {thr_t:g})")
            rec = rec.assign(Result=rec.crossed.map({True: "Rule met", False: "Not met"}))
            fig_t = px.scatter(
                rec, x="date", y="source", color="Result",
                color_discrete_map={"Rule met": EMERALD, "Not met": "#475569"},
                hover_data={var_t: ":.2f", "score": True, "status": True},
                labels={"date": "Date", "source": ""},
            )
            fig_t.update_traces(marker=dict(symbol="square", size=10 if scope_m is None else 15, line=dict(width=0)))
            dis_dates = list(days.index[days.disagree])
            if len(dis_dates) <= 60:
                for dt in dis_dates:
                    t0 = pd.Timestamp(dt)
                    fig_t.add_vrect(
                        x0=t0 - pd.Timedelta(hours=12), x1=t0 + pd.Timedelta(hours=12),
                        fillcolor=AMBER, opacity=0.22, line_width=0, layer="below",
                    )
            show_fig(style_fig(fig_t, 270))

            if n_dis:
                st.markdown("### Days Where Sources Disagree")
                dis_tbl = rec[rec.date.isin(dis_dates)][["date", "source", var_t, "Result", "score", "status"]]
                show_table(dis_tbl.rename(columns={
                    "date": "Date", "source": "Source", "score": "Score", "status": "Status",
                }))
            else:
                st.success("All sources give the same answer on every day for this rule.")


@st.fragment
def render_blockchain_group(city: str, month: str):
    raw_all = load_raw_strings()
    m_raw = raw_all[raw_all.ay == month].reset_index(drop=True)
    view = sub_nav(
        "Blockchain Section",
        ["🔗 Verify Record & Tamper Test", "📜 Monthly Seal Registry (80 Months)"],
        key="nav_chain",
    )

    if view == "🔗 Verify Record & Tamper Test":
        st.markdown("### On-Chain Merkle Verification & Interactive Tamper Test")
        st.caption(
            "Verify any single daily record against the monthly Merkle root stored in EcoProveRegistry on Ethereum Sepolia. "
            "Read-only view call — free, no wallet required."
        )

        step("Step 1 · Pick a Record")
        labels = [
            f"{r.date} · {r.source} · Tmean {r.tmean + ' °C' if r.tmean != '' else '—'} · "
            f"Score {r.score if r.score != '' else '—'} · {r.status}"
            for r in m_raw.itertuples()
        ]
        idx = st.selectbox("Record", range(len(m_raw)), format_func=lambda i: labels[i])
        row = m_raw.iloc[idx]

        # Clear saved verification result if user switched city, month, or record
        current_key = (city, month, int(idx))
        if st.session_state.get("verify_key") != current_key:
            st.session_state["verify_key"] = current_key
            st.session_state.pop("verify_result", None)
            st.session_state.pop("tamper_result", None)

        leaves = month_leaves(month)
        leaf = leaves[idx]
        proof = kanit(leaves, idx)
        local_root = kok(leaves)

        with st.expander("🔍 Technical Details (Leaf String, Keccak256 Hash & Merkle Proof)"):
            st.code(
                f"leaf text : {row.date}|{row.source}|{row.tmean}|{row.score}|{row.status}\n"
                f"leaf      : {hx(leaf)}\n"
                f"local root: {hx(local_root)}\n"
                f"proof ({len(proof)} sibling hashes):\n" + "\n".join(hx(p) for p in proof)
            )
            proof_doc = {
                "network": "Ethereum Sepolia (chainId 11155111)",
                "contract": CONTRACT,
                "function": "verify(string city, string period, bytes32 leaf, bytes32[] proof)",
                "city": city,
                "period": month,
                "leaf_text": f"{row.date}|{row.source}|{row.tmean}|{row.score}|{row.status}",
                "leaf_hash": "keccak256(leaf_text)",
                "leaf": hx(leaf),
                "proof": [hx(p) for p in proof],
                "local_root": hx(local_root),
            }
            st.download_button(
                "⬇️ Download Standalone Proof (JSON)",
                json.dumps(proof_doc, indent=2) if "json" in globals() else __import__("json").dumps(proof_doc, indent=2),
                file_name=f"proof_{row.date}_{row.source}.json",
                mime="application/json",
            )

        step("Step 2 · Verify Original Record on Chain")
        if st.button("🔗 Verify on Chain", type="primary"):
            try:
                with st.spinner("Querying EcoProveRegistry on Ethereum Sepolia..."):
                    chain_root, count, ts = read_root(city, month)
                    ok = verify_on_chain(city, month, leaf, proof)
                when = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                st.session_state["verify_result"] = {
                    "ok": ok,
                    "count": count,
                    "when": when,
                    "chain_root": hx(chain_root),
                    "match": chain_root == local_root,
                }
            except Exception as e:
                st.session_state["verify_result"] = {"error": chain_error_text(e)}

        vres = st.session_state.get("verify_result")
        if vres:
            if "error" in vres:
                if vres["error"] == "not_found":
                    st.warning(f"No fingerprint on chain yet for **{city} / {month}**.")
                else:
                    st.error(vres["error"])
            else:
                if vres["ok"]:
                    result_box(True, "✅ Verified on Ethereum Sepolia",
                               "This record is bit-for-bit identical to the data sealed on-chain.")
                else:
                    result_box(False, "❌ Not Verified",
                               "This record does not match the sealed monthly Merkle root.")
                r1, r2, r3 = st.columns(3)
                card(r1, "Sealed Records", vres["count"], note=f"{city} / {month}", accent=CYAN)
                card(r2, "Sealed Timestamp", vres["when"].split(" ")[0], note=vres["when"].split(" ", 1)[1], accent=CYAN)
                card(r3, "Root Match", "Yes" if vres["match"] else "No",
                     EMERALD if vres["match"] else CRIMSON, "local = on-chain",
                     accent=EMERALD if vres["match"] else CRIMSON)
                st.caption(f"On-chain Merkle Root: `{vres['chain_root']}`")

        step("Step 3 · Interactive Tamper Test")
        st.caption("Modify any field below by even 0.1 °C. The record's keccak256 leaf changes and the smart contract rejects the proof.")
        c1, c2, c3 = st.columns(3)
        new_tmean = c1.text_input("Tmean (°C)", value=str(row.tmean))
        new_score = c2.text_input("Score", value=str(row.score))
        new_status = c3.selectbox("Status", STATUS_ORDER, index=STATUS_ORDER.index(row.status) if row.status in STATUS_ORDER else 0)
        fake_leaf = leaf_from_values(row.date, row.source, new_tmean, new_score, new_status)
        if fake_leaf != leaf:
            st.caption(f"✏️ Tampered leaf hash: `{hx(fake_leaf)}`")
        else:
            st.caption("Edit a value above to simulate post-publication tampering.")

        if st.button("🧪 Verify Changed Record"):
            try:
                with st.spinner("Sending tampered leaf with original Merkle proof to Sepolia..."):
                    ok_fake = verify_on_chain(city, month, fake_leaf, proof)
                st.session_state["tamper_result"] = {"ok": ok_fake}
            except Exception as e:
                st.session_state["tamper_result"] = {"error": chain_error_text(e)}

        tres = st.session_state.get("tamper_result")
        if tres:
            if "error" in tres:
                if tres["error"] == "not_found":
                    st.warning(f"No fingerprint on chain yet for **{city} / {month}**.")
                else:
                    st.error(tres["error"])
            elif tres["ok"]:
                result_box(True, "✅ Verified", "No values were altered.")
            else:
                result_box(False, "❌ Not Verified — Tampering Detected",
                           "The record was modified after sealing. EcoProveRegistry rejected the proof.")

    else:
        st.markdown("### Seal Registry — Audit All 80 Monthly Merkle Roots")
        st.caption(
            f"Rebuilds all 80 monthly Merkle roots (`2020-01` to `2026-08`) locally and compares them in parallel "
            f"against the smart contract under city label **{city}**."
        )

        if st.button("🔄 Check All 80 Months on Chain", type="primary"):
            with st.spinner(f"Querying Ethereum Sepolia for all 80 months ({city})..."):
                st.session_state["registry_data"] = (city, fetch_registry(city))

        saved = st.session_state.get("registry_data")
        if saved and saved[0] == city:
            reg = saved[1]
            n_total = len(reg)
            n_match = int(reg["On-Chain Status"].str.startswith("✅").sum())
            n_diff = int(reg["On-Chain Status"].str.startswith("⚠️").sum())
            n_wait = int(reg["On-Chain Status"].str.startswith("⏳").sum())
            g1, g2, g3, g4 = st.columns(4)
            card(g1, "Months in Dataset", n_total, accent=CYAN)
            card(g2, "Sealed & Matching", n_match, EMERALD, accent=EMERALD)
            card(g3, "Different Data", n_diff, CRIMSON, accent=CRIMSON)
            card(g4, "Not Sealed Yet", n_wait, AMBER, accent=AMBER)
            st.progress(n_match / n_total if n_total else 0.0,
                        text=f"{n_match} of {n_total} months sealed and matching on Ethereum Sepolia")
            show_table(reg)
        else:
            st.info("Click **Check All 80 Months on Chain** to query the smart contract in parallel (free, read-only).")


def render_about():
    st.markdown("### System Overview & Navigation")
    st.markdown("""
| Section | What You Can Do |
|---|---|
| 📊 **Overview & Sources** | Inspect monthly KPIs, daily reliability scores, status heatmaps, side-by-side source spreads, and 80-month source trust rankings. |
| 🧠 **AI & Benchmarks** | Compare walk-forward LightGBM forecasts against actual temperatures (2023–2026), explore the 46-record Quarantine Archive, and test decision thresholds. |
| 🔗 **Blockchain & Seals** | Verify any single daily record against Ethereum Sepolia, run a live Tamper Test, and audit all 80 sealed monthly Merkle roots. |
""")
    st.markdown("### Methodology & Scoring Formula (v1)")
    st.markdown("""
- **Data Collection & Alignment (2020–2026):** Daily mean temperature for Ankara, Türkiye from **NASA POWER** (~1128 m), **Open-Meteo ERA5** (~883 m, reference series), and **NOAA GHCN-Daily** (Ankara Central Station, 891 m). Silent station days are never deleted — they remain in the calendar as `Missing` (27 missing station records across 2020–2026, including 7 consecutive days in late March / early April 2026).
- **Training vs Walk-Forward Test Split:** `2020–2022` serves as the initial reference baseline for monthly elevation bias and LightGBM quantile models without data leakage, followed by walk-forward expansion (`2023` trained on `2020–2022`, `2024` on `2020–2023`, `2025` on `2020–2024`, `2026` on `2020–2025`). All **80 months (`2020-01` through `2026-08`, 7,305 records)** are scored and sealed on-chain.
- **Penalty & Reliability Score (0–100):**
  $$z_{\\text{eff}} = z_{\\text{cross}} + z_{\\text{interval}} + 3 \\times \\text{repeat}$$
  where $z_{\\text{cross}}$ is cross-source deviation after monthly elevation-bias correction, $z_{\\text{interval}}$ is distance outside the LightGBM 90% expected band, and $\\text{repeat}$ flags a stuck sensor (3 identical consecutive days).
- **Operational Decisions (by $z_{\\text{eff}}$ threshold):** `Trusted` ($z_{\\text{eff}} \\le 3$, score 84–100) · `Review` ($3 < z_{\\text{eff}} \\le 6$, score 50–84) · `Quarantined` ($z_{\\text{eff}} > 6$, score 0–49, archived with reason) · `Missing` (station silent).
""")

    st.markdown("### Target Use Cases")
    u1, u2, u3 = st.columns(3)
    card(u1, "Crop Insurance", "🌾", note="Weather-index insurance pays when a threshold is crossed (frost, heat). Insurers and farmers can verify whether payout days are backed by high-reliability consensus data.", accent=EMERALD)
    card(u2, "Energy Planning", "☀️", note="Solar and wind planners can filter out Quarantined or sensor-drift days when building generation models.", accent=CYAN)
    card(u3, "Climate Auditing", "📄", note="Municipalities and ESG auditors can cryptographically verify that historical climate reports were not altered after publication.", accent=AMBER)

    st.markdown("### Honest System Boundaries")
    st.markdown("""
- Blockchain sealing proves a record **was not changed** after sealing; it does **not** prove a physical thermometer was calibrated accurately.
- Multi-source cross-checking and LightGBM interval scoring run off-chain in Python; `EcoProveRegistry.sol` seals the resulting monthly Merkle roots on Ethereum Sepolia.
- Reanalysis products (NASA POWER, ERA5) share upstream satellite assimilation inputs and are not 100% statistically independent.
""")
    st.markdown(f"### On-Chain Contract\n- Ethereum Sepolia Etherscan: [{CONTRACT}]({ETHERSCAN_ADDR})")


# ===================================================================== Main UI
st.set_page_config(page_title="EcoProve AI", page_icon="🌍", layout="wide")

if not CSV_PATH.exists():
    st.error(f"Data file not found: {CSV_PATH}")
    st.stop()

data = load_data()
months = sorted(data.ay.unique())
years = sorted({m_str[:4] for m_str in months})

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown(
        '<div class="brand">🌍 <span>EcoProve AI</span></div>'
        '<div class="brand-sub">Trust Layer for Climate Data · Ankara, Türkiye</div>',
        unsafe_allow_html=True,
    )
    sub_nav("Theme", ["🌙 Dark", "☀️ Light"], key="theme_mode")
    default_yr = "2023" if "2023" in years else years[-1]
    sy1, sy2 = st.columns(2)
    sel_yr = sy1.selectbox("Year", years, index=years.index(default_yr))
    avail_m = [m_str[5:7] for m_str in months if m_str.startswith(sel_yr)]
    sel_mo = sy2.selectbox("Month", avail_m, index=0)
    month = f"{sel_yr}-{sel_mo}"

    city = st.selectbox("City Label on Chain", CITY_LABELS, help=TIP["city"])

    blk = latest_block()
    dot_cls = "dot" if blk else "dot off"
    blk_txt = f"Chain ID 11155111 · Block #{blk:,}" if blk else "Sepolia RPC unreachable"
    st.markdown(
        f"""
<div class="net">
  <div class="net-title">Live Network Status</div>
  <div class="net-row"><span class="{dot_cls}"></span>Ethereum Sepolia Testnet</div>
  <div class="net-sub">{blk_txt}</div>
  <a class="addr" href="{ETHERSCAN_ADDR}" target="_blank">📄 {CONTRACT[:10]}…{CONTRACT[-6:]} ↗</a>
</div>
""",
        unsafe_allow_html=True,
    )

st.markdown(build_css(_mtime(BG_IMAGE_PATH), is_light_mode()), unsafe_allow_html=True)

# --------------------------------------------------------------------- hero
st.markdown(
    """
<div class="hero">
  <div class="title">🌍 <span>EcoProve AI</span></div>
  <div class="sub">Multi-source climate data reliability scoring, leak-free LightGBM interval forecasting,
  and immutable monthly Merkle verification on Ethereum Sepolia.</div>
  <span class="pill">📡 3 Sources (NASA · ERA5 · NOAA)</span>
  <span class="pill">🧠 Walk-Forward LightGBM & Score 0–100</span>
  <span class="pill">🔗 80 Monthly Roots Sealed on Sepolia</span>
</div>
""",
    unsafe_allow_html=True,
)

t_ov, t_ai, t_ch, t_ab = st.tabs([
    "📊 Overview & Sources",
    "🧠 AI & Benchmarks",
    "🔗 Blockchain & Seals",
    "ℹ️ About & Limits",
])

with t_ov:
    render_overview_group(month)

with t_ai:
    render_ai_group(month)

with t_ch:
    render_blockchain_group(city, month)

with t_ab:
    render_about()
