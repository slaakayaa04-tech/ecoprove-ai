"""EcoProve AI - Canlı skor fonksiyonu
Tek bir gün için (ve istenirse elle değiştirilmiş değerlerle) güvenilirlik skorunu hesaplar.
Hesap, skor_v1.py ile BİREBİR aynıdır; backend skoru uydurmaz, bu fonksiyonu çağırır.

Kullanım (Python):
    from ecoprove_score import score_reading
    sonuc = score_reading("2023-08-15", {"NOAA_GHCN": 45.8})     # diğer kaynaklar veriden gelir
    print(sonuc["NOAA_GHCN"]["status"], sonuc["NOAA_GHCN"]["score"], sonuc["NOAA_GHCN"]["neden"])

Kullanım (komut satırı):
    python ecoprove_score.py 2023-08-15 NOAA_GHCN=45.8

Gereken dosyalar (aynı klasörde): ecoprove_long.csv, tahmin_2023.csv
Not: Beklenen aralık sadece 2023 günleri için var (modelin test yılı).
"""
import sys
import numpy as np
import pandas as pd

REF = "OPEN_METEO_ERA5"
T_REVIEW, T_QUAR = 3.0, 6.0

_d = pd.read_csv("ecoprove_long.csv", parse_dates=["date"])
W = _d.pivot(index="date", columns="source", values="tmean")
FC = pd.read_csv("tahmin_2023.csv", parse_dates=["date"]).set_index("date")
_egitim = W.index.year <= 2022
KAYNAKLAR = list(W.columns)

# aylık bias (eğitim yılları, ERA5'e göre) ve kaynak başına ölçek (eğitim yıllarının std'si)
_bias = {s: (W[s] - W[REF])[_egitim].groupby(W.index[_egitim].month).mean() for s in KAYNAKLAR}


def _duzelt_satir(tarih, deger):
    return {s: deger[s] - _bias[s][tarih.month] for s in KAYNAKLAR}


_wd = W.copy()
for _s in KAYNAKLAR:
    _wd[_s] = W[_s] - W.index.month.map(_bias[_s]).to_numpy()
_ref = _wd.sub(_wd.median(axis=1), axis=0)
OLCEK = {s: _ref[s][_egitim].std() for s in KAYNAKLAR}


def _durum(z):
    return "Quarantined" if z > T_QUAR else ("Review" if z > T_REVIEW else "Trusted")


def _puan(z):
    return int(round(100 * 2 ** (-(z / T_QUAR) ** 2)))


def score_reading(tarih, degisiklik=None):
    """tarih: '2023-08-15'. degisiklik: {'NOAA_GHCN': 45.8} gibi, veriyi geçersiz kılan değerler."""
    t = pd.Timestamp(tarih)
    if t not in FC.index:
        raise ValueError("Beklenen aralık sadece 2023 günleri için var.")
    deger = {s: W.loc[t, s] for s in KAYNAKLAR}
    deger.update(degisiklik or {})
    onceki = [W[s].shift(g).loc[t] for s in KAYNAKLAR for g in (1, 2)]  # yalnızca tekrar kontrolü için
    wc = _duzelt_satir(t, deger)
    med = np.nanmedian(list(wc.values()))
    alt, ust = FC.loc[t, "alt"], FC.loc[t, "ust"]
    yari = (ust - alt) / 2
    sonuc = {}
    for s in KAYNAKLAR:
        v = deger[s]
        if v is None or np.isnan(v):
            sonuc[s] = {"value": None, "z_eff": None, "score": None, "status": "Missing",
                        "neden": ["Bu kaynak o gün veri vermedi (veri yok olarak kaydedildi)."]}
            continue
        sapma_c = wc[s] - med
        z_cross = abs(sapma_c) / OLCEK[s]
        disari_c = max(alt - wc[s], 0) + max(wc[s] - ust, 0)
        disari = disari_c / yari
        v1, v2 = W[s].shift(1).loc[t], W[s].shift(2).loc[t]
        tekrar = (abs(v - v1) < 1e-9) and (abs(v1 - v2) < 1e-9)
        z = z_cross + disari + (3.0 if tekrar else 0.0)
        durum = _durum(z)
        neden = []
        if z_cross > 1.5:
            neden.append(f"Diğer kaynakların ortak görüşünden {abs(sapma_c):.1f} °C ayrılıyor "
                         f"(bu kaynağın normal sapmasının {z_cross:.1f} katı).")
        if disari > 0:
            neden.append(f"Modelin beklediği aralığın ({alt:.1f} ile {ust:.1f} °C) {disari_c:.1f} °C dışında.")
        if tekrar:
            neden.append("Aynı değer 3 gün üst üste geldi, sensör takılı kalmış olabilir.")
        if not neden:
            neden.append("Diğer kaynaklarla uyumlu ve beklenen aralığın içinde.")
        if durum == "Quarantined":
            neden.append("Karantinaya alındı: silinmedi, insan incelemesi bekliyor.")
        sonuc[s] = {"value": round(float(v), 2), "z_cross": round(float(z_cross), 2),
                    "z_interval": round(float(disari), 2), "repeat": bool(tekrar),
                    "z_eff": round(float(z), 2), "score": _puan(z), "status": durum,
                    "expected_low": round(float(alt), 2), "expected_high": round(float(ust), 2),
                    "neden": neden}
    return sonuc


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    degis = {a.split("=")[0]: float(a.split("=")[1]) for a in sys.argv[2:]}
    for s, r in score_reading(sys.argv[1], degis).items():
        print(f"{s:16s} değer={r['value']}  skor={r['score']}  durum={r['status']}")
        for n in r["neden"]:
            print("   -", n)
