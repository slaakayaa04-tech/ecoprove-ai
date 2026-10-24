"""EcoProve AI - 3 kaynağı ortak günlük şemaya getirir.
Çıktı: ecoprove_long.csv (kaynak başına satır) ve ecoprove_wide.csv (gün başına satır)."""
import pandas as pd, numpy as np, io
U = ""
OUT = ""

# NASA POWER (günlük, -999 = eksik, YEAR+DOY -> tarih)
txt = open(U+"ankara_veri_nasa_power_2020-2025.csv", encoding="utf-8").read()
body = txt.split("-END HEADER-")[1].strip()
n = pd.read_csv(io.StringIO(body)).replace(-999, np.nan)
n["date"] = pd.to_datetime(n.YEAR.astype(str)) + pd.to_timedelta(n.DOY-1, unit="D")
nasa = n.rename(columns={"T2M":"tmean","RH2M":"rh","WS10M":"wind_ms",
                         "PRECTOTCORR":"prcp"})[["date","tmean","rh","wind_ms","prcp"]]

# NOAA GHCN-Daily (günlük, boş = eksik)
o = pd.read_csv(U+"noaa_ankaa.csv")
o["date"] = pd.to_datetime(o.DATE)
noaa = o.rename(columns={"TAVG":"tmean","TMAX":"tmax","TMIN":"tmin","PRCP":"prcp"})[
    ["date","tmean","tmax","tmin","prcp"]]

# Open-Meteo (saatlik + günlük bölüm, yerel saat Europe/Istanbul)
# Sütunları ada göre bulur; farklı sürümlerdeki dosyalarla da çalışır.
lines = open(U+"open-meteo-39_96N32_81E_ankara883m__1_.csv", encoding="utf-8").read().replace("\r","").split("\n")
heads = [i for i,l in enumerate(lines) if l.startswith("time,")]
i_h, i_d = heads[0], heads[1]
def bul(df, anahtar):
    for c in df.columns:
        if anahtar in c: return c
    return None
h = pd.read_csv(io.StringIO("\n".join(lines[i_h:i_d]).strip()))
h["date"] = pd.to_datetime(h["time"]).dt.normalize()
ct = bul(h, "temperature_2m"); cr = bul(h, "relative_humidity"); cp = bul(h, "precipitation")
agg = {"tmean": (ct,"mean")}
if cr: agg["rh"] = (cr,"mean")
if cp: agg["prcp"] = (cp,"sum")
hd = h.groupby("date").agg(**agg).round(2)
d = pd.read_csv(io.StringIO("\n".join(lines[i_d:]).strip()))
d["date"] = pd.to_datetime(d["time"])
om = pd.DataFrame({"date": d["date"]})
for ad, anahtar in [("tmean","temperature_2m_mean"),("tmax","temperature_2m_max"),
                    ("tmin","temperature_2m_min"),("rad_mj","shortwave_radiation_sum"),
                    ("prcp","precipitation_sum"),("wind_kmh","wind_speed_10m_max")]:
    c = bul(d, anahtar)
    if c: om[ad] = d[c].values
om = om.set_index("date")
for ad in ["tmean","rh","prcp"]:                     # günlükte yoksa saatlikten tamamla
    if ad in hd.columns:
        om[ad] = om[ad].fillna(hd[ad]) if ad in om.columns else hd[ad]
if "wind_kmh" in om.columns:
    om["wind_ms"] = (om["wind_kmh"]/3.6).round(2)
om = om.reset_index()

# ortak takvim: 2020-01-01 .. 2025-12-31 (eksik günler satır olarak kalsın)
cal = pd.DataFrame({"date": pd.date_range("2020-01-01","2025-12-31")})
cols = ["tmean","tmax","tmin","rh","wind_ms","prcp","rad_mj"]
frames = []
for name, df, unit_note in [("NASA_POWER", nasa, "MERRA-2 grid ~1128 m"),
                            ("OPEN_METEO_ERA5", om, "~883 m"),
                            ("NOAA_GHCN", noaa, "istasyon 891 m")]:
    f = cal.merge(df, on="date", how="left")
    for c in cols:
        if c not in f: f[c] = np.nan
    f["source"] = name
    f["row_present"] = cal.date.isin(df.date).values   # satır hiç yok mu?
    f["available"] = f.tmean.notna() | f.tmax.notna()
    f["imputed"] = False
    f["unit_temp"] = "C"
    frames.append(f[["date","source","row_present","available","imputed","unit_temp"]+cols])
long = pd.concat(frames, ignore_index=True)
long.to_csv(OUT+"ecoprove_long.csv", index=False)
wide = long.pivot(index="date", columns="source", values=["tmean","tmax","tmin","rh","prcp"])
wide.columns = [f"{v}_{s}" for v,s in wide.columns]
wide.reset_index().to_csv(OUT+"ecoprove_wide.csv", index=False)

# rapor
print("Satır yok (takvimde eksik gün):")
for s,g in long.groupby("source"): print(" ", s, int((~g.row_present).sum()))
missing = sorted(long[(long.source=="NOAA_GHCN") & ~long.row_present].date)
print("NOAA eksik gün sayısı:", len(missing)); print([str(x.date()) for x in missing])
print("\nSütun doluluk % (NOAA):"); print((long[long.source=="NOAA_GHCN"][cols].notna().mean()*100).round(1).to_string())
w = wide
for a,b in [("NASA_POWER","OPEN_METEO_ERA5"),("NOAA_GHCN","OPEN_METEO_ERA5"),("NOAA_GHCN","NASA_POWER")]:
    diff = (w[f"tmean_{a}"]-w[f"tmean_{b}"]).dropna()
    print(f"\ntmean {a} - {b}: n={len(diff)} ort={diff.mean():.2f} std={diff.std():.2f} MAE={diff.abs().mean():.2f} p95|d|={diff.abs().quantile(.95):.2f}")
