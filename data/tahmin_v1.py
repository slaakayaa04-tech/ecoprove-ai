"""EcoProve AI - Tahmin modeli v1
Eğitim: 2020-2022, Test: 2023 (model 2023'ü eğitimde HİÇ görmez).
Hedef: Ankara günlük ortalama sıcaklık (ERA5 serisi; eksiksiz olduğu için).
Her gün için "dünüme kadar bildiklerime göre bugün şu aralıkta olmalı" der.

Gereken: pandas numpy lightgbm matplotlib
"""
import numpy as np
import pandas as pd
import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------- 1) veri
d = pd.read_csv("ecoprove_long.csv", parse_dates=["date"])
s = d[d.source == "OPEN_METEO_ERA5"].set_index("date")["tmean"].sort_index()
assert s.notna().all(), "ERA5 serisinde eksik gün var"

egitim_son, test_yil = 2022, 2023

# ---------------------------------------------------------------- 2) özellikler
# KURAL: sadece geçmişi kullan (shift). Aynı günün başka kaynak değerleri YOK.
df = pd.DataFrame({"y": s})
for g in [1, 2, 3, 7]:
    df[f"lag{g}"] = s.shift(g)
df["ort7"] = s.shift(1).rolling(7).mean()
df["ort30"] = s.shift(1).rolling(30).mean()
doy = df.index.dayofyear
df["sin"] = np.sin(2 * np.pi * doy / 365.25)
df["cos"] = np.cos(2 * np.pi * doy / 365.25)

# iklimatoloji: eğitim yıllarında aynı günün (±7 gün) ortalaması
tr_s = s[s.index.year <= egitim_son]
tr_doy = tr_s.index.dayofyear.values
def iklim(gun):
    fark = np.abs(tr_doy - gun)
    fark = np.minimum(fark, 365 - fark)
    return tr_s.values[fark <= 7].mean()
tablo = {g: iklim(g) for g in range(1, 367)}
df["iklim"] = [tablo[g] for g in doy]

df = df.dropna()
tr = df[df.index.year <= egitim_son]
te = df[df.index.year == test_yil]
X = [c for c in df.columns if c != "y"]

# ---------------------------------------------------------------- 3) baseline'lar
tahmin = pd.DataFrame({"gercek": te.y})
tahmin["persistence"] = te.lag1          # dünkü değer
tahmin["iklimatoloji"] = te.iklim        # o günün çok yıllık ortalaması

# ---------------------------------------------------------------- 4) LightGBM
# Model sıcaklığın kendisini değil, "dünden ne kadar değişecek" farkını öğrenir (y - lag1).
# Sonra tahmin = dün + öğrenilen fark. Bu, gün-gün sıcaklıkta persistence'ı geçmek için daha kolay yol.
ortak = dict(n_estimators=300, learning_rate=0.03, num_leaves=8,
             min_child_samples=20, subsample=0.8, subsample_freq=1,
             colsample_bytree=0.8, random_state=42, verbose=-1)
orta = lgb.LGBMRegressor(objective="regression", **ortak).fit(tr[X], tr.y - tr.lag1)
alt = lgb.LGBMRegressor(objective="quantile", alpha=0.05, **ortak).fit(tr[X], tr.y - tr.lag1)
ust = lgb.LGBMRegressor(objective="quantile", alpha=0.95, **ortak).fit(tr[X], tr.y - tr.lag1)
tahmin["lightgbm"] = te.lag1 + orta.predict(te[X])
tahmin["alt"] = te.lag1 + alt.predict(te[X])
tahmin["ust"] = te.lag1 + ust.predict(te[X])
tahmin["alt"] = np.minimum(tahmin.alt, tahmin.lightgbm)   # aralık tahmini içermeli
tahmin["ust"] = np.maximum(tahmin.ust, tahmin.lightgbm)

# ---------------------------------------------------------------- 5) sonuçlar
def mae(a, b): return float(np.mean(np.abs(a - b)))
def rmse(a, b): return float(np.sqrt(np.mean((a - b) ** 2)))
print("=== 2023 TEST SONUÇLARI (365 gün) ===")
for m in ["persistence", "iklimatoloji", "lightgbm"]:
    print(f"{m:13s} MAE={mae(tahmin.gercek, tahmin[m]):.2f}  RMSE={rmse(tahmin.gercek, tahmin[m]):.2f}")

icinde = (tahmin.gercek >= tahmin.alt) & (tahmin.gercek <= tahmin.ust)
tahmin["aralik_icinde"] = icinde
print(f"\n%90'lık aralık: 2023 günlerinin %{100*icinde.mean():.1f}'i aralık içinde (hedef ≈ 90)")
print(f"Ortalama aralık genişliği: {(tahmin.ust - tahmin.alt).mean():.2f} °C")

sicak = tahmin[tahmin.gercek >= tahmin.gercek.quantile(0.95)]
print(f"\nEn sıcak %5 gün (n={len(sicak)}): ortalama hata (gerçek - tahmin) = "
      f"{(sicak.gercek - sicak.lightgbm).mean():+.2f} °C, aralık içinde %{100*sicak.aralik_icinde.mean():.0f}")

tahmin.round(2).to_csv("tahmin_2023.csv", index_label="date")

# ---------------------------------------------------------------- 6) grafik
fig, ax = plt.subplots(figsize=(13, 4.5))
ax.fill_between(tahmin.index, tahmin.alt, tahmin.ust, color="#2a9d8f", alpha=0.25, label="%90 beklenen aralık")
ax.plot(tahmin.index, tahmin.lightgbm, color="#264653", lw=1, label="LightGBM tahmini")
ax.plot(tahmin.index, tahmin.gercek, color="black", lw=0.8, label="Gerçek (2023)")
dis = tahmin[~tahmin.aralik_icinde]
ax.scatter(dis.index, dis.gercek, color="red", s=14, zorder=3, label="Aralık dışı")
ax.set_ylabel("Günlük ortalama sıcaklık (°C)")
ax.set_title("Ankara 2023 — test yılı (model eğitimde görmedi)")
ax.legend(loc="upper left", ncol=2)
plt.tight_layout()
plt.savefig("tahmin_2023.png", dpi=120)
print("\nKaydedildi: tahmin_2023.csv, tahmin_2023.png")
