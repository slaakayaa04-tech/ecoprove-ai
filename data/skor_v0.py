"""EcoProve AI - Reliability Score v0 (PROTOTIP).
ecoprove_long.csv -> reliability_scores.csv
Bu surumde tahmin modeli YOK; 'beklenen deger' = bias duzeltilmis kaynaklarin medyani.
Esikler yer tutucudur, sahte hata testiyle kalibre edilecek."""
import pandas as pd, numpy as np

d = pd.read_csv("ecoprove_long.csv", parse_dates=["date"])
w = d.pivot(index="date", columns="source", values="tmean")
egitim = w.index.year <= 2022

# 1) bias duzeltme: her kaynagi 2020-2022'de ERA5'e gore hizala
ref = "OPEN_METEO_ERA5"
bias = {s: (w[s] - w[ref])[egitim].mean() for s in w.columns}
wc = w.copy()
for s in w.columns:
    wc[s] = w[s] - bias[s]

# 2) kaynaklar arasi uzlasi = duzeltilmis degerlerin medyani
uzlasi = wc.median(axis=1)
sapma = wc.sub(uzlasi, axis=0)

# 3) kaynak basina robust olcek (MAD, egitim donemi)
olcek = {s: 1.4826 * (sapma[s][egitim] - sapma[s][egitim].median()).abs().median()
         for s in w.columns}

rows = []
for s in w.columns:
    z = sapma[s].abs() / olcek[s]
    skor = (100 * np.exp(-(z ** 2) / 18)).round()
    for t in w.index:
        if np.isnan(w.loc[t, s]):
            rows.append((t.date(), s, "", "", "", "", "Missing"))
            continue
        sk = int(skor[t])
        durum = "Trusted" if sk >= 80 else ("Review" if sk >= 50 else "Quarantined")
        rows.append((t.date(), s, round(w.loc[t, s], 2), round(uzlasi[t], 2),
                     round(z[t], 2), sk, durum))

out = pd.DataFrame(rows, columns=["date", "source", "tmean", "expected", "z", "score", "status"])
out.to_csv("reliability_scores.csv", index=False)
print("Bias (ERA5'e gore):", {k: round(v, 2) for k, v in bias.items()})
print("Satir:", len(out))
print(out.status.value_counts().to_string())
