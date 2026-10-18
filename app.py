"""EcoProve AI - Streamlit web app.

Reads the reliability score file, rebuilds the monthly Merkle trees
(same scheme as merkle_kok.py) and verifies records against the
EcoProveRegistry smart contract on Ethereum Sepolia (read-only, no wallet).

Run:  streamlit run app.py
"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from Crypto.Hash import keccak
from web3 import Web3

# ---------------------------------------------------------------- settings
CSV_PATH = "data/reliability_scores_v1.csv"
CONTRACT = "0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89"
RPC_URL = "https://ethereum-sepolia-rpc.publicnode.com"
ETHERSCAN_ADDR = f"https://sepolia.etherscan.io/address/{CONTRACT}"
CITY_LABELS = ["TEST", "Ankara"]  # TEST = trial roots, Ankara = final roots

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


# ===================================================================== UI
st.set_page_config(page_title="EcoProve AI", page_icon="🌍", layout="wide")

try:
    data = load_data()
except FileNotFoundError:
    st.error(f"Data file not found: {CSV_PATH}")
    st.stop()

months = sorted(data.ay.unique())

with st.sidebar:
    st.title("🌍 EcoProve AI")
    st.caption("Trust layer for climate data: reliability score + blockchain traceability.")
    month = st.selectbox("Month", months)
    city = st.selectbox("City label on chain", CITY_LABELS,
                        help="TEST = trial roots. Ankara = final roots.")
    st.markdown(f"**Network:** Ethereum Sepolia (testnet)  \n"
                f"**Contract:** [`{CONTRACT[:10]}…{CONTRACT[-6:]}`]({ETHERSCAN_ADDR})")

m = data[data.ay == month].reset_index(drop=True)
mn = numeric(m, ["score", "tmean"])

st.title("EcoProve AI — Ankara climate data trust layer")
st.write("We do not say a value is *right* or *wrong*. We show **how reliable** it is "
         "and prove that the record **was not changed** after it was sealed on the blockchain.")

tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "🔀 Source comparison",
                                  "🔗 Verify on chain", "ℹ️ About & limits"])

# ---------------------------------------------------------------- Overview
with tab1:
    counts = m.status.value_counts()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Records", len(m))
    c2.metric("Average score", f"{mn.score.mean():.1f}")
    c3.metric("OK", int(counts.get("OK", 0)))
    c4.metric("Review", int(counts.get("Review", 0)))
    c5.metric("Quarantine", int(counts.get("Quarantine", 0)))

    left, right = st.columns([1, 2])
    with left:
        st.subheader("Status")
        st.bar_chart(counts)
    with right:
        st.subheader("Daily reliability score (0-100)")
        st.line_chart(mn.pivot_table(index="date", columns="source", values="score"))

    st.subheader("Records")
    st.dataframe(m.drop(columns=["ay"]), use_container_width=True, hide_index=True)

# ------------------------------------------------------- Source comparison
with tab2:
    skip = {"date", "source", "status", "ay"}
    num_cols = [c for c in m.columns if c not in skip
                and pd.to_numeric(m[c], errors="coerce").notna().any()]
    default = num_cols.index("tmean") if "tmean" in num_cols else 0
    var = st.selectbox("Variable", num_cols, index=default)
    st.subheader(f"{var} — sources side by side ({month})")
    st.line_chart(numeric(m, [var]).pivot_table(index="date", columns="source", values=var))
    st.caption("When sources disagree on the same day, the reliability score goes down "
               "and the record can be marked Review or Quarantine.")

# --------------------------------------------------------- Verify on chain
with tab3:
    st.subheader("1) Pick a record")
    labels = [f"{r.date} | {r.source} | tmean={r.tmean} | score={r.score} | {r.status}"
              for r in m.itertuples()]
    idx = st.selectbox("Record", range(len(m)), format_func=lambda i: labels[i])
    row = m.iloc[idx]

    leaves = month_leaves(month)
    leaf = leaves[idx]
    proof = kanit(leaves, idx)
    local_root = kok(leaves)

    with st.expander("Technical details (leaf, proof, local root)"):
        st.code(f"leaf text : {row.date}|{row.source}|{row.tmean}|{row.score}|{row.status}\n"
                f"leaf      : {hx(leaf)}\n"
                f"local root: {hx(local_root)}\n"
                f"proof ({len(proof)} hashes):\n" + "\n".join(hx(p) for p in proof))

    st.subheader("2) Check it on the blockchain")
    if st.button("🔗 Verify on chain", type="primary"):
        try:
            chain_root, count, ts = read_root(city, month)
            ok = verify_on_chain(city, month, leaf, proof)
            when = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            st.write(f"Root on chain for **{city} / {month}**: `{hx(chain_root)}` "
                     f"({count} records, sealed {when})")
            if chain_root == local_root:
                st.write("✅ Local root = root on chain")
            else:
                st.write("⚠️ Local root is different from the root on chain "
                         "(the data file is not the one that was sealed).")
            if ok:
                st.success("VERIFIED ✅ This record is exactly the same as when it was sealed.")
            else:
                st.error("NOT VERIFIED ❌ This record does not match the sealed root.")
        except Exception as e:
            t = chain_error_text(e)
            if t == "not_found":
                st.warning(f"No root on chain yet for **{city} / {month}**. "
                           "Try another month or city label.")
            else:
                st.error(t)

    st.subheader("3) Tamper test — change a value and try again")
    st.caption("Change the value below. The leaf is computed again, the same proof is used. "
               "The blockchain should now say NOT VERIFIED.")
    c1, c2, c3 = st.columns(3)
    new_tmean = c1.text_input("tmean", value=str(row.tmean))
    new_score = c2.text_input("score", value=str(row.score))
    statuses = sorted(set(data.status.unique()) | {"OK", "Review", "Quarantine"})
    new_status = c3.selectbox("status", statuses, index=statuses.index(row.status))
    fake_leaf = leaf_from_values(row.date, row.source, new_tmean, new_score, new_status)
    changed = fake_leaf != leaf
    st.write("Changed leaf: " + (f"`{hx(fake_leaf)}`" if changed else "_(nothing changed yet)_"))

    if st.button("🧪 Verify changed record"):
        try:
            ok = verify_on_chain(city, month, fake_leaf, proof)
            if ok:
                st.success("VERIFIED ✅ (the value was not changed)")
            else:
                st.error("NOT VERIFIED ❌ The record was changed after sealing. "
                         "Tampering is detected.")
        except Exception as e:
            t = chain_error_text(e)
            if t == "not_found":
                st.warning(f"No root on chain yet for **{city} / {month}**.")
            else:
                st.error(t)

    st.markdown(f"Contract: [{CONTRACT}]({ETHERSCAN_ADDR}) · Calls are read-only "
                "(free, no wallet needed).")

# ------------------------------------------------------------ About/limits
with tab4:
    st.markdown(f"""
### How it works
1. **Data:** daily values for Ankara from three sources — ERA5 (Open-Meteo), NASA POWER (MERRA-2), NOAA GHCN-Daily station.
2. **Score:** agreement between sources + change over time + past reliability of the source → **Reliability Score (0-100)** and status **OK / Review / Quarantine**.
3. **Merkle tree:** each record becomes a keccak256 leaf: `date|source|tmean|score|status`. One Merkle root per month.
4. **Blockchain:** the monthly root is stored in the `EcoProveRegistry` contract on Ethereum Sepolia. Raw data is **not** stored on chain.
5. **Verify:** this site builds the proof locally and asks the contract `verify(...)`. A changed record gives **false**.

### Honest limits
- The blockchain proves a record **was not changed** after sealing. It does **not** prove the value is correct.
- Cross-checking is done by the **scoring code**; the blockchain only **seals** the result.
- Sources are not fully independent (reanalysis products also use observations).
- One city (Ankara), limited years.
- Testnet (Sepolia), not mainnet.

### Links
- Contract: [{CONTRACT}]({ETHERSCAN_ADDR})

_AI assistance: Claude (Anthropic) was used during development._
""")
