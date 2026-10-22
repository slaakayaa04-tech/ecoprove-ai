"""EcoProve AI - 2024, 2025 ve 2026 yılları için güvenilirlik skorlarını ve Merkle köklerini hesaplar.
ÖNEMLİ KURAL: 2023 dosyalarına DOKUNULMAZ.
Çıktılar:
  - reliability_scores_2024_2026.csv
  - merkle_roots_2024_2026.csv
  - merkle_kanitlari_2024_2026.csv
"""
import numpy as np
import pandas as pd
from eth_hash.auto import keccak

REF = "OPEN_METEO_ERA5"
T_REVIEW, T_QUAR = 3.0, 6.0

def k(b):
    return keccak(b)

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

def durum(z):
    return "Quarantined" if z > T_QUAR else ("Review" if z > T_REVIEW else "Trusted")

def puan(z):
    return int(round(100 * 2 ** (-(z / T_QUAR) ** 2)))

d = pd.read_csv("ecoprove_long_2026.csv", parse_dates=["date"])
w = d.pivot(index="date", columns="source", values="tmean")
fc = pd.read_csv("tahmin_yillik_2026.csv", parse_dates=["date"]).set_index("date")

# Yıllık skor üretimi
rows = []
for yil in [2024, 2025, 2026]:
    egitim = w.index.year < yil
    test = w.index[w.index.year == yil]
    
    # Her yıl için bias ve sapma o yıla kadar olan eğitim geçmişiyle hesaplanır
    bias_ay = {s: (w[s] - w[REF])[egitim].groupby(w.index[egitim].month).mean() for s in w.columns}
    
    w_d = w.copy()
    for s in w.columns:
        w_d[s] = w[s] - w.index.month.map(bias_ay[s]).to_numpy()
    
    ref_sap = w_d.sub(w_d.median(axis=1), axis=0)
    olcek = {s: ref_sap[s][egitim].std() for s in w.columns}
    
    sap = w_d.sub(w_d.median(axis=1), axis=0)
    alt, ust = fc.loc[test, "alt"], fc.loc[test, "ust"]
    yari = (ust - alt) / 2
    
    for t in test:
        for s in w.columns:
            v = w.loc[t, s]
            if np.isnan(v):
                rows.append((t.strftime("%Y-%m-%d"), s, "", round(alt[t], 2), round(ust[t], 2), "", "", "Missing"))
            else:
                z_cross = abs(sap.loc[t, s]) / olcek[s]
                disari = (max(alt[t] - w_d.loc[t, s], 0) + max(w_d.loc[t, s] - ust[t], 0)) / yari[t]
                v1 = w[s].shift(1).loc[t] if t in w[s].shift(1).index else np.nan
                v2 = w[s].shift(2).loc[t] if t in w[s].shift(2).index else np.nan
                tekrar = (abs(v - v1) < 1e-9) and (abs(v1 - v2) < 1e-9) if (pd.notna(v1) and pd.notna(v2)) else False
                z_eff = z_cross + 1.0 * disari + (3.0 if tekrar else 0.0)
                rows.append((t.strftime("%Y-%m-%d"), s, round(v, 2), round(alt[t], 2), round(ust[t], 2),
                             round(z_eff, 2), puan(z_eff), durum(z_eff)))

out = pd.DataFrame(rows, columns=["date", "source", "tmean", "expected_low", "expected_high",
                                  "z_eff", "score", "status"])
out.to_csv("reliability_scores_2024_2026.csv", index=False)

print("=== SKORLAR (2024-2026) ===")
print("Toplam satır:", len(out))
print(out.status.value_counts().to_string())

# Merkle kökleri ve kanıtları
out_sort = out.sort_values(["date", "source"]).reset_index(drop=True)
out_sort["ay"] = out_sort.date.str[:7]

def yaprak_metni(r):
    return f"{r.date}|{r.source}|{r.tmean}|{r.score}|{r.status}"

satirlar, kokler = [], []
for ay, g in out_sort.groupby("ay"):
    metinler = [yaprak_metni(r) for r in g.itertuples()]
    yapraklar = [k(m.encode("utf-8")) for m in metinler]
    root = "0x" + kok(yapraklar[:]).hex()
    kokler.append((ay, root, len(yapraklar)))
    for i, r in enumerate(g.itertuples()):
        satirlar.append((r.date, r.source, ay, metinler[i], "0x" + yapraklar[i].hex(),
                         ";".join("0x" + e.hex() for e in kanit(yapraklar, i)), root))

df_kanit = pd.DataFrame(satirlar, columns=["date", "source", "ay", "leaf_text", "leaf_hash", "proof", "root"])
df_kanit.to_csv("merkle_kanitlari_2024_2026.csv", index=False)
df_kok = pd.DataFrame(kokler, columns=["ay", "root", "count"])
df_kok.to_csv("merkle_roots_2024_2026.csv", index=False)

print(f"\nOluşturulan Ay Sayısı: {len(kokler)} (Beklenen: 12 + 12 + 8 = 32 ay)")
print(df_kok.to_string(index=False))
