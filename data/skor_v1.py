"""EcoProve AI - Reliability Score v1
2023 (test yılı) için her gün ve her kaynak için güvenilirlik skoru üretir.

Üç kanıt birleşir:
  1) Kaynaklar arası uyumsuzluk  : aylık bias düzeltilmiş değerin, diğer kaynakların medyanından sapması
  2) Tahmin aralığı dışı kalma   : değer, modelin %90 beklenen aralığının ne kadar dışında
  3) Tekrar eden değer           : aynı değerin 3 gün üst üste gelmesi (takılı sensör şüphesi)
z_eff = z_cross + 1.0 * disari + 3.0 * tekrar
Eşikler (sabit, test verisine göre ayarlanmadı): z_eff <= 3 Trusted, <= 6 Review, > 6 Quarantined.

Gereken dosyalar (aynı klasörde): ecoprove_long.csv, tahmin_2023.csv
Çıktılar: reliability_scores_v1.csv, demo_ornekleri.csv
"""
import numpy as np
import pandas as pd

REF = "OPEN_METEO_ERA5"
T_REVIEW, T_QUAR = 3.0, 6.0

d = pd.read_csv("ecoprove_long.csv", parse_dates=["date"])
w = d.pivot(index="date", columns="source", values="tmean")
fc = pd.read_csv("tahmin_2023.csv", parse_dates=["date"]).set_index("date")
egitim = w.index.year <= 2022
test = w.index[w.index.year == 2023]

# aylık bias (eğitim yılları, ERA5'e göre)
bias_ay = {s: (w[s] - w[REF])[egitim].groupby(w.index[egitim].month).mean() for s in w.columns}


def duzelt(df):
    o = df.copy()
    for s in df.columns:
        o[s] = df[s] - df.index.month.map(bias_ay[s]).to_numpy()
    return o


w_d = duzelt(w)
ref_sap = w_d.sub(w_d.median(axis=1), axis=0)
olcek = {s: ref_sap[s][egitim].std() for s in w.columns}


def skorla(veri):
    """veri: tüm tarihler x kaynaklar günlük sıcaklık tablosu. 2023 için tablo döndürür."""
    wc = duzelt(veri)
    sap = wc.sub(wc.median(axis=1), axis=0)
    alt, ust = fc.loc[test, "alt"], fc.loc[test, "ust"]
    yari = (ust - alt) / 2
    zs = {}
    for s in veri.columns:
        z_cross = (sap[s].abs() / olcek[s]).loc[test]
        disari = ((np.maximum(alt - wc.loc[test, s], 0) + np.maximum(wc.loc[test, s] - ust, 0)) / yari)
        tek = ((veri[s].diff().abs() < 1e-9) & (veri[s].shift(1).diff().abs() < 1e-9)).loc[test]
        zs[s] = z_cross + 1.0 * disari + 3.0 * tek.astype(float)
    return pd.DataFrame(zs), alt, ust


def durum(z):
    return "Quarantined" if z > T_QUAR else ("Review" if z > T_REVIEW else "Trusted")


def puan(z):
    return int(round(100 * 2 ** (-(z / T_QUAR) ** 2)))   # z=6 -> 50, z=3 -> 84


z, alt, ust = skorla(w)
rows = []
for s in w.columns:
    for t in test:
        v = w.loc[t, s]
        if np.isnan(v) or np.isnan(z.loc[t, s]):
            rows.append((t.date(), s, "", round(alt[t], 2), round(ust[t], 2), "", "", "Missing"))
        else:
            rows.append((t.date(), s, round(v, 2), round(alt[t], 2), round(ust[t], 2),
                         round(z.loc[t, s], 2), puan(z.loc[t, s]), durum(z.loc[t, s])))
out = pd.DataFrame(rows, columns=["date", "source", "tmean", "expected_low", "expected_high",
                                  "z_eff", "score", "status"])
out.to_csv("reliability_scores_v1.csv", index=False)

print("=== SKOR v1, 2023 (hata eklenmemiş TEMİZ veri) ===")
print("Satır:", len(out))
print(out.status.value_counts().to_string())
temiz = out[out.status != "Missing"]
print(f"Temiz veride Review+Quarantined oranı (yanlış alarm): %{100 * (temiz.status != 'Trusted').mean():.1f}")

# demo örnekleri
gun = pd.Timestamp("2023-08-15")
satir = []


def ornek(ad, veri, kaynak):
    zz, a, u = skorla(veri)
    zv = zz.loc[gun, kaynak]
    satir.append((ad, kaynak, round(veri.loc[gun, kaynak], 2), round(a[gun], 2), round(u[gun], 2),
                  round(zv, 2), puan(zv), durum(zv)))


ornek("1) Normal gün", w, "NOAA_GHCN")
v2 = w.copy(); v2.loc[gun, "NOAA_GHCN"] = 45.8
ornek("2) NOAA sensörü 45.8 C gönderiyor", v2, "NOAA_GHCN")
v3 = w.copy(); v3.loc[gun] = v3.loc[gun] + 7
for k in w.columns:
    ornek("3) Gerçek ekstrem (3 kaynak da +7 C)", v3, k)
demo = pd.DataFrame(satir, columns=["senaryo", "kaynak", "tmean", "expected_low", "expected_high",
                                    "z_eff", "score", "status"])
demo.to_csv("demo_ornekleri.csv", index=False)
print("\n=== DEMO ÖRNEKLERİ (15 Ağustos 2023) ===")
print(demo.to_string(index=False))
print("\nKaydedildi: reliability_scores_v1.csv, demo_ornekleri.csv")
