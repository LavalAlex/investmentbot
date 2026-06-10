"""
analyze_30d.py — Análisis comparativo: órdenes reales Binance Futures vs señales del modelo

Pasos:
1. Descarga OHLCV fresco (35d 15m + 40d 1h) para BTC y ETH
2. Descarga historial de trades reales de Binance Futures (últimos 30d)
3. Corre el modelo (config producción: BTC EXP017-B, ETH EXP016A)
4. Filtra señales a los últimos 30d
5. Compara señales vs trades reales y genera resumen

Uso:
    python analyze_30d.py
"""

import sys
import os
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.exchange import create_futures_exchange, create_exchange
from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend, is_trend_strong, is_pullback_quality,
    is_entry_trigger, is_candle_quality,
    is_range_sufficient, is_market_efficient,
)
from core.trade_logic import check_exit

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

DAYS_ANALYSIS = 30
DAYS_WARMUP   = 40   # 1h data (indicator warmup)
DAYS_15M      = 35   # 15m data

BTC_CONFIG = {'longs_only': True,  'min_sl_pct': 0.0030, 'rr': 2.0, 'label': 'EXP017-B'}
ETH_CONFIG = {'longs_only': False, 'min_sl_pct': 0.0050, 'rr': 2.0, 'label': 'EXP016A'}

DATA_DIR = Path('data')


# ─── 1. FETCH OHLCV ──────────────────────────────────────────────────────────

