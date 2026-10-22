"""EcoProve AI - Degerlendirme v2: Adaptive Trust + esik duyarliligi + 10 rastgele tohum

Ne yapar?
 1) Kaynak guveni (Adaptive Trust): her kaynagin gecmis uyumuna gore bir guven puani (Beta-reputation).
 2) Sahte hata testini 10 farkli rastgele tohumla tekrarlar (tek deneme sansi yok).
 3) Adaptive Trust ACIK ve KAPALI sonuclarini yan yana karsilastirir.
 4) Esik duyarliligi: Review ve Quarantine esikleri degisirse sonuc ne olur?

Gereken dosyalar (ayni klasorde): ecoprove_long.csv, tahmin_2023.csv
Ciktilar: adaptive_karsilastirma.csv, esik_duyarlilik.csv, kaynak_guveni_2023.csv, kaynak_guveni_2023.png
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SENSOR, REF = "NOAA_GHCN", "OPEN_METEO_ERA5"
LAMBDA = 0.97            # unutma katsayisi: ~33 gunluk hafiza
UYUM_ESIGI = 3.0         # kaynaklar arasi z <= 3 ise o gun "uyumlu" sayilir
TOHUMLAR = range(10)

# ------------------------------------------------------------------ veri
d = pd.read_csv("ecoprove_long.csv", parse_dates=["date"])
w = d.pivot(index="date", columns="source", values="tmean")
fc = pd.read_csv("tahmin_2023.csv", parse_dates=["date"]).set_index("date")
egitim = w.index.year <= 2022
test = w.index[w.index.year == 2023]
idx = w.index[w.index.year <= 2023]          # guven puani 2020-2023 boyunca islenir
kaynaklar = list(w.columns)

bias_ay = {s: (w[s] - w[REF])[egitim].groupby(w.index[egitim].month).mean() for s in kaynaklar}


def duzelt(df):
    o = df.copy()
    for s in df.columns:
        o[s] = df[s] - df.index.month.map(bias_ay[s]).to_numpy()
    return o


w_d = duzelt(w)
ref_sap = w_d.sub(w_d.median(axis=1), axis=0)
olcek = {s: ref_sap[s][egitim].std() for s in kaynaklar}     # egitim yillarinin standart sapmasi


# ------------------------------------------------------------------ kaynak guveni
def guven_serisi(z_cross):
    """Beta-reputation. Her gun: o gunden ONCEKI davranisa gore guven = a / (a + b).
    Sonra bugunun gozlemi eklenir (uyumlu -> a artar, uyumsuz -> b artar), eskiler LAMBDA ile solar."""
    out = pd.DataFrame(index=z_cross.index, columns=z_cross.columns, dtype=float)
    for s in z_cross.columns:
        a = b = 1.0
        for t, z in z_cross[s].items():
            out.loc[t, s] = a / (a + b)             # bugunku guven = sadece gecmisten
            if np.isnan(z):
                a, b = a * LAMBDA, b * LAMBDA        # veri yok: sadece sol
            else:
                a = a * LAMBDA + (1.0 if z <= UYUM_ESIGI else 0.0)
                b = b * LAMBDA + (0.0 if z <= UYUM_ESIGI else 1.0)
    return out


def hata_ekle(seed):
    rng = np.random.default_rng(seed)
    bad = w.copy()
    bos = np.ones(len(test), dtype=bool)
    etiket = pd.Series("temiz", index=test)
    pos0 = w.index.get_loc(test[0])

    def yer_ac(n):
        for _ in range(2000):
            i = int(rng.integers(5, len(test) - n - 5))
            if bos[i - 2:i + n + 2].all():
                bos[i - 2:i + n + 2] = False
                return i
        raise RuntimeError("yer yok")

    c = w.columns.get_loc(SENSOR)
    for _ in range(3):                                       # drift: 20 gunde 0 -> +6
        i = yer_ac(20)
        bad.iloc[pos0 + i:pos0 + i + 20, c] += np.linspace(0, 6, 20)
        etiket.iloc[i:i + 20] = "drift"
    for _ in range(4):                                       # takili sensor: 7 gun ayni deger
        i = yer_ac(7)
        bad.iloc[pos0 + i:pos0 + i + 7, c] = w.iloc[pos0 + i, c]
        etiket.iloc[i:i + 7] = "takili_sensor"
    for _ in range(8):                                       # ani sicrama +-15
        i = yer_ac(1)
        bad.iloc[pos0 + i, c] += rng.choice([-1, 1]) * 15
        etiket.iloc[i] = "sicrama"
    for _ in range(6):                                       # C <-> F karisikligi
        i = yer_ac(1)
        bad.iloc[pos0 + i, c] = w.iloc[pos0 + i, c] * 9 / 5 + 32
        etiket.iloc[i] = "birim_hatasi"
    for _ in range(4):                                       # GERCEK ekstrem: 3 gun +7, TUM kaynaklar
        i = yer_ac(3)
        bad.iloc[pos0 + i:pos0 + i + 3, :] += 7
        etiket.iloc[i:i + 3] = "gercek_ekstrem"
    fark = (bad.loc[test, SENSOR] - w.loc[test, SENSOR])
    hatali = etiket.isin(["sicrama", "birim_hatasi", "takili_sensor", "drift"]) & (fark.abs() >= 1.5)
    return bad, etiket, hatali


def z_hesapla(bad):
    """Donus: z_base (guvensiz) ve z_adapt (guvenle carpilmis), her ikisi 2023 icin."""
    wc = duzelt(bad)
    sap = wc.sub(wc.median(axis=1), axis=0)
    z_cross_all = pd.DataFrame({s: (sap[s].abs() / olcek[s]) for s in kaynaklar}).loc[idx]
    guven = guven_serisi(z_cross_all)
    # her kaynagin "normal" guveni: egitim yillari ortalamasi (ilk 60 gun isinma haric)
    g_egit = guven.loc[(guven.index.year <= 2022)].iloc[60:]
    g0 = g_egit.mean()
    carpan = (g0 / guven).clip(0.8, 3.0).loc[test]
    alt, ust = fc.loc[test, "alt"], fc.loc[test, "ust"]
    yari = (ust - alt) / 2
    zb = {}
    for s in kaynaklar:
        disari = (np.maximum(alt - wc.loc[test, s], 0) + np.maximum(wc.loc[test, s] - ust, 0)) / yari
        tek = ((bad[s].diff().abs() < 1e-9) & (bad[s].shift(1).diff().abs() < 1e-9)).loc[test]
        zb[s] = z_cross_all.loc[test, s] + disari + 3.0 * tek.astype(float)
    zb = pd.DataFrame(zb)
    return zb, zb * carpan, guven


def metrik(z, etiket, hatali, t_rev, t_quar):
    s = z[SENSOR]
    flag = s > t_rev
    temiz = etiket == "temiz"
    tp = int((flag & hatali).sum()); fp = int((flag & ~hatali & temiz).sum()); fn = int((~flag & hatali).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    r = dict(precision=pr, recall=rc, F1=f1, yanlis_alarm=fp / int(temiz.sum()))
    for tur in ["sicrama", "birim_hatasi", "takili_sensor", "drift"]:
        m = hatali & (etiket == tur)
        r["yakalama_" + tur] = float((s[m] > t_rev).mean())
    ge = (etiket == "gercek_ekstrem").to_numpy()
    r["gercek_ekstrem_karantina"] = float((z.to_numpy()[ge] > t_quar).mean())
    return r


# ------------------------------------------------------------------ 10 tohum
kayit = []
for seed in TOHUMLAR:
    bad, etiket, hatali = hata_ekle(seed)
    zb, za, _ = z_hesapla(bad)
    for mod, z in [("guven_KAPALI", zb), ("guven_ACIK", za)]:
        for tr in [2.5, 3.0, 3.5]:
            for tq in [5.0, 6.0, 7.0]:
                kayit.append(dict(seed=seed, mod=mod, T_review=tr, T_quar=tq, **metrik(z, etiket, hatali, tr, tq)))
res = pd.DataFrame(kayit)

varsayilan = res[(res.T_review == 3.0) & (res.T_quar == 6.0)]
ozet = varsayilan.groupby("mod").agg(["mean", "std"]).drop(columns=["seed", "T_review", "T_quar"])
ozet.columns = [f"{a}_{b}" for a, b in ozet.columns]
ozet.round(3).to_csv("adaptive_karsilastirma.csv")
esik = res.groupby(["mod", "T_review", "T_quar"])[["precision", "recall", "F1", "yanlis_alarm",
                                                   "gercek_ekstrem_karantina"]].mean().round(3)
esik.to_csv("esik_duyarlilik.csv")

print("=== 10 TOHUM ORTALAMASI, esikler 3 / 6 (ortalama +- std) ===")
for mod in ["guven_KAPALI", "guven_ACIK"]:
    r = varsayilan[varsayilan["mod"] == mod]
    print(f"\n[{mod}]")
    for k in ["precision", "recall", "F1", "yanlis_alarm", "yakalama_sicrama", "yakalama_birim_hatasi",
              "yakalama_takili_sensor", "yakalama_drift", "gercek_ekstrem_karantina"]:
        print(f"  {k:26s} {r[k].mean():.3f} +- {r[k].std():.3f}")
print("\n=== ESIK DUYARLILIGI (10 tohum ortalamasi) ===")
print(esik.to_string())

# ------------------------------------------------------------------ kaynak guveni 2023 (temiz) + grafik
_, _, g_temiz = z_hesapla(w.copy())
g23 = g_temiz.loc[test]
g23.round(3).to_csv("kaynak_guveni_2023.csv", index_label="date")
bad0, _, _ = hata_ekle(0)
_, _, g_bad = z_hesapla(bad0)
fig, ax = plt.subplots(figsize=(12, 4.2))
for s, renk in zip(kaynaklar, ["#e9c46a", "#2a9d8f", "#264653"]):
    ax.plot(g23.index, g23[s], lw=1.2, color=renk, label=f"{s} (temiz veri)")
ax.plot(test, g_bad.loc[test, SENSOR], lw=1.4, color="#e76f51", label="NOAA (hata eklenmis, tohum 0)")
ax.set_ylim(0, 1.02); ax.set_ylabel("Kaynak guveni (0-1)")
ax.set_title("Adaptive Trust: kaynaklarin guveni 2023 boyunca"); ax.legend(loc="lower left", ncol=2, fontsize=8)
plt.tight_layout(); plt.savefig("kaynak_guveni_2023.png", dpi=120)
print("\nKaydedildi: adaptive_karsilastirma.csv, esik_duyarlilik.csv, kaynak_guveni_2023.csv/.png")
