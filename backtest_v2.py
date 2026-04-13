"""
EXP001-v2 — Pullback Continuation System (Baseline)

Strategy family : pullback continuation
Entry logic     : 1h trend via EMA20 slope → pullback to EMA20 → 15m trigger candle
Exit logic      : SL at trigger candle extreme, TP at 2× risk (R:R = 2:1)
Filters         : none (baseline)
Position sizing : 1% equity risk per trade
"""

import sys
import json
import pandas as pd

from strategy_pullback import prepare_1h, prepare_15m, align_1h_to_15m, get_trend, is_pullback, is_entry_trigger
from trade_logic import calculate_sl_tp, check_exit
from logger_v2 import setup_logger, log_open, log_close

# ── Config ───────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 10_000.0
RISK_PCT = 0.01   # 1% of equity risked per trade
MIN_RISK_PRICE = 1.0  # minimum SL distance in USD (avoid degenerate trades)


# ── Data loading ─────────────────────────────────────────────────────────────

def load_data(path_1h: str, path_15m: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_1h = pd.read_csv(path_1h, parse_dates=['open_time'])
    df_15m = pd.read_csv(path_15m, parse_dates=['open_time'])
    df_1h.sort_values('open_time', inplace=True)
    df_15m.sort_values('open_time', inplace=True)
    df_1h.reset_index(drop=True, inplace=True)
    df_15m.reset_index(drop=True, inplace=True)
    return df_1h, df_15m


# ── Execution loop ────────────────────────────────────────────────────────────

def run_backtest(path_1h: str, path_15m: str, label: str = 'in_sample') -> dict:
    log_file = f'logs/backtest_{label}.log'
    logger = setup_logger(f'bt_{label}', log_file=log_file)

    logger.info(f"\n{'='*60}")
    logger.info(f"EXP001-v2  |  {label.upper()}")
    logger.info(f"1h data  : {path_1h}")
    logger.info(f"15m data : {path_15m}")
    logger.info(f"{'='*60}\n")

    df_1h, df_15m = load_data(path_1h, path_15m)
    df_1h_prep = prepare_1h(df_1h)
    df_15m_prep = prepare_15m(df_15m)

    # Align 1h context onto each 15m bar (no look-ahead)
    df = align_1h_to_15m(df_15m_prep, df_1h_prep)

    equity = INITIAL_CAPITAL
    position = None   # None or dict
    trades = []
    equity_curve = []  # (ts, equity) after each bar

    for _, row in df.iterrows():
        ts = row['open_time']

        # ── Check exit if in a position ───────────────────────────────────
        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result

                if position['direction'] == 'long':
                    pnl = (exit_price - position['entry']) * position['qty']
                else:
                    pnl = (position['entry'] - exit_price) * position['qty']

                equity += pnl

                log_close(logger, position['direction'], position['entry'], exit_price, reason, pnl, equity)

                trades.append({
                    'open_ts': position['open_ts'],
                    'close_ts': str(ts),
                    'direction': position['direction'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'sl': position['sl'],
                    'tp': position['tp'],
                    'reason': reason,
                    'pnl': round(pnl, 4),
                    'equity': round(equity, 4),
                })

                position = None

            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue  # never enter a new trade on the same bar as an exit (or while open)

        # ── Check entry ───────────────────────────────────────────────────
        trend = get_trend(row)
        if trend is None:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_pullback(row):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_entry_trigger(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        # Signal confirmed — size and open trade
        entry = row['close']
        direction = 'long' if trend == 'up' else 'short'

        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        risk_price = abs(entry - sl)
        if risk_price < MIN_RISK_PRICE:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        risk_usd = equity * RISK_PCT
        qty = risk_usd / risk_price

        position = {
            'direction': direction,
            'entry': entry,
            'sl': sl,
            'tp': tp,
            'qty': qty,
            'open_ts': str(ts),
        }

        log_open(logger, direction, ts, entry, sl, tp)
        equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})

    # Force-close any open position at last bar price
    if position is not None:
        last_row = df.iloc[-1]
        exit_price = last_row['close']
        if position['direction'] == 'long':
            pnl = (exit_price - position['entry']) * position['qty']
        else:
            pnl = (position['entry'] - exit_price) * position['qty']
        equity += pnl
        log_close(logger, position['direction'], position['entry'], exit_price, 'END', pnl, equity)
        trades.append({
            'open_ts': position['open_ts'],
            'close_ts': str(last_row['open_time']),
            'direction': position['direction'],
            'entry': position['entry'],
            'exit': exit_price,
            'sl': position['sl'],
            'tp': position['tp'],
            'reason': 'END',
            'pnl': round(pnl, 4),
            'equity': round(equity, 4),
        })

    metrics = compute_metrics(trades, INITIAL_CAPITAL, equity)
    print_summary(logger, metrics, label)

    return {
        'label': label,
        'metrics': metrics,
        'trades': trades,
        'equity_curve': equity_curve,
    }


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(trades: list, initial_capital: float, final_equity: float) -> dict:
    if not trades:
        return {'total_trades': 0, 'note': 'no trades generated'}

    df = pd.DataFrame(trades)
    df['close_ts'] = pd.to_datetime(df['close_ts'])
    df['month'] = df['close_ts'].dt.tz_localize(None).dt.to_period('M').astype(str)

    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]

    win_rate = len(wins) / len(df) * 100
    total_return = (final_equity - initial_capital) / initial_capital * 100
    gross_profit = wins['pnl'].sum() if len(wins) > 0 else 0.0
    gross_loss = abs(losses['pnl'].sum()) if len(losses) > 0 else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    expectancy = df['pnl'].mean()

    # Max drawdown from equity column
    peak = initial_capital
    max_dd = 0.0
    for eq in df['equity']:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Consecutive losses
    max_consec_loss = 0
    current_streak = 0
    for pnl in df['pnl']:
        if pnl <= 0:
            current_streak += 1
            max_consec_loss = max(max_consec_loss, current_streak)
        else:
            current_streak = 0

    # Directional breakdown
    long_df = df[df['direction'] == 'long']
    short_df = df[df['direction'] == 'short']

    # Monthly breakdown
    monthly = (
        df.groupby('month')['pnl']
        .agg(trades='count', net_pnl='sum', wins=lambda x: (x > 0).sum())
        .reset_index()
    )
    monthly['win_rate'] = (monthly['wins'] / monthly['trades'] * 100).round(1)
    monthly['net_pnl'] = monthly['net_pnl'].round(2)
    monthly_list = monthly.to_dict(orient='records')

    return {
        'total_trades': len(df),
        'win_rate_pct': round(win_rate, 1),
        'total_return_pct': round(total_return, 2),
        'final_equity': round(final_equity, 2),
        'max_drawdown_pct': round(max_dd, 2),
        'profit_factor': round(profit_factor, 3),
        'expectancy_usd': round(expectancy, 2),
        'gross_profit': round(gross_profit, 2),
        'gross_loss': round(gross_loss, 2),
        'max_consec_losses': max_consec_loss,
        'long_trades': len(long_df),
        'short_trades': len(short_df),
        'long_pnl': round(long_df['pnl'].sum(), 2) if len(long_df) > 0 else 0.0,
        'short_pnl': round(short_df['pnl'].sum(), 2) if len(short_df) > 0 else 0.0,
        'monthly': monthly_list,
    }


