"""
fetch_all.py — Descarga datos históricos de Binance para BTC/USDT y ETH/USDT.

Descarga:
  BTC/USDT: 15m (180d), 1h (200d)
  ETH/USDT: 15m (180d), 1h (200d)

Uso:
    python fetch_all.py           # descarga todo
    python fetch_all.py --recent  # solo últimos 14d de 15m + 60d de 1h (rápido)

Los archivos se guardan en data/ con el mismo formato que fetch_history.py.
"""

import csv
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.exchange import create_exchange

OUTPUT_DIR = Path('data')
COLUMNS = [
    'open_time', 'open', 'high', 'low', 'close', 'volume',
    'close_time', 'quote_volume', 'trade_count',
    'taker_buy_base_volume', 'taker_buy_quote_volume',
]

CONFIGS = [
    # symbol_raw, interval, days, filename
    ('BTCUSDT', '15m', 180, 'BTCUSDT_15m_last_180d.csv'),
    ('BTCUSDT', '1h',  200, 'BTCUSDT_1h_last_200d.csv'),
    ('ETHUSDT', '15m', 180, 'ETHUSDT_15m_last_180d.csv'),
    ('ETHUSDT', '1h',  200, 'ETHUSDT_1h_last_200d.csv'),
]

CONFIGS_RECENT = [
    ('BTCUSDT', '15m',  14, 'BTCUSDT_15m_recent.csv'),
    ('BTCUSDT', '1h',   60, 'BTCUSDT_1h_recent.csv'),
    ('ETHUSDT', '15m',  14, 'ETHUSDT_15m_recent.csv'),
    ('ETHUSDT', '1h',   60, 'ETHUSDT_1h_recent.csv'),
]

# 370 días: cubre Apr 2025 → Apr 2026 (ciclo completo bull recovery + bear)
CONFIGS_EXTENDED = [
    ('BTCUSDT', '15m', 370, 'BTCUSDT_15m_last_370d.csv'),
    ('BTCUSDT', '1h',  380, 'BTCUSDT_1h_last_380d.csv'),
    ('ETHUSDT', '15m', 370, 'ETHUSDT_15m_last_370d.csv'),
    ('ETHUSDT', '1h',  380, 'ETHUSDT_1h_last_380d.csv'),
]

# 730 días: cubre Apr 2024 → Apr 2026 (bull 2024 + recovery 2025 + bear 2025-26)
CONFIGS_2Y = [
    ('BTCUSDT', '15m', 730, 'BTCUSDT_15m_last_730d.csv'),
    ('BTCUSDT', '1h',  740, 'BTCUSDT_1h_last_740d.csv'),
    ('ETHUSDT', '15m', 730, 'ETHUSDT_15m_last_730d.csv'),
    ('ETHUSDT', '1h',  740, 'ETHUSDT_1h_last_740d.csv'),
]


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def fetch_candles(exchange, symbol_raw: str, interval: str, days: int) -> list[dict]:
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    print(f'  [{symbol_raw} {interval} {days}d] fetching from Binance...', end='', flush=True)

    all_rows   = []
    batch_start = since_ms

    while batch_start < now_ms:
        raw = exchange.publicGetKlines({
            'symbol':    symbol_raw,
            'interval':  interval,
            'startTime': batch_start,
            'limit':     1000,
        })
        if not raw:
            break
        for e in raw:
            all_rows.append({
                'open_time':              ms_to_iso(int(e[0])),
                'open':                   float(e[1]),
                'high':                   float(e[2]),
                'low':                    float(e[3]),
                'close':                  float(e[4]),
                'volume':                 float(e[5]),
                'close_time':             ms_to_iso(int(e[6])),
                'quote_volume':           float(e[7]),
                'trade_count':            int(e[8]),
                'taker_buy_base_volume':  float(e[9]),
                'taker_buy_quote_volume': float(e[10]),
            })
        if len(raw) < 1000:
            break
        batch_start = int(raw[-1][0]) + 1

    # Dedup and sort
    seen = set()
    unique = []
    for row in all_rows:
        if row['open_time'] not in seen:
            seen.add(row['open_time'])
            unique.append(row)
    unique.sort(key=lambda r: r['open_time'])

    first = unique[0]['open_time'][:10] if unique else '?'
    last  = unique[-1]['open_time'][:10] if unique else '?'
    print(f' {len(unique)} candles ({first} → {last})')
    return unique


def save_csv(rows: list[dict], path: Path) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f'  Saved → {path}')


def main():
    parser = argparse.ArgumentParser(description='Descarga datos históricos de Binance')
    parser.add_argument('--recent', action='store_true',
                        help='Descarga solo los últimos 14d (15m) y 60d (1h) — más rápido')
    parser.add_argument('--extended', action='store_true',
                        help='Descarga 370d BTC+ETH — ciclo completo Apr 2025 → Apr 2026')
    parser.add_argument('--2y', dest='two_years', action='store_true',
                        help='Descarga 730d BTC+ETH — bull 2024 + recovery 2025 + bear 2025-26')
    args = parser.parse_args()

    exchange = create_exchange()
    if args.recent:
        configs = CONFIGS_RECENT
        label   = 'datos recientes (14d/60d)'
    elif args.extended:
        configs = CONFIGS_EXTENDED
        label   = 'histórico extendido (370d — ciclo completo)'
    elif args.two_years:
        configs = CONFIGS_2Y
        label   = '2 años (730d — bull 2024 + recovery 2025 + bear 2025-26)'
    else:
        configs = CONFIGS
        label   = 'histórico estándar (180d/200d)'

    print(f'\nDescargando {label} de Binance...\n')

    for symbol_raw, interval, days, filename in configs:
        rows = fetch_candles(exchange, symbol_raw, interval, days)
        if rows:
            save_csv(rows, OUTPUT_DIR / filename)

    print('\nListo.\n')
    if args.extended:
        print('  Datos disponibles para EXP017 (BTC 12 meses con fees):')
        print('  python backtest/backtest_exp017.py')


if __name__ == '__main__':
    main()
