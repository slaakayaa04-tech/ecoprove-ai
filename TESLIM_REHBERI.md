# 🌍 EcoProve AI — Yarışma Teslim Rehberi & Video Metni 

## 🎯 0. Biz Bu Hackathonda Hangi Soruna Çözüm Ürettik? (Özet Mantık)

**Hackathon Kategorimiz:** *Track 4 — Climate Data & Environmental Monitoring (İklim Verileri ve Çevresel İzleme)*

### 🔴 Çözdüğümüz 3 Katmanlı Temel Sorun:
İklim değişikliğiyle mücadelede **parametrik tarım sigortaları** ("Sıcaklık 0 °C'nin altına düştüyse çiftçiye don tazminatı öde"), **yenilenebilir enerji (güneş/rüzgâr) üretim planlaması** ve **belediye/kurum iklim raporlamaları** doğrudan günlük hava durumu verilerine dayanır. Ancak gerçek dünyada 3 büyük problem vardır:

1. **Kaynaklar Arası Çelişki (Hangi Veriye Güvenecekler?):**
   - Uydu/Reanaliz modelleri (**NASA POWER**, **Open-Meteo ERA5**) geniş alanları ızgara (grid) olarak tahmin ederken, yer istasyonları (**NOAA GHCN-Daily**) fiziksel sensörle noktasal ölçüm yapar.
   - Aynı gün aynı şehir (Ankara) için bir kaynak `-0.5 °C` (don var, sigorta ödemesi yapılmalı) derken diğeri `+0.6 °C` (don yok) diyebilir. Nitekim sadece 2023 yılında Ankara'da sıcaklığın sıfırın altına indiği **38 günün 13'ünde (%34'ünde)** kaynaklar birbiriyle çelişmiştir!
2. **Bozuk Sensör vs. Gerçek İklim Felaketi İkilemi (Veriyi Silmek Neden Tehlikeli?):**
   - Yer istasyonundaki bir sensör bozulup aniden `45.8 °C` gönderebilir, 5 gün aynı değerde takılı kalabilir veya bağlantısı kopup günlerce susabilir (NOAA Ankara istasyonunun 2026 Mart–Nisan'da **7 gün üst üste sustuğu** gibi).
   - Eğer uç değerleri *"kesin sensör hatasıdır"* diye otomatik silersek, **gerçek bir sıcak dalgasını veya iklim felaketini gözden kaçırırız**. Olduğu gibi kabul edersek **sahte alarmlar ve haksız sigorta ödemeleri** oluşur.
3. **Verinin Sonradan Sessizce Değiştirilebilmesi (Manipülasyon Riski):**
   - İklim verileri kurumlar arasında sıradan CSV/Excel dosyalarıyla paylaşılır. Bir sigorta ödemesi veya karbon/iklim raporu sonrasında dosyadaki bir sıcaklığın `0.5 °C` değiştirilip değiştirilmediğini kanıtlamanın kriptografik bir yolu yoktur.

### 🟢 EcoProve AI Bu Sorunu Nasıl Çözdü?
Biz "mutlak doğru sıcaklığı" iddia etmek yerine, ham iklim verisi ile karar vericiler arasına **Yapay Zekâ + Blokzincir tabanlı bağımsız bir Güven ve Kanıt Katmanı (Trust & Verification Layer)** kurduk:
- **Veriyi Asla Silmez:** Eksik günleri takvimde `Missing` olarak tutar; şüpheli veriyi silmek yerine gerekçesiyle `Quarantined` (Karantina) arşivine alır.
- **Yapay Zekâ ile Beklenen Aralığı Tahmin Eder (`LightGBM`):** Veri sızıntısı (data leakage) olmadan, sadece geçmiş yıllarla eğitilen Walk-Forward LightGBM modeliyle her gün için **%90 Beklenen Sıcaklık Bandı (`[q05, q95]`)** üretir (`1.33–1.39 °C` MAE).
- **Çok Kaynaklı Güvenilirlik Skoru (`0–100`) Verir:** Tek bir sensör `45.8 °C` gönderdiğinde diğer kaynaklarla uyuşmadığı için anında yakalayıp karantinaya alır (**Skor 0**, genel hata yakalamada **0.865 F1 skoru**); ama **gerçek bir sıcak dalgasında** üç kaynak birden yükseldiği için veriyi karantinaya atmaz (**%98.6+ koruma**)!
- **Blokzincire Mühürler (`Ethereum Sepolia Merkle Tree`):** Her günün kaydını tek tek zincire yazıp yüksek gas ücreti ödemek yerine, her ayın tüm kayıtlarını `keccak256` Merkle Ağacı ile **aylık tek bir 32-byte Merkle Köküne (`Root`)** dönüştürüp Sepolia üzerindeki `EcoProveRegistry.sol` akıllı sözleşmesine mühürler (**2020–2026 arası 80 ayın tamamı mühürlü**). İsteyen herkes cüzdan bile bağlamadan tek tıkla bir kaydın sonradan `0.1 °C` bile değiştirilmediğini doğrular!

---

## 🔗 1. Resmi Proje Linklerimiz (Herkese Açık / Public)

- **Canlı Web Sitesi (Prototip / Demo):** https://ecoprove-ai.streamlit.app
- **GitHub Kod Deposu (Her İkimizin Tüm Kodları + Belgeler):** https://github.com/slaakayaa04-tech/ecoprove-ai
- **Ethereum Sepolia Akıllı Sözleşme (80/80 Ay `Ankara` Mühürlü):** https://sepolia.etherscan.io/address/0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89

---

## 📝 2. Teslim Formuna Kopyala-Yapıştır Yapılacak Cevaplar

### A) Yol Haritası (Track / Selected Path)
```text
Track 4: Climate Data & Environmental Monitoring

How EcoProve AI addresses Track 4:
Climate-driven decisions (parametric crop insurance, frost/heatwave alerts, and renewable energy planning) depend on daily environmental measurements. However, satellite/reanalysis models (NASA POWER, ERA5) and ground stations (NOAA GHCN-Daily) frequently report conflicting numbers for the same city on the same day, or stations go silent. Deleting suspicious data risks hiding real climate disasters, while blindly accepting it causes false payouts—and CSV files can be silently edited afterwards.

EcoProve AI solves this by building an AI + Blockchain trust layer for Ankara (2020–2026, 80 months, 7,305 daily records):
1. Aligns 3 climate sources without deleting missing station days (27 Missing days explicitly tracked).
2. Predicts a leak-free 90% Expected Temperature Band using a walk-forward LightGBM quantile model (1.33–1.39 °C MAE across 2023–2026).
3. Computes a daily Reliability Score (0–100) and status (Trusted, Review, Quarantined) that achieves a 0.865 F1 score on injected sensor faults while preserving 98.6%+ of real multi-source heatwaves.
4. Seals monthly keccak256 Merkle roots on Ethereum Sepolia (80/80 months sealed) so anyone can verify any daily record or detect a 0.1 °C tamper in one click without a wallet.
```

### B) Proje Tanımı (Problem, Solution, Target Users, Scalability & Ease of Adoption)
```text
1. THE PROBLEM
Different climate sources often report different numbers for the same day: for example, in 2023 our three Ankara sources disagreed on whether the freezing threshold (< 0 °C) was crossed on 13 out of 38 sub-zero days. A broken sensor may spike to 45.8 °C or go silent for 7 days (as NOAA did in March–April 2026), while CSV spreadsheets can be altered retroactively without leaving a trace.

2. OUR SOLUTION
EcoProve AI never deletes suspicious or missing data. Instead, it:
- Predicts a 90% expected daily temperature interval [q05, q95] using a leak-free walk-forward LightGBM model trained strictly on historical lags and rolling averages.
- Scores every daily record (0–100) using z_eff = z_cross + z_interval + 3*repeat (combining elevation-bias-corrected cross-source deviation, LightGBM interval distance, and stuck-sensor detection) into Trusted (84–100), Review (50–83), Quarantined (0–49, archived with reason), or Missing.
- Hashes each record as keccak256(date|source|tmean|score|status) into a sorted-pair monthly Merkle tree and seals 1 root per city per month on our Ethereum Sepolia smart contract (EcoProveRegistry.sol).

3. TARGET USERS
- Parametric (Weather-Index) Crop Insurers & Farmers: Verify whether threshold-crossing days (frost < 0 °C, extreme heat >= 30 °C) are backed by high-reliability consensus data before triggering payouts.
- Renewable Energy Planners: Filter out Quarantined or sensor-drift days when modeling solar/wind generation.
- Climate & ESG Auditors: Cryptographically verify that historical climate reports were never edited after publication.

4. SCALABILITY & EASE OF ADOPTION
- O(1) Monthly Blockchain Cost: Sealing 1 Merkle root per city per month requires only 12 transactions/year per city regardless of whether there are 90 rows or 100,000 IoT sensor readings per month.
- Zero-Contract-Change Multi-City Expansion: Our smart contract indexes roots by keccak256(city, period), so adding new agricultural regions (Konya, Izmir, Adana, or global cities) requires zero Solidity changes.
- Zero-Wallet Public Verification: End users, farmers, and auditors verify records in our web app via free read-only RPC calls—no crypto wallet, gas, or browser extension needed. Standalone JSON Merkle proofs can also be downloaded for offline/Etherscan verification.
```

---

## 🎥 3. Demo Videosu (3 Dakikalık Ekran Kaydı + Konuşma Metni)

**Nasıl Çekilir?**
- Yüzünüzün (kameranın) görünmesine **gerek yoktur**.
- Zoom veya Windows Ekran Alıntısı Aracı ile ekranı (`https://ecoprove-ai.streamlit.app`) kaydederken aşağıdaki 5 paragrafı sırayla okuyup sekmelere tıklayın:

### ⏱️ Bölüm 1: Giriş — Üst Başlık Görünürken (0:00 – 0:40)
> "Hello! We are the EcoProve AI team, competing in Track 4: Climate Data and Environmental Monitoring.
> Climate decisions like parametric crop insurance and renewable energy planning depend on daily weather thresholds. However, satellite reanalysis models like NASA POWER and ERA5 often disagree with ground stations like NOAA, or sensors malfunction and go silent.
> EcoProve AI is a climate data trust layer for Ankara covering 80 months and 7,305 daily records from 2020 to 2026. Instead of deleting suspicious data, we predict a 90 percent expected band with LightGBM, give every daily record a Reliability Score from 0 to 100, and seal monthly Merkle roots on the Ethereum Sepolia blockchain."

### ⏱️ Bölüm 2: `📊 Overview` ve `🔀 Source Comparison` Sekmeleri (0:40 – 1:15)
> "In the Overview tab, we can select any of the 80 months from 2020 to 2026 in the sidebar. We see our KPI cards—Trusted, Review, Quarantined, and Missing station days—along with the daily reliability score curves and status heatmap.
> In the Source Comparison tab, we compare NASA POWER, Open-Meteo ERA5, and the NOAA ground station side by side, see their daily spread, and inspect any single day."

### ⏱️ Bölüm 3: `📈 AI Forecast vs Actual` Sekmesi (1:15 – 1:50)
> "In the AI Forecast vs Actual tab, we show our walk-forward LightGBM model with zero data leakage: 2023 is trained on data up to 2022, 2024 on data up to 2023, 2025 on data up to 2024, and 2026 on data up to 2025.
> The white line is the actual temperature, the gold line is our AI forecast, and the shaded area is our 90 percent expected band. In 2026, our model achieves a 1.39 degree MAE, beating both Persistence and Climatology baselines."

### ⏱️ Bölüm 4: `🧪 Fault Benchmark` ve `🎯 Threshold Check` Sekmeleri (1:50 – 2:30)
> "In the Fault Benchmark tab, we prove why we never blindly delete extreme values. When a single sensor spikes to 45.8 degrees, EcoProve catches the cross-source disagreement and quarantines it with score 0. But during a real plus-7-degree heatwave across all three sources, the records stay Trusted! Overall, EcoProve achieves a 0.865 F1 score compared to 0.148 for a simple threshold baseline, and archives all 46 quarantined fault records with their exact reason.
> In the Threshold Check tab, we also show how source disagreement flips freezing-day decisions below zero degrees Celsius."

### ⏱️ Bölüm 5: `🔗 Verify on Chain` ve `📜 Seal Registry` Sekmeleri (2:30 – 3:15)
*(Önce **Verify on Chain** butonuna basıp **✅ Verified** kutusunu gösterin. Sonra aşağıda **Step 3 · Tamper Test** kısmında sıcaklığı `1.74` yerine `2.74` yapıp **Verify Changed Record** butonuna basarak **❌ Not Verified — Tampering Detected** kutusunu gösterin. Son olarak **Seal Registry** sekmesinde **Check All Months on Chain** butonuna basın.)*
> "Finally, in the Verify on Chain tab, anyone can verify a single daily record against our EcoProveRegistry smart contract on Ethereum Sepolia—for free and without a wallet. Clicking Verify on Chain confirms the record matches the sealed monthly Merkle root.
> Now, in the Tamper Test below, if someone edits a temperature by just one degree and clicks Verify Changed Record, the leaf hash changes and the smart contract immediately rejects it: Not Verified — Tampering Detected!
> And in the Seal Registry tab, we can verify that all 80 monthly roots from 2020 to 2026 are sealed on-chain under Ankara. Thank you for watching!"
