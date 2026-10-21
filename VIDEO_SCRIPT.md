# 🎬 EcoProve AI — 3–5 Minute Demo Video Script (Step-by-Step)

> **Target Length:** 3 min 30 sec – 4 min 30 sec  
> **What to Have Open in Chrome Before Recording:**
> 1. **Tab 1:** Live App — `https://ecoprove-ai.streamlit.app` (Sidebar set to `Month: 2023-01`, `City Label: TEST` — *or `Ankara` once final roots are sealed*)
> 2. **Tab 2:** Sepolia Etherscan Contract — `https://sepolia.etherscan.io/address/0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89`
> 3. **Tab 3:** GitHub Repository — `https://github.com/slaakayaa04-tech/ecoprove-ai` (showing the Mermaid architecture diagram)

---

## ⏱️ Scene 1: The Problem & Why It Matters (0:00 – 0:45)
**Screen:** Show `https://ecoprove-ai.streamlit.app` Hero Banner & the 4-step pipeline (`1. Collect → 2. Score → 3. Seal → 4. Verify`).

**What to Say (Simple English):**
> "Hello! We are the EcoProve AI team, competing in Track 4: Climate Data & Environmental Monitoring.
> Climate decisions—like parametric crop insurance payouts and solar or wind energy planning—depend on daily weather thresholds, such as whether the temperature dropped below zero degrees Celsius.
> But when we collect data for the same city and the same day from different sources—ERA5 reanalysis, NASA POWER satellite data, and a NOAA ground weather station—they often report different numbers.
> EcoProve AI does not claim which thermometer is physically right. Instead, it is a **climate data trust layer**: it scores how reliable each daily reading is from 0 to 100, and seals the monthly fingerprint on the Ethereum Sepolia blockchain so nobody can secretly edit climate records afterwards."

---

## ⏱️ Scene 2: Live Dashboard — Overview & Source Disagreement (0:45 – 1:40)
**Screen:**
1. Scroll down in **📊 Overview** tab: point to the 5 KPI cards (`Records`, `Avg Score`, `Trusted / OK`, `Review`, `Quarantine`) and the **Daily Reliability Score** Plotly curve.
2. Click **🔀 Source Comparison** tab: show the 3 lines side by side, the **Daily Disagreement (Spread)** bar chart, and the **Day Inspector** table.

**What to Say:**
> "In the Overview tab, we see 93 daily records for Ankara in January 2023 across our three sources, with an average reliability score of 91.5.
> When the three sources agree and change smoothly over time, records get a high score and are marked Trusted. When sources diverge, the score drops and the record is marked Review.
> Switching to the Source Comparison tab, we can see the daily temperature curves side by side, the daily spread between sources, and inspect any single day across all three providers."

---

## ⏱️ Scene 3: Real Climate Impact — Threshold Check & Source Trust (1:40 – 2:25)
**Screen:**
1. Click **🎯 Threshold Check** tab. Select **Period: All Months** (`🧊 Freezing Day — tmean below 0 °C`). Point to the **Sources Disagree (`13` days)** card and the table below.
2. Briefly click **🏆 Source Trust** tab to show the medal ranking (`🥇 NOAA_GHCN`, `🥈 OPEN_METEO_ERA5`, `🥉 NASA_POWER`).

**What to Say:**
> "Why does source disagreement matter in the real world? In our Threshold Check tab, we test a freezing-day rule—temperature below 0 degrees Celsius—across the whole year.
> Out of 365 days, at least one source reported freezing temperatures on 38 days. On 13 of those days, the sources disagreed: one source said Yes, another said No. For a weather-index insurance contract, that changes whether a farmer gets paid. EcoProve highlights those exact days and shows the reliability score of each source."

---

## ⏱️ Scene 4: Blockchain Verification & Live Tamper Test (2:25 – 3:30) ⭐ *KEY DEMO MOMENT*
**Screen:**
1. Click **🔗 Verify on Chain** tab.
2. Open **🔍 Technical Details** expander briefly to show the `keccak256` leaf and 7-hash Merkle proof.
3. Click **🔗 Verify on Chain** button → Show the green **`✅ Verified`** banner and `Root Match: Yes`.
4. Scroll to **Step 3 · Tamper Test**. Change `Tmean (°C)` from `1.74` to `2.74`.
5. Click **🧪 Verify Changed Record** → Show the red **`❌ Not Verified — Tampering Detected`** banner!
6. Click **📜 Seal Registry** tab and click **🔄 Check All Months on Chain**.

**What to Say:**
> "Instead of writing every row on-chain—which would be expensive—we group each month into a sorted-pair keccak256 Merkle tree and store only one root per city per month in our `EcoProveRegistry` smart contract on Ethereum Sepolia.
> In the Verify on Chain tab, any user or auditor can pick a record and click Verify on Chain—completely free and without needing a crypto wallet. The smart contract confirms our record is Verified and matches the on-chain root.
> Now let's try to cheat in the Tamper Test. If someone edits the temperature in the spreadsheet by just one degree and tries to verify again, the leaf fingerprint changes, and the Ethereum smart contract immediately rejects it: **Not Verified — Tampering Detected**.
> Moreover, our contract enforces write-once immutability: once a monthly root is stored, trying to overwrite it reverts with `already stored`."

---

## ⏱️ Scene 5: Architecture, Scalability & Honest Boundaries (3:30 – 4:10)
**Screen:** Switch to the **GitHub Repo tab** (`README.md` Mermaid diagram) and **Sepolia Etherscan tab** (`0x2b27fd49...`).

**What to Say:**
> "Our public GitHub repository includes our Solidity contract, 6 passing Hardhat unit tests, Python Merkle and sealing scripts, and full documentation.
> Because we seal one Merkle root per city per month, scaling to a new city requires only 12 transactions per year regardless of dataset size.
> Finally, we state our honest boundaries clearly: blockchain proves that data was not changed after sealing, while cross-checking and anomaly detection are performed off-chain by our scoring pipeline.
> Thank you for watching!"
