import pandas as pd, numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
OUT=""
w=pd.read_csv(OUT+"ecoprove_wide.csv",parse_dates=["date"]).set_index("date")
# 1) fark histogramı (bias düzeltmeden ve düzeltmiş)
pairs=[("NASA_POWER","OPEN_METEO_ERA5"),("NOAA_GHCN","OPEN_METEO_ERA5"),("NOAA_GHCN","NASA_POWER")]
fig,ax=plt.subplots(1,3,figsize=(15,4))
for a,(x,y) in zip(ax,pairs):
    d=(w[f"tmean_{x}"]-w[f"tmean_{y}"]).dropna()
    a.hist(d,bins=50,color="#2a9d8f"); a.axvline(d.mean(),color="r",ls="--")
    a.set_title(f"{x} - {y}\nort={d.mean():.2f}  std={d.std():.2f}"); a.set_xlabel("°C fark")
plt.tight_layout(); plt.savefig(OUT+"sapma_histogram.png",dpi=120)
# 2) eksik günler: ERA5 ve NASA o gün ne diyordu, mevsim normaline göre?
era=w["tmean_OPEN_METEO_ERA5"]; doy=era.index.dayofyear
clim=era.groupby(doy).mean(); sd=era.groupby(doy).std()
miss=w.index[w["tmean_NOAA_GHCN"].isna() & w.index.isin(pd.to_datetime(
 ['2021-02-11','2021-02-12','2021-02-20','2024-03-28','2024-03-29','2024-03-30','2024-03-31','2024-05-01','2024-08-12','2024-11-18','2024-11-19','2024-11-20','2024-11-21','2024-12-01','2025-02-28','2025-08-30','2025-08-31','2025-09-01','2025-09-02']))]
rows=[]
for d in miss:
    k=d.dayofyear; z=(era[d]-clim[k])/sd[k]
    rows.append((d.date(),round(era[d],1),round(w.loc[d,"tmean_NASA_POWER"],1),round(clim[k],1),round(z,2)))
r=pd.DataFrame(rows,columns=["tarih","ERA5_tmean","NASA_tmean","normal_ERA5","z"])
r.to_csv(OUT+"eksik_gunler_hava.csv",index=False); print(r.to_string(index=False))
print("\n|z|>2 olan eksik gün:",int((r.z.abs()>2).sum()))
# 3) genel olarak en sıcak günler (demo adayı)
print("\nERA5 en sıcak 5 gün:"); print(era.nlargest(5).round(1).to_string())
