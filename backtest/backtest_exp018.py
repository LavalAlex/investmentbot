"""
EXP018  —  ADX regime classifier: does ADX(14) on 1h separate good trades from bad?

Hypothesis:
    The pullback continuation strategy (EXP002) has edge only in trending markets.
    ADX(14) > threshold should select the trending periods and exclude the choppy ones,
    improving PF while the discarded trades should have PF < 1.0.

Variants tested (all with fees 0.05%/side):
    BASE    : no ADX filter          (= EXP017-B for BTC, EXP016A for ETH)
    ADX>20  : only enter when ADX > 20
    ADX>25  : only enter when ADX > 25  (classic threshold)
    ADX>30  : only enter when ADX > 30  (strict)

Assets:
    BTC/USDT — longs only,  SL≥0.30%,  RR=2:1  (EXP017-B params)
    ETH/USDT — longs+shorts, SL≥0.50%,  RR=2:1  (EXP016A params)

Data required:
    data/BTCUSDT_15m_last_730d.csv + data/BTCUSDT_1h_last_740d.csv
    data/ETHUSDT_15m_last_730d.csv + data/ETHUSDT_1h_last_740d.csv

Criteria for KEEP (classifier is useful):
    PF(ADX>25) > PF(BASE)  AND  PF(discarded trades when ADX<25) < 1.0
    Trade count with ADX>25 >= 80 (statistically significant)
"""

import json
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend, is_trend_strong, is_pullback_quality,
    is_entry_trigger, is_candle_quality,
    is_range_sufficient, is_market_efficient,
)
from core.trade_logic import check_exit
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005


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


