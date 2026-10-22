"""EcoProve AI - 2026 verisini mevcut birleşik tabloya ekler.

Neden ayrı dosya? 2020-2025 satırlarına DOKUNULMAZ (2023 kökleri zincirde, değişmemeli).
Bu betik ecoprove_long.csv'yi olduğu gibi alır, birlestir.py ile AYNI kurallarla okunan
2026 satırlarını sonuna ekler ve yeni dosyaya yazar.

Girdiler (aynı klasörde):
  ecoprove_long.csv        (2020-2025, değişmeden kalır)
  nasa_2026.csv            NASA POWER, 39.93 N 32.86 E, LST, T2M/RH2M/WS10M/PRECTOTCORR
  open_meteo_2026.csv      Open-Meteo, 39.9334 N 32.8597 E (yükseklik 883 m), Europe/Istanbul
  noaa_2026.csv            NOAA GHCN-Daily, TUM00017130 ANKARA CENTRAL (891 m)
İndirme ayarları 1 Aralık 2025 örtüşmesiyle doğrulandı (eski tabloyla aynı değerler).

Çıktılar: ecoprove_long_2026.csv, ecoprove_wide_2026.csv   (2020-01-01 .. 2026-08-31)
"""
import io
import numpy as np
import pandas as pd

BITIS = "2026-08-31"          # aylık Merkle kökleri için tam aylar (Ocak-Ağustos 2026)

eski = pd.read_csv("ecoprove_long.csv", parse_dates=["date"])

# --- NASA POWER (birlestir.py ile aynı)
txt = open("nasa_2026.csv", encoding="utf-8").read()
body = txt.split("-END HEADER-")[1].strip()
n = pd.read_csv(io.StringIO(body)).replace(-999, np.nan)
n["date"] = pd.to_datetime(n.YEAR.astype(str)) + pd.to_timedelta(n.DOY - 1, unit="D")
nasa = n.rename(columns={"T2M": "tmean", "RH2M": "rh", "WS10M": "wind_ms",
                         "PRECTOTCORR": "prcp"})[["date", "tmean", "rh", "wind_ms", "prcp"]]

# --- NOAA GHCN-Daily (birlestir.py ile aynı)
o = pd.read_csv("noaa_2026.csv")
o["date"] = pd.to_datetime(o.DATE)
noaa = o.rename(columns={"TAVG": "tmean", "TMAX": "tmax", "TMIN": "tmin", "PRCP": "prcp"})[
    ["date", "tmean", "tmax", "tmin", "prcp"]]

# --- Open-Meteo (birlestir.py ile aynı: sütunlar ada göre bulunur)
lines = open("open_meteo_2026.csv", encoding="utf-8").read().replace("\r", "").split("\n")
heads = [i for i, l in enumerate(lines) if l.startswith("time,")]
i_h, i_d = heads[0], heads[1]


def bul(df, anahtar):
    for c in df.columns:
        if anahtar in c:
            return c
    return None


h = pd.read_csv(io.StringIO("\n".join(lines[i_h:i_d]).strip()))
h["date"] = pd.to_datetime(h["time"]).dt.normalize()
ct = bul(h, "temperature_2m"); cr = bul(h, "relative_humidity"); cp = bul(h, "precipitation")
agg = {"tmean": (ct, "mean")}
if cr: agg["rh"] = (cr, "mean")
if cp: agg["prcp"] = (cp, "sum")
hd = h.groupby("date").agg(**agg).round(2)
d = pd.read_csv(io.StringIO("\n".join(lines[i_d:]).strip()))
d["date"] = pd.to_datetime(d["time"])
om = pd.DataFrame({"date": d["date"]})
for ad, anahtar in [("tmean", "temperature_2m_mean"), ("tmax", "temperature_2m_max"),
                    ("tmin", "temperature_2m_min"), ("rad_mj", "shortwave_radiation_sum"),
                    ("prcp", "precipitation_sum"), ("wind_kmh", "wind_speed_10m_max")]:
    c = bul(d, anahtar)
    if c: om[ad] = d[c].values
om = om.set_index("date")
for ad in ["tmean", "rh", "prcp"]:
    if ad in hd.columns:
        om[ad] = om[ad].fillna(hd[ad]) if ad in om.columns else hd[ad]
if "wind_kmh" in om.columns:
    om["wind_ms"] = (om["wind_kmh"] / 3.6).round(2)
om = om.reset_index()

# --- 2026 takvimi (eksik günler satır olarak kalır)
cal = pd.DataFrame({"date": pd.date_range("2026-01-01", BITIS)})
cols = ["tmean", "tmax", "tmin", "rh", "wind_ms", "prcp", "rad_mj"]
frames = []
for name, df in [("NASA_POWER", nasa), ("OPEN_METEO_ERA5", om), ("NOAA_GHCN", noaa)]:
    df = df[df.date <= BITIS]
    f = cal.merge(df, on="date", how="left")
    for c in cols:
        if c not in f: f[c] = np.nan
    f["source"] = name
    f["row_present"] = cal.date.isin(df.date).values
    f["available"] = f.tmean.notna() | f.tmax.notna()
    f["imputed"] = False
    f["unit_temp"] = "C"
    frames.append(f[["date", "source", "row_present", "available", "imputed", "unit_temp"] + cols])
yeni = pd.concat(frames, ignore_index=True)

assert eski.date.max() == pd.Timestamp("2025-12-31"), "ecoprove_long.csv 2025 sonunda bitmeli"
long = pd.concat([eski, yeni[eski.columns]], ignore_index=True)
long.to_csv("ecoprove_long_2026.csv", index=False)
wide = long.pivot(index="date", columns="source", values=["tmean", "tmax", "tmin", "rh", "prcp"])
wide.columns = [f"{v}_{s}" for v, s in wide.columns]
wide.reset_index().to_csv("ecoprove_wide_2026.csv", index=False)

# --- kontrol: 2020-2025 satırları birebir aynı kaldı mı?
geri = pd.read_csv("ecoprove_long_2026.csv", parse_dates=["date"])
ilk = geri[geri.date <= "2025-12-31"].reset_index(drop=True)
ayni = ilk.equals(pd.read_csv("ecoprove_long.csv", parse_dates=["date"]))
print("2020-2025 satırları değişmedi mi?", "EVET" if ayni else "HAYIR (DUR, kontrol et)")
print("Toplam satır:", len(long), "| son gün:", long.date.max().date())
print("\n2026 eksik günler (tmean yok):")
for s, g in yeni.groupby("source"):
    eks = g[g.tmean.isna()].date.dt.strftime("%Y-%m-%d").tolist()
    print(f"  {s}: {len(eks)}  {eks}")