def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def fetch_candles(exchange, symbol_raw: str, interval: str, days: int) -> list[dict]:
    columns = [
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trade_count',
        'taker_buy_base_volume', 'taker_buy_quote_volume',
    ]
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    print(f'  [{symbol_raw} {interval} {days}d] descargando...', end='', flush=True)
    all_rows, batch_start = [], since_ms

    while batch_start < now_ms:
        raw = exchange.publicGetKlines({
            'symbol': symbol_raw, 'interval': interval,
            'startTime': batch_start, 'limit': 1000,
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

    seen, unique = set(), []
    for row in all_rows:
        if row['open_time'] not in seen:
            seen.add(row['open_time'])
            unique.append(row)
    unique.sort(key=lambda r: r['open_time'])

    first = unique[0]['open_time'][:10] if unique else '?'
    last  = unique[-1]['open_time'][:10] if unique else '?'
    print(f' {len(unique)} velas ({first} → {last})')
    return unique


def save_temp_csv(rows: list[dict], path: Path) -> None:
    columns = [
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trade_count',
        'taker_buy_base_volume', 'taker_buy_quote_volume',
    ]
    DATA_DIR.mkdir(exist_ok=True)
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def refresh_data(spot_exchange) -> dict:
    """Descarga OHLCV fresco y devuelve rutas de archivos."""
    print('\n── 1. Descargando datos OHLCV frescos ──')
    files = {}
    for symbol, label in [('BTCUSDT', 'BTC'), ('ETHUSDT', 'ETH')]:
        p_1h  = DATA_DIR / f'{symbol}_1h_fresh_{DAYS_WARMUP}d.csv'
        p_15m = DATA_DIR / f'{symbol}_15m_fresh_{DAYS_15M}d.csv'
        rows_1h  = fetch_candles(spot_exchange, symbol, '1h',  DAYS_WARMUP)
        rows_15m = fetch_candles(spot_exchange, symbol, '15m', DAYS_15M)
        save_temp_csv(rows_1h,  p_1h)
        save_temp_csv(rows_15m, p_15m)
        files[label] = {'1h': p_1h, '15m': p_15m}
    return files


# ─── 2. FETCH FUTURES TRADES ─────────────────────────────────────────────────

def fetch_futures_trades(futures_exchange, symbol: str, days: int) -> list[dict]:
    """Descarga historial de trades reales de Binance USDM Futures."""
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    trades = []
    try:
        raw = futures_exchange.fapiPrivateGetUserTrades({
            'symbol':    symbol.replace('/', ''),
            'startTime': since_ms,
            'limit':     1000,
        })
        for t in raw:
            trades.append({
                'symbol':     t.get('symbol'),
                'order_id':   t.get('orderId'),
                'trade_id':   t.get('id'),
                'side':       t.get('side', '').lower(),
                'price':      float(t.get('price', 0)),
                'qty':        float(t.get('qty', 0)),
                'realized_pnl': float(t.get('realizedPnl', 0)),
                'commission': float(t.get('commission', 0)),
                'position_side': t.get('positionSide', ''),
                'maker':      t.get('maker', False),
                'time':       ms_to_iso(int(t.get('time', 0))),
                'quote_qty':  float(t.get('quoteQty', 0)),
            })
        trades.sort(key=lambda x: x['time'])
    except Exception as e:
        print(f'  ERROR fetching {symbol} trades: {e}')
    return trades


def fetch_all_futures_orders(futures_exchange) -> dict:
    print('\n── 2. Descargando órdenes reales de Binance Futures ──')
    result = {}
    for symbol in ['BTCUSDT', 'ETHUSDT']:
        print(f'  {symbol}...', end='', flush=True)
        trades = fetch_futures_trades(futures_exchange, symbol, DAYS_ANALYSIS)
        print(f' {len(trades)} trades encontrados')
        result[symbol] = trades
    return result


# ─── 3. CORRER MODELO ────────────────────────────────────────────────────────

def calculate_sl_tp(entry, direction, candle_low, candle_high, rr: float):
    if direction == 'long':
        sl   = candle_low
        risk = entry - sl
        if risk <= 0:
            return None, None
        tp = entry + rr * risk
    else:
        sl   = candle_high
        risk = sl - entry
        if risk <= 0:
            return None, None
        tp = entry - rr * risk
    return sl, tp


def run_model(path_1h: str, path_15m: str, config: dict) -> list[dict]:
    """Corre el modelo pullback y retorna lista de trades (con señales dentro de últimos 30d)."""
    df_1h_raw  = pd.read_csv(path_1h,  parse_dates=['open_time'])
    df_15m_raw = pd.read_csv(path_15m, parse_dates=['open_time'])
    df_1h_raw.sort_values('open_time', inplace=True)
    df_15m_raw.sort_values('open_time', inplace=True)

    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)

    longs_only = config['longs_only']
    min_sl_pct = config['min_sl_pct']
    rr         = config['rr']

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=DAYS_ANALYSIS)
    equity    = INITIAL_CAPITAL
    position  = None
    trades    = []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty      = position['qty']
                gross    = ((exit_price - position['entry']) * qty
                            if position['direction'] == 'long'
                            else (position['entry'] - exit_price) * qty)
                fee      = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl  = gross - fee
                equity  += net_pnl
                open_ts  = pd.to_datetime(position['open_time'], utc=True)
                # Solo guardamos si la apertura fue dentro de los últimos 30d
                if open_ts >= cutoff_dt.replace(tzinfo=timezone.utc):
                    trades.append({
                        'open_time':   str(position['open_time']),
                        'close_time':  str(row['open_time']),
                        'direction':   position['direction'],
                        'entry':       round(position['entry'], 4),
                        'exit':        round(exit_price, 4),
                        'sl':          round(position['sl'], 4),
                        'tp':          round(position['tp'], 4),
                        'sl_dist_pct': position['sl_dist_pct'],
                        'qty':         round(qty, 6),
                        'reason':      reason,
                        'gross_pnl':   round(gross, 4),
                        'fee_usd':     round(fee, 4),
                        'pnl':         round(net_pnl, 4),
                        'equity':      round(equity, 4),
                    })
                position = None
            continue

        trend = get_trend(row)
        if trend is None:
            continue
        if longs_only and trend != 'up':
            continue
        if not is_trend_strong(row):
            continue
        if not is_pullback_quality(row, trend):
            continue
        if not is_entry_trigger(row, trend):
            continue
        if not is_candle_quality(row, trend):
            continue
        if not is_range_sufficient(row):
            continue
        if not is_market_efficient(row):
            continue

        direction = 'long' if trend == 'up' else 'short'
        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'], rr)
        if sl is None:
            continue
        risk_price  = abs(entry - sl)
        sl_dist_pct = risk_price / entry
        if sl_dist_pct < min_sl_pct:
            continue

        risk_usd = equity * RISK_PCT
        position = {
            'open_time':   row['open_time'],
            'direction':   direction,
            'entry':       entry,
            'sl':          sl,
            'tp':          tp,
            'qty':         risk_usd / risk_price,
            'sl_dist_pct': round(sl_dist_pct * 100, 4),
        }

    return trades


def run_all_models(files: dict) -> dict:
    print('\n── 3. Corriendo modelos (señales últimos 30d) ──')
    results = {}
    for asset, cfg in [('BTC', BTC_CONFIG), ('ETH', ETH_CONFIG)]:
        print(f'  {asset} ({cfg["label"]})...')
        trades = run_model(
            path_1h=str(files[asset]['1h']),
            path_15m=str(files[asset]['15m']),
            config=cfg,
        )
        print(f'    → {len(trades)} trades generados')
        results[asset] = trades
    return results


