# Dosya adlarını düzeltir, sonra birleştirme ve analizi çalıştırır.
import glob, os, subprocess, sys
hedef = [("*nasa*power*", "ankara_veri_nasa_power_2020-2025.csv"),
         ("noaa*", "noaa_ankaa.csv"),
         ("open-meteo*", "open-meteo-39_96N32_81E_ankara883m__1_.csv")]
for desen, yeni in hedef:
    bulunan = [f for f in glob.glob(desen) if f.endswith(".csv")]
    if not bulunan:
        print("BULUNAMADI:", desen); continue
    if bulunan[0] != yeni:
        os.rename(bulunan[0], yeni); print("Yeniden adlandırıldı:", bulunan[0], "->", yeni)
    else:
        print("Adı doğru:", yeni)
for kod in ["birlestir.py", "analiz_A.py"]:
    print("\n=====", kod, "=====")
    subprocess.run([sys.executable, kod])
