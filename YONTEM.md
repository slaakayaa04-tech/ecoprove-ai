# EcoProve AI: Methodology / Yöntem Belgesi

## English Summary

- **Data:** Daily mean temperature for Ankara, Türkiye from three sources: NASA POWER (MERRA-2 reanalysis, ~1128 m), Open-Meteo ERA5 (reanalysis, ~883 m, reference series) and NOAA GHCN-Daily (Ankara Central station, 891 m). Days with no station data are kept as `Missing`, never deleted.
- **Bias correction:** Systematic, season-dependent differences (mainly elevation) are removed using the monthly mean difference of each source from ERA5, computed only on training years.
- **Forecast model:** LightGBM learns the day-to-day change using only past information (lags of 1, 2, 3 and 7 days, 7- and 30-day rolling means, day-of-year terms, climatology). No same-day values from other sources are used, so there is no leakage. Two quantile models (5% and 95%) give a 90% expected band. Evaluation is walk-forward: each test year is trained only on earlier years.
- **Reliability score:** `z_eff = z_cross + z_interval + 3 × repeat`, where `z_cross` is the bias-corrected deviation from the cross-source median (scaled by that source's typical deviation), `z_interval` is the distance outside the 90% band relative to its half-width, and `repeat` flags a value repeated three days in a row. Status: `z_eff ≤ 3` Trusted, `3–6` Review, `> 6` Quarantined. Displayed score = `100 × 2^(-(z_eff/6)^2)`. Quarantine is not deletion.
- **Fault test:** Known faults (±15 °C spikes, °C/°F unit errors, stuck sensors, gradual drift) are injected into clean 2023 NOAA data, plus real multi-source extremes (+7 °C on all sources) that must not be quarantined. Repeated with 10 random seeds and several thresholds, and compared to a single-series `|z| > 3` baseline.
- **Blockchain:** Each record becomes a `keccak256` leaf of `date|source|tmean|score|status`. Leaves are combined into a sorted-pair Merkle tree per month, and only the monthly root and record count are written to the `EcoProveRegistry` contract on Sepolia. A month cannot be overwritten once stored.
- **Limitations:** The chain proves records were not changed after sealing, not that they are physically correct. NASA POWER and ERA5 are both reanalysis products and not fully independent. Faults are synthetic. Single city, single variable, testnet only.

The detailed Turkish version follows below.

---

Bu belge, sistemin her adımını ve kullandığı sayıları açıklar. Sentetik hata testleri 2023 test yılına ve kontrollü hata senaryolarına dayanır.

## 1. Veri

Ankara, günlük ortalama sıcaklık, 2020-2025. Üç kaynak:

| Kaynak | Nitelik | Not |
|---|---|---|
| NASA POWER (MERRA-2) | Reanaliz, ızgara hücresi yaklaşık 1128 m | İstasyondan yaklaşık 1.7 °C soğuk, yükseklik farkı |
| Open-Meteo (ERA5) | Reanaliz, yaklaşık 883 m | Eksiksiz tek kaynak |
| NOAA GHCN-Daily | Gerçek istasyon ölçümü, yaklaşık 891 m | 19 gün hiç kayıt yok, tmax/tmin/yağış seyrek |

NASA ve ERA5 ikisi de reanalizdir, birbirinden bağımsız ölçüm sayılmaz. Gerçek ölçüm yalnızca NOAA'dır. Ana değişken sıcaklıktır (üç kaynakta da dolu); nem, rüzgâr ve radyasyon her kaynakta bulunmadığı için karşılaştırılamaz.

Kod: `birlestir.py` (ortak şema), `analiz_A.py` (sapma ve eksik gün analizi).

## 2. Bias düzeltme

Kaynaklar arasındaki sistematik fark (yükseklik gibi) mevsime göre değişir. Her kaynak için 2020-2022 yıllarında, ERA5'e göre **ay ay ortalama fark** hesaplanır ve değerden çıkarılır. Böylece bir kaynak normal davranışı yüzünden şüpheli görünmez.

## 3. Tahmin modeli

- Eğitim 2020-2022, test 2023. Model 2023'ü eğitimde hiç görmez.
- Hedef: ERA5 günlük ortalama sıcaklığı.
- Girdiler yalnızca **geçmişten** gelir: 1, 2, 3 ve 7 gün önceki değer, son 7 ve 30 günün ortalaması, yılın günü, o günün çok yıllık ortalaması. Aynı günün başka kaynak değerleri modele verilmez (veri sızıntısı olmasın diye).
- Model LightGBM'dir; sıcaklığın kendisini değil "dünden ne kadar değişeceğini" öğrenir. Alt (%5) ve üst (%95) sınırları için iki ek model, **%90'lık beklenen aralığı** verir.
- Sonuç (2023, yaklaşık): ortalama hata persistence ("dün neyse bugün o") ile aynı, 1.3 °C. Aralık günlerin yaklaşık %87'sini kapsar. En sıcak %5 günde model ortalama 1.5 °C düşük tahmin eder.
- **Yorum:** Modelin değeri doğruluk değil, beklenen aralığı vermesidir. Tahmin hatası veri hatası anlamına gelmez; gerçek bir ekstrem olay aralığın dışında kalabilir.

Kod: `tahmin_v1.py`.

## 4. Güvenilirlik skoru (v1)

Her gün ve her kaynak için bir şüphe puanı hesaplanır:

`z_eff = z_cross + z_interval + 3 × tekrar`

1. **z_cross (kaynaklar arası uyumsuzluk):** Bias düzeltilmiş değerin, üç kaynağın ortanca değerinden sapması, o kaynağın 2020-2022'deki tipik sapmasına (standart sapma) bölünür.
2. **z_interval (tahmin aralığı dışı):** Değer %90 beklenen aralığın dışındaysa, dışında kalan miktarın aralık yarı genişliğine oranı. İçindeyse 0.
3. **tekrar:** Aynı değer üç gün üst üste geldiyse takılı sensör şüphesi olarak +3.

**Durum eşikleri (sabit):** z_eff ≤ 3 Trusted, 3-6 Review, > 6 Quarantined. Gösterilen skor `100 × 2^(-(z_eff/6)^2)`: şüphe 0'sa 100, 3'te 84, 6'da 50.

Karantina silme değildir: kayıt ayrı durumda saklanır, nedeniyle birlikte incelemeye açıktır.

Kodlar: `skor_v1.py` (2023 toplu), `ecoprove_score.py` (tek gün, canlı; sonuçları skor_v1 ile birebir aynıdır ve neden listesi verir).

## 5. Kaynak güveni (Adaptive Trust)

Beta-reputation: her kaynağın bir "uyumlu gün" ve bir "uyumsuz gün" sayacı vardır (başlangıç 1 ve 1). Bugünkü güven yalnızca geçmişten hesaplanır: `uyumlu / (uyumlu + uyumsuz)`. Gün sonunda kaynaklar arası sapma ≤ 3 ise uyumlu, değilse uyumsuz sayılır. Eski günler her gün %3 solar (yaklaşık 33 günlük hafıza). Güven, kaynağın normal güvenine (2020-2022 ortalaması) oranlanıp şüphe puanıyla çarpılabilir (0.8-3 arası sınırlı).

**Ölçülen etki (10 rastgele tohum, eşikler 3/6, yaklaşık):** yavaş hataların yakalanması artar (takılı sensör %90 → %96, drift %82 → %86), ama yanlış alarm da artar (%4.5 → %6.5); F1 neredeyse aynıdır (0.86 → 0.85). Bu nedenle güven şimdilik skoru değiştirmez, ayrı bir gösterge olarak sunulur.

Kod: `degerlendirme_v2.py`.

## 6. Sahte hata testi

Temiz 2023 verisine bilinen hatalar eklenir ve sistemin yakalayıp yakalamadığı ölçülür. Hata NOAA'ya eklenir:

- 8 ani sıçrama (±15 °C)
- 6 °C/°F karışıklığı
- 4 takılı sensör (7 gün aynı değer)
- 3 drift (20 günde 0 → +6 °C kayma)
- 4 **gerçek ekstrem olay** (3 gün, +7 °C, üç kaynakta birden): hata sayılmaz, karantinaya düşmemesi beklenir

Metrikler: precision, recall, F1, temiz günlerde yanlış alarm, her hata türü için yakalama, gerçek ekstremin karantinaya düşme oranı. Test 10 farklı rastgele tohumla tekrarlanır; eşikler (2.5/3/3.5 ve 5/6/7) için duyarlılık analizi yapılır. F1 üç Review eşiğinde de yaklaşık 0.86-0.87'dir; sonuç eşiğe fazla duyarlı değildir.

**Karşılaştırma:** Tek kaynaklı, sabit eşikli (|z| > 3, tüm yılın ortalaması ve standart sapmasıyla) basit bir yöntem aynı testte F1 yaklaşık 0.15 verir. Bu baseline'ı Heston (2026) tarzında kendimiz yazdık; yazarların kodu çalıştırılmadı.

Kodlar: `sahte_hata_testi.py` (tek deneme), `degerlendirme_v2.py` (10 tohum, eşik analizi).

## 7. Blokzincir ve kanıt

- Zincire ham veri yazılmaz. Her ayın kayıtları için `keccak256` yaprakları ve sıralı çift hash'li bir **Merkle ağacı** kurulur, yalnızca ayın **kökü** ve kayıt sayısı zincire yazılır (2023 için 12 kök).
- Yaprak metni: `tarih|kaynak|tmean|skor|durum`.
- Her kayıt için kanıt dosyası (`merkle_kanitlari_v1.csv`) üretilir; doğrulama kaydın metni ve kanıtından kök hesaplayıp zincirdeki kökle karşılaştırmaktır. Bir kaydın skoru veya değeri sonradan değiştirilirse doğrulama "uyuşmuyor" der.
- Sözleşme: bir ay bir kez yazıldıktan sonra üzerine yazılamaz.

Kodlar: `merkle_kok.py`, `merkle_kanit.py`, `contracts/`.

## 8. Bu sistem ne yapmaz (sınırlılıklar)

- Zincir verinin **doğru** olduğunu kanıtlamaz; yazıldıktan sonra **değişmediğini** gösterir. Yanlış bir skor zincire yazılırsa olduğu gibi kalır.
- Yazma yetkisi şu an tek hesaptadır; çok kurumlu, birbirine güvenmeyen bir doğrulama henüz kurulmadı.
- Blokzincir test ağındadır (Sepolia), gerçek bir ağ değildir.
- Hatalar sentetiktir (kendi eklediğimiz); gerçek sensör hataları farklı davranabilir. Örnek sayısı küçüktür.
- NASA ve ERA5 bağımsız ölçüm değildir; tek gerçek ölçüm kaynağı NOAA'dır. Tek şehir, tek değişken.
- Takılı sensör ve drift en zayıf yakalanan hatalardır. Tahmin modeli ekstrem sıcakları hafife alır.
- Eşikler sabittir; sapma ölçeği 2023 temiz günlerine bakılarak seçilmiştir (etiketli hata verisine bakılmadan).
- Tahmin aralığı, hata eklenen günlerde bile temiz geçmişten hesaplanır.
