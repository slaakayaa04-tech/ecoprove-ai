"""
EcoProve AI - Merkle köklerini Sepolia'daki EcoProveRegistry sözleşmesine yazar.

Kullanım (C:\\dev\\ecoprove klasöründe):
  python store_roots.py                               -> sadece planı gösterir, HİÇBİR ŞEY göndermez
  python store_roots.py --send --city TEST --limit 3  -> deneme: ilk 3 ayı 'TEST' şehriyle yazar
  python store_roots.py --send                        -> gerçek: CSV'deki tüm ayları yazar

Gerekenler: python -m pip install web3 python-dotenv pandas
.env dosyasında: PRIVATE_KEY=0x...   (isteğe bağlı: SEPOLIA_RPC_URL=https://...)
Girdi: merkle_kok.py'nin ürettiği CSV. Kabul edilen sütunlar:
  ay, root, count   (arkadaşın merkle_kok.py çıktısı, şehir 'Ankara' kabul edilir)
  city, period, root, count
Dosya adı varsayılan olarak merkle_kokleri.csv; farklıysa --csv merkle_roots.csv
"""
import argparse
import os
import re
import sys
import time

import pandas as pd
from dotenv import load_dotenv
from web3 import Web3

CONTRACT = "0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89"
CHAIN_ID = 11155111
DEFAULT_RPC = "https://ethereum-sepolia-rpc.publicnode.com"

ABI = [
    {"type": "function", "name": "owner", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "storeRoot", "stateMutability": "nonpayable",
     "inputs": [{"name": "city", "type": "string"},
                {"name": "period", "type": "string"},
                {"name": "root", "type": "bytes32"},
                {"name": "count", "type": "uint32"}],
     "outputs": []},
    {"type": "function", "name": "getRoot", "stateMutability": "view",
     "inputs": [{"name": "city", "type": "string"},
                {"name": "period", "type": "string"}],
     "outputs": [{"name": "root", "type": "bytes32"},
                 {"name": "count", "type": "uint32"},
                 {"name": "timestamp", "type": "uint64"}]},
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="merkle_kokleri.csv")
    ap.add_argument("--city", default=None,
                    help="CSV'deki şehir yerine bu adı kullan (deneme için TEST)")
    ap.add_argument("--limit", type=int, default=None, help="sadece ilk N satır")
    ap.add_argument("--send", action="store_true", help="gerçekten gönder")
    args = ap.parse_args()

    load_dotenv()
    key = os.getenv("PRIVATE_KEY", "").strip().strip('"').strip("'")
    if not key:
        sys.exit(".env içinde PRIVATE_KEY bulunamadı.")
    if not key.startswith("0x"):
        key = "0x" + key
    rpc = os.getenv("SEPOLIA_RPC_URL", "").strip() or DEFAULT_RPC

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        sys.exit("RPC adresine bağlanılamadı.")
    if w3.eth.chain_id != CHAIN_ID:
        sys.exit(f"Yanlış ağ: {w3.eth.chain_id} (Sepolia 11155111 olmalı)")

    acct = w3.eth.account.from_key(key)
    c = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT), abi=ABI)
    owner = c.functions.owner().call()
    bal = w3.from_wei(w3.eth.get_balance(acct.address), "ether")
    print(f"Cüzdan          : {acct.address}  ({bal:.4f} test ETH)")
    print(f"Sözleşme sahibi : {owner}")
    if owner.lower() != acct.address.lower():
        sys.exit("Bu cüzdan sözleşmenin sahibi değil, yazamaz.")
    if bal < 0.01:
        print("UYARI: Bakiye düşük, faucet'ten test ETH alın.")

    df = pd.read_csv(args.csv)
    # Arkadaşın merkle_kok.py çıktısı: sütunlar ay, root, count (şehir sütunu yok)
    if "period" not in df.columns and "ay" in df.columns:
        df = df.rename(columns={"ay": "period"})
    if "city" not in df.columns:
        df["city"] = "Ankara"
    need = {"city", "period", "root", "count"}
    if not need.issubset(df.columns):
        sys.exit(f"CSV'de şu sütunlar olmalı: {sorted(need)}. Bulunan: {list(df.columns)}")
    if args.limit:
        df = df.head(args.limit)

    todo = []
    for _, r in df.iterrows():
        city = args.city or str(r["city"])
        period = str(r["period"])
        root = str(r["root"]).strip()
        count = int(r["count"])
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", root):
            sys.exit(f"Geçersiz kök biçimi: {root}")
        try:
            on_root, on_count, _ = c.functions.getRoot(city, period).call()
            if Web3.to_hex(on_root).lower() == root.lower():
                print(f"[atla]   {city} {period}: zincirde zaten var (aynı kök)")
            else:
                print(f"[UYARI]  {city} {period}: zincirde FARKLI bir kök var, atlandı")
        except Exception as e:
            if "not found" in str(e):
                todo.append((city, period, root, count))
            else:
                raise

    print(f"\nYazılacak kayıt sayısı: {len(todo)}")
    for city, period, root, count in todo:
        print(f"  {city} {period}  count={count}  {root[:12]}...")

    if not args.send:
        print("\nBu bir denemeydi, hiçbir şey gönderilmedi. Yazmak için --send ekleyin.")
        return
    if not todo:
        print("Yazılacak yeni kayıt yok.")
        return

    # Not: MetaMask akıllı hesap (delegasyon) kullanan hesaplarda ağ, aynı anda
    # bekleyen yalnızca 1 işleme izin veriyor. Bu yüzden her işlemden sonra biraz
    # bekliyor, "in-flight" hatasında da tekrar deniyoruz.
    for city, period, root, count in todo:
        h = None
        for attempt in range(1, 9):
            try:
                tx = c.functions.storeRoot(
                    city, period, Web3.to_bytes(hexstr=root), count
                ).build_transaction({
                    "from": acct.address,
                    "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
                    "chainId": CHAIN_ID,
                })
                signed = acct.sign_transaction(tx)
                raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
                h = w3.eth.send_raw_transaction(raw)
                break
            except Exception as e:
                err_s = str(e).lower()
                if any(k in err_s for k in ["in-flight", "nonce", "underpriced", "replacement", "timeout", "502", "503", "429"]) and attempt < 8:
                    print(f"[bekle]  {city} {period}: ağ önceki işlemi tamamlıyor, "
                          f"10 sn sonra tekrar ({attempt}/8)", flush=True)
                    time.sleep(10)
                    continue
                raise
        rc = w3.eth.wait_for_transaction_receipt(h, timeout=240)
        link = f"https://sepolia.etherscan.io/tx/{Web3.to_hex(h)}"
        if rc.status == 1:
            print(f"[yazıldı] {city} {period}  {link}", flush=True)
        else:
            sys.exit(f"[HATA] {city} {period} başarısız: {link}")
        time.sleep(2)

    print("\nBitti.")


if __name__ == "__main__":
    main()
