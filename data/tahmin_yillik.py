"""EcoProve AI - Yıllık ileri sarmalı (walk-forward) tahmin testi
Her test yılı için model SADECE o yıldan ÖNCEKİ yıllarla eğitilir:
  2022 testi <- 2020-2021 ile eğitim
  2023 testi <- 2020-2022 ile eğitim   (ana sonuçlarımız bu)
  2024 testi <- 2020-2023 ile eğitim
  2025 testi <- 2020-2024 ile eğitim
Test yılı hiçbir zaman eğitimde görülmez. Tüm yılları birleştirip aynı verilerde test etmek veri sızıntısı olurdu.

Gereken dosya: ecoprove_long.csv    Gereken paketler: pandas numpy lightgbm
Çıktılar: tahmin_yillik.csv (her gün için tahmin ve aralık), tahmin_yillik_ozet.csv
"""
import numpy as np
import pandas as pd
import lightgbm as lgb

d = pd.read_csv("ecoprove_long.csv", parse_dates=["date"])
s = d[d.source == "OPEN_METEO_ERA5"].set_index("date")["tmean"].sort_index()
assert s.notna().all()

ortak = dict(n_estimators=300, learning_rate=0.03, num_leaves=8, min_child_samples=20,
             subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=42, verbose=-1)


def ozellikler(seri, egitim_son):
    df = pd.DataFrame({"y": seri})
    for g in [1, 2, 3, 7]:
        df[f"lag{g}"] = seri.shift(g)
    df["ort7"] = seri.shift(1).rolling(7).mean()
    df["ort30"] = seri.shift(1).rolling(30).mean()
    doy = df.index.dayofyear
    df["sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["cos"] = np.cos(2 * np.pi * doy / 365.25)
    tr = seri[seri.index.year <= egitim_son]
    td = tr.index.dayofyear.values

    def iklim(gun):
        f = np.abs(td - gun)
        f = np.minimum(f, 365 - f)
        return tr.values[f <= 7].mean()

    tablo = {g: iklim(g) for g in range(1, 367)}
    df["iklim"] = [tablo[g] for g in doy]
    return df.dropna()


tum, ozet = [], []
for test_yil in [2022, 2023, 2024, 2025]:
    df = ozellikler(s, test_yil - 1)
    tr, te = df[df.index.year < test_yil], df[df.index.year == test_yil]
    X = [c for c in df.columns if c != "y"]
    orta = lgb.LGBMRegressor(objective="regression", **ortak).fit(tr[X], tr.y - tr.lag1)
    alt = lgb.LGBMRegressor(objective="quantile", alpha=0.05, **ortak).fit(tr[X], tr.y - tr.lag1)
    ust = lgb.LGBMRegressor(objective="quantile", alpha=0.95, **ortak).fit(tr[X], tr.y - tr.lag1)
    out = pd.DataFrame({"gercek": te.y, "persistence": te.lag1, "iklimatoloji": te.iklim})
    out["lightgbm"] = te.lag1 + orta.predict(te[X])
    out["alt"] = np.minimum(te.lag1 + alt.predict(te[X]), out.lightgbm)
    out["ust"] = np.maximum(te.lag1 + ust.predict(te[X]), out.lightgbm)
    out["yil"] = test_yil
    icinde = (out.gercek >= out.alt) & (out.gercek <= out.ust)
    sicak = out[out.gercek >= out.gercek.quantile(0.95)]
    ozet.append(dict(test_yili=test_yil, egitim=f"2020-{test_yil - 1}", gun=len(out),
                     MAE_persistence=np.mean(np.abs(out.gercek - out.persistence)),
                     MAE_lightgbm=np.mean(np.abs(out.gercek - out.lightgbm)),
                     MAE_iklimatoloji=np.mean(np.abs(out.gercek - out.iklimatoloji)),
                     aralik_kapsama=icinde.mean(), aralik_genislik=(out.ust - out.alt).mean(),
                     sicak5_hata=(sicak.gercek - sicak.lightgbm).mean()))
    tum.append(out)

res = pd.DataFrame(ozet).round(3)
pd.concat(tum).round(2).to_csv("tahmin_yillik.csv", index_label="date")
res.to_csv("tahmin_yillik_ozet.csv", index=False)
print("=== YILLIK İLERİ SARMALI TEST (her yıl yalnızca öncesiyle eğitilir) ===")
print(res.to_string(index=False))
print("\nKaydedildi: tahmin_yillik.csv, tahmin_yillik_ozet.csv")
