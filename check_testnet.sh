#!/usr/bin/env bash
set -e
source venv/bin/activate
python - <<'EOF'
from dotenv import load_dotenv
load_dotenv(dotenv_path='.env')
import ccxt
from config import BINANCE_API_KEY, BINANCE_SECRET

def check_wallet(label, wallet_type):
    print(f"\n── {label} ──")
    try:
        ex = ccxt.binance({
            "apiKey": BINANCE_API_KEY,
            "secret": BINANCE_SECRET,
            "enableRateLimit": True,
            "options": {"defaultType": wallet_type},
        })
        b = ex.fetch_balance()
        found = False
        for asset, info in b.items():
            if isinstance(info, dict):
                total = info.get('total') or 0
                if total and float(total) > 0:
                    print(f"  {asset}: free={info.get('free')}  total={total}")
                    found = True
        if not found:
            print("  (vacío)")
    except Exception as e:
        print(f"  ERROR: {e}")

check_wallet("FUTURES", "future")
EOF
