# EcoProve AI

Çevresel verilerin kullanılmadan önce güvenilirliğini değerlendiren, şüpheli veriyi silmeden karantinaya alan ve kararların kaydını blokzincirde izlenebilir yapan bir güven katmanı.

Track: Climate Data & Environmental Monitoring (IEEE Global ClimateChain Hackathon 2026)

## Durum
- [x] Üç veri kaynağını ortak şemaya getirme (`birlestir.py`)
- [x] Kaynaklar arası sapma ve eksik gün analizi (`analiz_A.py`)
- [x] Tahmin modeli: eğitim 2020-2022, test 2023, %90 beklenen aralık (`tahmin_v1.py`)
- [x] Reliability Score v0 (prototip, yerini v1 aldı) (`skor_v0.py`)
- [x] Aylık Merkle kökleri (`merkle_kok.py`)
- [x] Registry contract: Sepolia test ağında çalıştırıldı (adres ve Etherscan linki eklenecek)
- [x] Sahte hata testi: bilinen hatalar enjekte edilip yakalama ölçüldü (`sahte_hata_testi.py`)
- [x] Reliability Score v1, 2023: kaynaklar arası uyum + tahmin aralığı + tekrar eden değer (`skor_v1.py`)
- [x] Adaptive Trust: kaynak güveni, 10 tohumlu karşılaştırma ve eşik duyarlılığı (`degerlendirme_v2.py`)
- [x] Merkle kanıt dosyası, kayıt bazlı doğrulama (`merkle_kanit.py`)
- [x] Canlı skor fonksiyonu, nedenleriyle birlikte (`ecoprove_score.py`)
- [x] Yöntem belgesi (`YONTEM.md`)
- [ ] Backend, dashboard, testnet deploy

## Veri kaynakları (Ankara, 2020-2025)
- NASA POWER (MERRA-2), günlük: https://power.larc.nasa.gov/
- Open-Meteo (ERA5 reanalysis): https://open-meteo.com/
- NOAA GHCN-Daily istasyon verisi: https://www.ncei.noaa.gov/

## Çalıştırma sırası
Dosyalar aynı klasörde olmalı:
```
pip install pandas numpy matplotlib lightgbm pycryptodome
python hazirla.py        # dosya adlarını düzeltir, birleştirir, analiz eder
python tahmin_v1.py      # tahmin_2023.csv, tahmin_2023.png
python skor_v1.py        # reliability_scores_v1.csv, demo_ornekleri.csv
python merkle_kok.py reliability_scores_v1.csv merkle_roots_v1.csv
python merkle_kanit.py   # merkle_kanitlari_v1.csv
python sahte_hata_testi.py
python degerlendirme_v2.py
python ecoprove_score.py 2023-08-15 NOAA_GHCN=45.8   # canlı skor örneği
```

## Bilinen sınırlılıklar
- NASA POWER ve ERA5 ikisi de reanaliz tabanlıdır, birbirinden bağımsız ölçüm değildir. Gerçek ölçüm kaynağı yalnızca NOAA istasyonudur.
- Tek şehir (Ankara) ve tek ana değişken (günlük ortalama sıcaklık).
- Tahmin modeli persistence baseline'ı ile aynı doğruluktadır; katkısı beklenen aralığı sağlamasıdır.

## İlgili çalışma
Heston TF (2026). A proof-of-stake blockchain framework for transparent climate data verification. PLOS Climate 5(6): e0000764. https://doi.org/10.1371/journal.pclm.0000764