# ─── 4. COMPARACIÓN Y RESUMEN ────────────────────────────────────────────────

def metrics_summary(trades: list) -> dict:
    if not trades:
        return {'trades': 0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum()
    gl   = abs(loss['pnl'].sum())
    return {
        'trades':         len(df),
        'wins':           len(wins),
        'losses':         len(loss),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'net_pnl_usd':    round(df['pnl'].sum(), 2),
        'gross_pnl_usd':  round(df['gross_pnl'].sum(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
        'profit_factor':  round(gp / gl, 3) if gl > 0 else float('inf'),
        'avg_pnl_usd':    round(df['pnl'].mean(), 2),
        'tp_exits':       len(df[df['reason'] == 'TP']),
        'sl_exits':       len(df[df['reason'] == 'SL']),
    }


def real_orders_summary(trades: list) -> dict:
    if not trades:
        return {'trades': 0}
    df = pd.DataFrame(trades)
    total_pnl  = round(df['realized_pnl'].sum(), 4)
    total_comm = round(df['commission'].sum(), 4)
    buys  = df[df['side'] == 'buy']
    sells = df[df['side'] == 'sell']
    total_vol = round(df['quote_qty'].sum(), 2)
    return {
        'trades':          len(df),
        'buys':            len(buys),
        'sells':           len(sells),
        'realized_pnl':    total_pnl,
        'total_commission':total_comm,
        'net_after_fees':  round(total_pnl - total_comm, 4),
        'volume_usdt':     total_vol,
        'first_trade':     df['time'].min()[:16],
        'last_trade':      df['time'].max()[:16],
    }


def compare_and_print(real_orders: dict, model_trades: dict) -> None:
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    cutoff  = (datetime.now(timezone.utc) - timedelta(days=DAYS_ANALYSIS)).strftime('%Y-%m-%d')

    print(f'\n{"═"*80}')
    print(f'  ANÁLISIS COMPARATIVO: ÓRDENES REALES vs SEÑALES DEL MODELO')
    print(f'  Período: {cutoff} → {now_str[:10]}  ({DAYS_ANALYSIS} días)')
    print(f'{"═"*80}')

    for asset, symbol in [('BTC', 'BTCUSDT'), ('ETH', 'ETHUSDT')]:
        cfg     = BTC_CONFIG if asset == 'BTC' else ETH_CONFIG
        real    = real_orders.get(symbol, [])
        signals = model_trades.get(asset, [])
        r_sum   = real_orders_summary(real)
        m_sum   = metrics_summary(signals)

        print(f'\n{"─"*80}')
        print(f'  {asset}/USDT  |  Config producción: {cfg["label"]}')
        print(f'  {"SL≥" + str(int(cfg["min_sl_pct"]*100*10)/10) + "%  RR=" + str(int(cfg["rr"])) + ":1":<30} Longs only: {cfg["longs_only"]}')
        print(f'{"─"*80}')

        print(f'\n  [A] ÓRDENES REALES EN BINANCE FUTURES')
        if r_sum['trades'] == 0:
            print('      Sin actividad en este período.')
        else:
            print(f'      Trades ejecutados:   {r_sum["trades"]:>6}  (buys: {r_sum["buys"]}, sells: {r_sum["sells"]})')
            print(f'      Volumen operado:     ${r_sum["volume_usdt"]:>12,.2f} USDT')
            print(f'      PnL realizado:       ${r_sum["realized_pnl"]:>+10.4f}')
            print(f'      Comisiones pagadas:  ${r_sum["total_commission"]:>10.4f}')
            print(f'      Neto tras fees:      ${r_sum["net_after_fees"]:>+10.4f}')
            print(f'      Rango temporal:      {r_sum["first_trade"]} → {r_sum["last_trade"]}')

        print(f'\n  [B] SEÑALES DEL MODELO (backtest sobre mismos 30d)')
        if m_sum['trades'] == 0:
            print('      Sin señales generadas en este período.')
        else:
            print(f'      Trades generados:    {m_sum["trades"]:>6}  (wins: {m_sum["wins"]}, losses: {m_sum["losses"]})')
            print(f'      Win rate:            {m_sum["win_rate_pct"]:>5.1f}%')
            print(f'      Profit Factor:       {m_sum["profit_factor"]:>6.3f}')
            print(f'      PnL neto (modelo):   ${m_sum["net_pnl_usd"]:>+10.2f}')
            print(f'      PnL bruto:           ${m_sum["gross_pnl_usd"]:>+10.2f}')
            print(f'      Fees simulados:      ${m_sum["total_fees_usd"]:>10.2f}')
            print(f'      Avg PnL/trade:       ${m_sum["avg_pnl_usd"]:>+9.2f}')
            print(f'      TP hits / SL hits:   {m_sum["tp_exits"]} TP  /  {m_sum["sl_exits"]} SL')

        print(f'\n  [C] COMPARACIÓN')
        if m_sum['trades'] == 0 and r_sum['trades'] == 0:
            print('      Sin actividad en ninguno de los dos lados.')
        elif m_sum['trades'] == 0:
            print('      El modelo NO generó señales. Las órdenes reales no tienen contrapartida en el modelo.')
            print('      → Posible causa: mercado choppy (ER<0.15), sin tendencia definida, o filtros muy estrictos.')
        elif r_sum['trades'] == 0:
            print('      El modelo generó señales pero NO hay órdenes reales.')
            print('      → El sistema live puede estar en pausa (circuit breaker), o las señales no se ejecutaron.')
        else:
            delta_pnl = r_sum['net_after_fees'] - m_sum['net_pnl_usd']
            print(f'      Señales modelo:      {m_sum["trades"]:>4} trades  |  ${m_sum["net_pnl_usd"]:>+.2f}')
            print(f'      Órdenes reales:      {r_sum["trades"]:>4} fills   |  ${r_sum["net_after_fees"]:>+.4f} neto')
            print(f'      Diferencia PnL:      ${delta_pnl:>+.4f}')
            if abs(r_sum['trades'] - m_sum['trades'] * 2) < m_sum['trades']:
                print(f'      ✓ Actividad real alineada con señales del modelo (aprox. {m_sum["trades"]*2} fills = {m_sum["trades"]} trades)')
            elif r_sum['trades'] > m_sum['trades'] * 3:
                print(f'      ⚠ Más actividad real de la esperada — posibles trades manuales o ajustes de posición')
            else:
                print(f'      ? Divergencia en volumen de actividad — revisar logs para detalles')

        # Detalle de señales del modelo
        if signals:
            print(f'\n  [D] DETALLE SEÑALES MODELO {asset}')
            print(f'      {"Apertura":<20} {"Dir":<6} {"Entry":>10} {"SL":>10} {"TP":>10} {"Razón":<6} {"PnL":>8}')
            print(f'      {"─"*75}')
            for t in signals:
                print(f'      {t["open_time"][:16]:<20} {t["direction"]:<6} {t["entry"]:>10.2f} '
                      f'{t["sl"]:>10.2f} {t["tp"]:>10.2f} {t["reason"]:<6} ${t["pnl"]:>+8.2f}')

    print(f'\n{"═"*80}')
    print(f'  NOTAS:')
    print(f'  • "Órdenes reales" = fills individuales de Binance USDM Futures (cada entrada/salida = 1 fill)')
    print(f'  • "Señales modelo" = trades completos (entrada + salida = 1 trade)')
    print(f'  • Config BTC: {BTC_CONFIG["label"]} — longs only, SL≥0.30%, RR=2:1')
    print(f'  • Config ETH: {ETH_CONFIG["label"]} — longs+shorts, SL≥0.50%, RR=2:1')
    print(f'{"═"*80}\n')


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print(f'\n{"═"*80}')
    print(f'  analyze_30d.py — Análisis: Binance Futures vs Modelo')
    print(f'  {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}')
    print(f'{"═"*80}')

    spot_exchange    = create_exchange()
    futures_exchange = create_futures_exchange()

    # 1. Datos OHLCV frescos
    files = refresh_data(spot_exchange)

    # 2. Órdenes reales Binance Futures
    real_orders = fetch_all_futures_orders(futures_exchange)

    # 3. Señales del modelo
    model_trades = run_all_models(files)

    # 4. Comparación y reporte
    compare_and_print(real_orders, model_trades)

    # 5. Guardar resultado JSON
    output = {
        'generated_at':  datetime.now(timezone.utc).isoformat(),
        'period_days':   DAYS_ANALYSIS,
        'real_orders':   real_orders,
        'model_trades':  model_trades,
    }
    out_path = Path('data/analysis_30d_result.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f'  Resultado guardado en {out_path}\n')


if __name__ == '__main__':
    main()