def print_summary(logger, metrics: dict, label: str) -> None:
    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY — {label.upper()}")
    logger.info(f"{'='*60}")
    if metrics.get('total_trades', 0) == 0:
        logger.info("No trades generated.")
        return
    logger.info(f"Total trades       : {metrics['total_trades']}")
    logger.info(f"  Long             : {metrics['long_trades']}")
    logger.info(f"  Short            : {metrics['short_trades']}")
    logger.info(f"Win rate           : {metrics['win_rate_pct']}%")
    logger.info(f"Total return       : {metrics['total_return_pct']}%")
    logger.info(f"Final equity       : {metrics['final_equity']} USD")
    logger.info(f"Max drawdown       : {metrics['max_drawdown_pct']}%")
    logger.info(f"Profit factor      : {metrics['profit_factor']}")
    logger.info(f"Expectancy         : {metrics['expectancy_usd']} USD/trade")
    logger.info(f"Max consec. losses : {metrics['max_consec_losses']}")
    logger.info(f"Long PnL           : {metrics['long_pnl']} USD")
    logger.info(f"Short PnL          : {metrics['short_pnl']} USD")
    logger.info(f"\nMonthly breakdown:")
    for m in metrics.get('monthly', []):
        logger.info(
            f"  {m['month']}  trades={m['trades']:>3}  "
            f"win%={m['win_rate']:>5.1f}  net={m['net_pnl']:>+9.2f} USD"
        )
    logger.info(f"{'='*60}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def save_results(result: dict, out_prefix: str) -> None:
    # Equity curve CSV
    eq_path = f'data/equity_curve_{out_prefix}.csv'
    pd.DataFrame(result['equity_curve']).to_csv(eq_path, index=False)

    # Full results JSON (metrics + trades)
    json_path = f'data/backtest_{out_prefix}.json'
    with open(json_path, 'w') as f:
        json.dump({'metrics': result['metrics'], 'trades': result['trades']}, f, indent=2)

    print(f"Saved: {eq_path}")
    print(f"Saved: {json_path}")


if __name__ == '__main__':
    # ── In-sample ─────────────────────────────────────────────────────────
    is_result = run_backtest(
        path_1h='data/BTCUSDT_1h_last_200d.csv',
        path_15m='data/BTCUSDT_15m_last_180d.csv',
        label='in_sample',
    )
    save_results(is_result, 'exp001v2_in_sample')

    # ── Out-of-sample ─────────────────────────────────────────────────────
    oos_result = run_backtest(
        path_1h='data/BTCUSDT_1h_oos_200d.csv',
        path_15m='data/BTCUSDT_15m_oos_180d.csv',
        label='out_of_sample',
    )
    save_results(oos_result, 'exp001v2_out_of_sample')
