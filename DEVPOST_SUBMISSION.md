# 🌍 EcoProve AI — Devpost Submission & Deliverables Document

> **Track:** Track 4 — Climate Data & Environmental Monitoring  
> **Live Web App:** [https://ecoprove-ai.streamlit.app](https://ecoprove-ai.streamlit.app)  
> **Public GitHub Repository:** [https://github.com/slaakayaa04-tech/ecoprove-ai](https://github.com/slaakayaa04-tech/ecoprove-ai)  
> **Smart Contract (Ethereum Sepolia):** [`0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89`](https://sepolia.etherscan.io/address/0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89)

---

## 1. Elevator Pitch (Short Tagline for Devpost)
A climate data trust layer that scores daily multi-source weather reliability (0–100) and seals monthly Merkle roots on Ethereum Sepolia so anyone can verify records were never altered.

---

## 2. Problem Statement (Max 2 Pages)

### The Hidden Fragility in Climate-Driven Decisions
Climate action, renewable energy operations, and agricultural risk management depend on daily environmental measurements. However, organizations rarely rely on a single thermometer—they pull data from **reanalysis models (e.g., ERA5)**, **satellite-derived products (e.g., NASA POWER / MERRA-2)**, and **ground weather stations (e.g., NOAA GHCN-Daily)**.

In practice, these sources frequently report **different values for the same city on the same day**:
1. **Threshold Flipping Risk:** Many climate contracts and policies are binary. A **parametric (weather-index) crop insurance** policy triggers a payout if daily temperature drops below $0\,^\circ\text{C}$. If one data source reports $-0.5\,^\circ\text{C}$ and another reports $+0.4\,^\circ\text{C}$, the payout decision flips depending on which dataset is chosen.
2. **Silent Anomalies & Sensor Drift:** Ground stations experience temporary sensor faults or missing observations, while gridded satellite/reanalysis products smooth out local extremes. Using unverified rows directly in solar/wind forecasting or municipal climate reports introduces silent errors.
3. **Lack of Post-Publication Auditability:** Climate datasets are typically exchanged as CSV or Excel files. Once a dataset is used to justify an insurance payout, a carbon/climate disclosure, or an energy forecast, third-party auditors have no cryptographic way to verify that a single row was not edited retroactively.

### What EcoProve AI Solves
EcoProve AI does **not** claim to declare physical "truth." Instead, it builds a **transparent trust and integrity layer** between raw climate feeds and downstream decision-makers:
- It quantifies **how reliable** each daily record is (`0–100` Reliability Score) and assigns an operational status (`Trusted / OK`, `Review`, or `Quarantine`).
- It anchors monthly batches of scored records on the **Ethereum Sepolia blockchain** using **keccak256 Merkle roots**, making any subsequent tampering immediately detectable by anyone—for free and without requiring a crypto wallet.

---

## 3. Climate Impact Assessment (Evidence from Ankara Dataset)

EcoProve AI improves the **decision quality and auditability** of climate adaptation and clean-energy workflows rather than claiming direct physical carbon removal.

### Quantitative Findings on Ankara Multi-Source Data (`ERA5`, `NASA POWER`, `NOAA GHCN-Daily`)
- **Dataset Coverage (2020–2026):** `2020–2022` serves as the leak-free training/reference period; **`4,017` scored daily records across `44` months (`2023-01` to `2026-08`)** are evaluated via walk-forward expansion and sealed into `44` monthly Merkle roots.
- **Reliability Distribution (2023–2026, 4,017 records):**
  - **Trusted Records (`84–100`):** `3,866` (`96.2%`) — sources agree and stay within the LightGBM 90% expected interval.
  - **Review Records (`50–83`):** `126` (`3.1%`) — noticeable inter-source divergence requiring verification before decision use.
  - **Quarantined Records (`0–49`):** `1` natural anomaly + synthetic fault test cases — archived with reason rather than silently deleted.
  - **Missing Station Days (`Missing`):** `24` records (`0.6%`) in `2024–2026` (plus `19` historical days in `2020–2022`), including **7 consecutive silent days at the NOAA Ankara station in late March / early April 2026**—kept explicitly in the calendar so station outages are never hidden.
- **Freezing Threshold Scenario ($T_{\text{mean}} < 0\,^\circ\text{C}$):**
  - In 2023 alone, at least one source reported sub-zero daily mean temperature on **`38` days**, and on **`13` of those days (`3.6%` of the year)** the three sources **disagreed** on whether the freezing threshold was crossed (one source said *Yes*, another said *No*).
  - Our interactive **🎯 Threshold Check** tab makes these disagreement days immediately visible so insurers, farmers, and energy planners can inspect the exact source scores before making a payout or modeling decision.
- **Fault Injection & Walk-Forward Forecasting Validation:**
  - **Synthetic Fault Injection Benchmark (`sahte_hata_ozet.csv` & `esik_duyarlilik.csv`):** Tested on `75` injected fault days (`±15 °C` sudden spikes, `°C/°F` unit errors, `5-day` stuck sensors, and `20-day` gradual sensor drift) plus `+7 °C` multi-source real heatwaves. EcoProve achieved **100% detection on spikes and unit errors**, **81.2% on stuck sensors**, **68.9% on gradual drift**, and an overall **F1 score of `0.817 – 0.865`** compared to **`0.148` F1** for a single-series Heston-style threshold baseline ($z > 2.5$)—while preserving **98.6%+ of real multi-source heatwaves** without false quarantine.
  - **Walk-Forward LightGBM Interval Forecast (`tahmin_yillik_ozet_2026.csv`):** Trained strictly on past years (`2024` on `2020–2023`, `2025` on `2020–2024`, `2026` on `2020–2025`), LightGBM achieved **`1.39 °C` MAE in 2026** (beating both Persistence `1.56 °C` and Climatology `2.58 °C`) with **`82.3%–87.7%` empirical coverage** on its 90% expected temperature band.

---

## 4. Technical Innovation: How AI + Blockchain Work Together

### Step 1 — Multi-Source Ingestion & Statistical / AI Scoring (Off-Chain)
For each day $t$ and source $s \in \{\text{ERA5}, \text{NASA POWER}, \text{NOAA}\}$, the scoring pipeline computes:
- Expected normal range (`expected_low`, `expected_high`) and effective deviation (`z_eff`) combining cross-source agreement, temporal consistency, and historical source reliability.
- A normalized **Reliability Score (`0–100`)** and status (`Trusted / OK`, `Review`, `Quarantine`).

### Step 2 — Monthly keccak256 Merkle Tree Construction (`merkle_kok.py`)
Writing every daily weather reading on-chain would waste gas and leak raw data structure. Instead:
- Each record becomes a deterministic leaf:
  $$\text{leaf} = \text{keccak256}(\texttt{"date|source|tmean|score|status"})$$
- Leaves are sorted by `(date, source)` and paired using **sorted-pair keccak256 hashing** ($\min(a,b) \parallel \max(a,b)$) to produce **one 32-byte Merkle root per city per month**.

### Step 3 — Immutable On-Chain Sealing (`EcoProveRegistry.sol` on Sepolia)
- The smart contract stores `(root, recordCount, timestamp)` keyed by `keccak256(city | period)`.
- **`storeRoot(city, period, root, count)`:** Restricted to `onlyOwner` and protected by `require(entries[key].timestamp == 0, "already stored")`—meaning once a month is sealed, **nobody (not even the owner) can overwrite it**.
- **`verify(city, period, leaf, proof)`:** A public, gas-free `view` function that recomputes the root from a single record's leaf and its Merkle proof ($\approx 7$ sibling hashes) and returns `true` or `false`.

### Step 4 — Zero-Wallet Verification & Live Tamper Test (`app.py`)
- Anyone visiting **[https://ecoprove-ai.streamlit.app](https://ecoprove-ai.streamlit.app)** can pick any daily record, click **Verify on Chain**, and query the live Ethereum Sepolia contract.
- In the **Tamper Test**, changing a temperature by even `0.1 °C` changes the leaf hash and causes the smart contract to immediately return **`❌ Not Verified — Tampering Detected`**.

---

## 5. Adoption Strategy & Scalability Roadmap

| Dimension | Why EcoProve Scales Easily |
|---|---|
| **On-Chain Cost (`O(1)` per month)** | Whether a city has 90 records/month or 100,000 IoT sensor records/month, it still requires **only 1 transaction per city per month** (12 tx/year). On Sepolia/L2s, sealing an entire year costs fractions of a cent. |
| **Adding New Cities** | The contract key is `city | period`. Adding İzmir, Konya, or 100 global agricultural regions requires **zero smart contract changes**. |
| **Adding New Data Sources** | New satellite or local IoT station feeds plug into the off-chain CSV schema (`date, source, ...`) as a single adapter function. |
| **Standalone Proof Portability** | Users can export a **JSON Merkle Proof** from our web app and verify it directly on Etherscan or any Web3 script—even if our website is offline. |

### Roadmap
1. **Phase 1 (Current Prototype):** Ankara multi-source daily temperature scoring + monthly Merkle sealing on Ethereum Sepolia + 7-tab verification web app.
2. **Phase 2 (Multi-City & Multi-Variable):** Expand leaf schema to precipitation, wind speed, and solar radiation across key agricultural zones (Konya, İzmir, Adana).
3. **Phase 3 (L2 Mainnet & Automated Oracles):** Deploy `EcoProveRegistry` on an Ethereum Layer-2 (Arbitrum / Base) with automated monthly cron sealing for parametric insurance and ESG auditing partners.

---

## 6. Honest System Boundaries

1. **Tamper-Evidence, Not Sensor Calibration:** Blockchain proves a record **was not altered after sealing**; it does not prove a physical thermometer was accurate.
2. **Off-Chain Scoring vs. On-Chain Sealing:** Cross-validation is performed by the Python scoring pipeline; the blockchain seals the result.
3. **Source Overlap:** Reanalysis datasets (ERA5, MERRA-2) assimilate surface observations, so sources are not 100% independent.
4. **AI Assistance Disclosure:** Claude (Anthropic) was used during development for code structuring and documentation.