def run(path_1h: str, path_15m: str, longs_only: bool,
        min_sl_pct: float, rr: float,
        adx_min: float | None = None) -> dict:
    """
    Run backtest. Returns {'kept': [...], 'discarded': [...]}
    'kept'      = trades that passed the ADX filter (or all trades if adx_min is None)
    'discarded' = trades that would have fired but ADX was below threshold
    """
    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)

    equity_kept      = INITIAL_CAPITAL
    equity_discarded = INITIAL_CAPITAL
    position_kept     = None
    position_disc     = None
    trades_kept      = []
    trades_discarded = []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        adx_val    = row.get('adx_1h')
        adx_ok     = (adx_min is None) or (not pd.isna(adx_val) and adx_val >= adx_min)
        adx_reject = (adx_min is not None) and (pd.isna(adx_val) or adx_val < adx_min)

        # ── Check exits ───────────────────────────────────────────────────────
        if position_kept is not None:
            result = check_exit(position_kept['direction'], position_kept['sl'], position_kept['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty = position_kept['qty']
                gross = (exit_price - position_kept['entry']) * qty if position_kept['direction'] == 'long' \
                        else (position_kept['entry'] - exit_price) * qty
                fee     = (position_kept['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity_kept += net_pnl
                trades_kept.append({
                    'open_time':   str(position_kept['open_time']),
                    'close_time':  str(row['open_time']),
                    'direction':   position_kept['direction'],
                    'entry':       position_kept['entry'],
                    'exit':        exit_price,
                    'sl':          position_kept['sl'],
                    'tp':          position_kept['tp'],
                    'sl_dist_pct': position_kept['sl_dist_pct'],
                    'adx_at_entry': position_kept['adx'],
                    'reason':      reason,
                    'gross_pnl':   round(gross, 4),
                    'fee_usd':     round(fee, 4),
                    'pnl':         round(net_pnl, 4),
                    'equity':      round(equity_kept, 4),
                })
                position_kept = None
            continue

        if position_disc is not None:
            result = check_exit(position_disc['direction'], position_disc['sl'], position_disc['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty = position_disc['qty']
                gross = (exit_price - position_disc['entry']) * qty if position_disc['direction'] == 'long' \
                        else (position_disc['entry'] - exit_price) * qty
                fee     = (position_disc['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity_discarded += net_pnl
                trades_discarded.append({
                    'open_time':   str(position_disc['open_time']),
                    'close_time':  str(row['open_time']),
                    'direction':   position_disc['direction'],
                    'entry':       position_disc['entry'],
                    'exit':        exit_price,
                    'sl':          position_disc['sl'],
                    'tp':          position_disc['tp'],
                    'sl_dist_pct': position_disc['sl_dist_pct'],
                    'adx_at_entry': position_disc['adx'],
                    'reason':      reason,
                    'gross_pnl':   round(gross, 4),
                    'fee_usd':     round(fee, 4),
                    'pnl':         round(net_pnl, 4),
                    'equity':      round(equity_discarded, 4),
                })
                position_disc = None
            continue

        # ── Entry signal check ────────────────────────────────────────────────
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

        adx_now = round(float(adx_val), 2) if not pd.isna(adx_val) else None

        pos_data = {
            'open_time':   row['open_time'],
            'direction':   direction,
            'entry':       entry,
            'sl':          sl,
            'tp':          tp,
            'adx':         adx_now,
            'sl_dist_pct': round(sl_dist_pct * 100, 4),
        }

        if adx_ok:
            risk_usd      = equity_kept * RISK_PCT
            pos_data['qty'] = risk_usd / risk_price
            position_kept = pos_data
        elif adx_reject:
            risk_usd      = equity_discarded * RISK_PCT
            pos_data_disc = {**pos_data, 'qty': risk_usd / risk_price}
            position_disc = pos_data_disc

    return {'kept': trades_kept, 'discarded': trades_discarded}


def metrics(trades: list, initial: float = INITIAL_CAPITAL) -> dict:
    if not trades:
        return {}
    df        = pd.DataFrame(trades)
    wins      = df[df['pnl'] > 0]
    losses    = df[df['pnl'] <= 0]
    gp        = wins['pnl'].sum()
    gl        = abs(losses['pnl'].sum())
    pf        = gp / gl if gl > 0 else float('inf')
    total_ret = (df['equity'].iloc[-1] - initial) / initial * 100
    peak, max_dd = initial, 0.0
    eq = initial
    for p in df['pnl']:
        eq += p
        peak   = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(total_ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
        'avg_adx':        round(df['adx_at_entry'].dropna().mean(), 1) if 'adx_at_entry' in df else None,
    }


def regime_split(trades: list) -> dict:
    if not trades:
        return {}
    def _m(subset): return metrics(subset) if subset else {}
    return {
        'bull_2024':     _m([t for t in trades if t['close_time'] < '2024-10-01']),
        'ath_2024_25':   _m([t for t in trades if '2024-10-01' <= t['close_time'] < '2025-04-01']),
        'recovery_2025': _m([t for t in trades if '2025-04-01' <= t['close_time'] < '2025-10-01']),
        'bear_2025_26':  _m([t for t in trades if t['close_time'] >= '2025-10-01']),
    }


ASSET_CONFIGS = {
    'BTC': {
        'path_1h':    'data/BTCUSDT_1h_last_740d.csv',
        'path_15m':   'data/BTCUSDT_15m_last_730d.csv',
        'longs_only': True,
        'min_sl_pct': 0.0030,
        'rr':         2.0,
        'label':      'BTC/USDT — longs only  SL≥0.30%  RR=2:1  (EXP017-B)',
    },
    'ETH': {
        'path_1h':    'data/ETHUSDT_1h_last_740d.csv',
        'path_15m':   'data/ETHUSDT_15m_last_730d.csv',
        'longs_only': False,
        'min_sl_pct': 0.0050,
        'rr':         2.0,
        'label':      'ETH/USDT — longs+shorts  SL≥0.50%  RR=2:1  (EXP016A)',
    },
}

ADX_VARIANTS = {
    'BASE':    None,
    'ADX>20':  20.0,
    'ADX>25':  25.0,
    'ADX>30':  30.0,
}


def print_asset_report(asset: str, cfg: dict, results: dict) -> None:
    vnames = list(ADX_VARIANTS.keys())
    w = 15

    print(f"\n{'='*90}")
    print(f"  EXP018  |  {cfg['label']}")
    print(f"  730 días con fees (0.05%/lado)")
    print(f"{'='*90}")

    # ── Summary table ─────────────────────────────────────────────────────────
    header = f"  {'Métrica':<22}" + ''.join(f"  {v:>{w}}" for v in vnames)
    print(header)
    print(f"  {'-'*85}")

    fields = [
        ('Trades (kept)',   'total_trades',   '{:d}'),
        ('Win rate %',      'win_rate_pct',    '{:.1f}'),
        ('Return %',        'return_pct',      '{:+.2f}'),
        ('Max DD %',        'max_dd_pct',      '{:.2f}'),
        ('Profit factor',   'profit_factor',   '{:.3f}'),
        ('Expectancy $',    'expectancy_usd',  '{:+.2f}'),
        ('Avg ADX entry',   'avg_adx',         '{:.1f}'),
        ('Total fees $',    'total_fees_usd',  '{:.0f}'),
    ]

    for label, key, fmt in fields:
        row = f"  {label:<22}"
        for v in vnames:
            m = results[v]['kept_metrics']
            val = m.get(key, 0) if m else 0
            row += f"  {fmt.format(val):>{w}}"
        print(row)

    # ── Discarded trades (what ADX filtered out) ──────────────────────────────
    print(f"\n  ── TRADES DESCARTADOS (ADX < threshold) — deben tener PF < 1.0 ────────────────")
    disc_header = f"  {'Métrica':<22}" + ''.join(f"  {v:>{w}}" for v in vnames)
    print(disc_header)
    print(f"  {'-'*85}")

    disc_fields = [
        ('Trades (disc.)',  'total_trades',  '{:d}'),
        ('Profit factor',  'profit_factor', '{:.3f}'),
        ('Return %',       'return_pct',    '{:+.2f}'),
        ('Avg ADX entry',  'avg_adx',       '{:.1f}'),
    ]
    for label, key, fmt in disc_fields:
        row = f"  {label:<22}"
        for v in vnames:
            m = results[v]['disc_metrics']
            if v == 'BASE' or not m:
                row += f"  {'—':>{w}}"
            else:
                val = m.get(key, 0) if m else 0
                row += f"  {fmt.format(val):>{w}}"
        print(row)

    # ── Regime breakdown for BASE and ADX>25 ─────────────────────────────────
    print(f"\n  ── DESGLOSE POR RÉGIMEN (BASE vs ADX>25, trades kept) ──────────────────────────")
    regimes = [
        ('bull_2024',     'Bull 2024 (Apr-Sep 24)'),
        ('ath_2024_25',   'ATH 2024-25 (Oct24-Mar25)'),
        ('recovery_2025', 'Recovery 2025 (Apr-Sep 25)'),
        ('bear_2025_26',  'Bear 2025-26 (Oct25-Apr26)'),
    ]
    print(f"  {'Variante':<10}  {'Régimen':<28}  {'T':>4}  {'WR%':>5}  {'PF':>6}  {'Ret%':>7}")
    print(f"  {'-'*70}")
    for v in ['BASE', 'ADX>25']:
        rg = results[v]['regime']
        for rkey, rlabel in regimes:
            rm = rg.get(rkey, {})
            if rm and rm.get('total_trades', 0) > 0:
                print(f"  [{v}]{'':5}  {rlabel:<28}  "
                      f"{rm['total_trades']:>4}  "
                      f"{rm['win_rate_pct']:>4.0f}%  "
                      f"{rm['profit_factor']:>6.3f}  "
                      f"{rm['return_pct']:>+6.1f}%")
            else:
                print(f"  [{v}]{'':5}  {rlabel:<28}  {'—':>4}  {'—':>5}  {'—':>6}  {'—':>7}")

    # ── Verdict ───────────────────────────────────────────────────────────────
    base_pf   = results['BASE']['kept_metrics'].get('profit_factor', 0)
    adx25_pf  = results['ADX>25']['kept_metrics'].get('profit_factor', 0)
    adx25_t   = results['ADX>25']['kept_metrics'].get('total_trades', 0)
    disc25_pf = results['ADX>25']['disc_metrics'].get('profit_factor', 0) if results['ADX>25']['disc_metrics'] else 0

    print(f"\n  ── VEREDICTO ────────────────────────────────────────────────────────────────────")
    print(f"  BASE PF:       {base_pf:.3f}")
    print(f"  ADX>25 PF:     {adx25_pf:.3f}  ({'↑ mejor' if adx25_pf > base_pf else '↓ peor'})")
    print(f"  ADX>25 trades: {adx25_t}  ({'✓ suficiente' if adx25_t >= 80 else '✗ insuficiente (<80)'})")
    print(f"  Discarded PF:  {disc25_pf:.3f}  ({'✓ < 1.0 = clasificador separa correctamente' if disc25_pf < 1.0 else '✗ >= 1.0 = clasificador no discrimina'})")

    if adx25_pf > base_pf and adx25_t >= 80 and disc25_pf < 1.0:
        print(f"\n  ✅  CLASIFICADOR FUNCIONA — ADX>25 mejora PF y descarta trades perdedores")
        print(f"     → Continuar con EXP019 (Strategy B: mean reversion en ADX<20)")
    elif adx25_pf > base_pf and adx25_t >= 80:
        print(f"\n  ⚠️  CLASIFICADOR PARCIAL — ADX>25 mejora PF pero los descartados no son claramente malos")
        print(f"     → Analizar si ADX>20 es mejor threshold, luego continuar con EXP019")
    else:
        print(f"\n  ❌  CLASIFICADOR NO DISCRIMINA — ADX no separa los regímenes correctamente")
        print(f"     → Probar ATR_ratio o volatility ratio como clasificador alternativo")

    print(f"{'='*90}\n")


if __name__ == '__main__':
    print(f"\nEXP018 — ADX regime classifier  |  730d con fees\n")

    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        if not os.path.exists(cfg['path_15m']):
            print(f"[{asset_name}] ERROR: {cfg['path_15m']} no encontrado.")
            print("  Ejecutar: python fetch_all.py --2y")
            continue

        print(f"[{asset_name}] Corriendo variantes...", flush=True)
        asset_results = {}

        for vname, adx_threshold in ADX_VARIANTS.items():
            result = run(
                path_1h   = cfg['path_1h'],
                path_15m  = cfg['path_15m'],
                longs_only = cfg['longs_only'],
                min_sl_pct = cfg['min_sl_pct'],
                rr         = cfg['rr'],
                adx_min    = adx_threshold,
            )
            km = metrics(result['kept'])
            dm = metrics(result['discarded'])
            rg = regime_split(result['kept'])
            asset_results[vname] = {
                'kept_metrics': km,
                'disc_metrics': dm,
                'regime':       rg,
                'trades_kept':  result['kept'],
                'trades_disc':  result['discarded'],
            }
            kept_pf  = km.get('profit_factor', 0) if km else 0
            disc_pf  = dm.get('profit_factor', 0) if dm else 0
            kept_t   = km.get('total_trades', 0) if km else 0
            disc_t   = dm.get('total_trades', 0) if dm else 0
            print(f"  [{vname:8}] kept={kept_t:>3} PF={kept_pf:.3f}  |  "
                  f"disc={disc_t:>3} PF={disc_pf:.3f}")

        all_results[asset_name] = asset_results
        print_asset_report(asset_name, cfg, asset_results)

    # Save results
    out_path = 'data/backtest_exp018.json'
    with open(out_path, 'w') as f:
        json.dump(
            {a: {v: {k: val for k, val in r.items() if k not in ('trades_kept', 'trades_disc')}
                 for v, r in vr.items()}
             for a, vr in all_results.items()},
            f, indent=2, default=str
        )
    print(f"Resultados guardados en {out_path}")
