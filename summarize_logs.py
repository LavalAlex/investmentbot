"""
summarize_logs.py — Resumen rápido del paper trading activo.

Lee todos los logs en logs/ y paper_state.json, e imprime:
  - Tabla de todos los trades cerrados
  - Métricas globales (equity, WR, PF, return, DD)
  - Posiciones actualmente abiertas

Uso:
    python summarize_logs.py
    python summarize_logs.py --days 7   # solo últimos 7 días de logs
"""

import json
import re
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta


LOG_DIR    = Path('logs')
STATE_FILE = Path('paper_state.json')

OPEN_RE  = re.compile(
    r'\[OPEN\]\s+(\w+)\s+\|\s+ts=([^\|]+)\|\s+entry=([\d.]+)\s+\|\s+sl=([\d.]+)\s+\|\s+tp=([\d.]+)'
)
CLOSE_RE = re.compile(
    r'\[CLOSE\]\s+(\w+)\s+\|\s+entry=([\d.]+)\s+\|\s+exit=([\d.]+)\s+\|\s+reason=(\w+)\s+\|\s+net=([+-][\d.]+)\s+USD\s+\|\s+equity=([\d.]+)'
)


def parse_logs(days: int | None = None) -> list[dict]:
    trades = []
    paper_log_re = re.compile(r'^logs_paper_(\d{8})$')
    log_files = sorted(
        f for f in LOG_DIR.glob('*.log') if paper_log_re.match(f.stem)
    )

    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        log_files = [
            f for f in log_files
            if datetime.strptime(paper_log_re.match(f.stem).group(1), '%Y%m%d').replace(tzinfo=timezone.utc) >= cutoff
        ]

    open_positions: dict[str, dict] = {}

    for log_file in log_files:
        text = log_file.read_text(errors='replace')
        for line in text.splitlines():
            m = OPEN_RE.search(line)
            if m:
                direction, ts, entry, sl, tp = m.groups()
                open_positions[direction] = {
                    'direction': direction.lower(),
                    'open_time': ts.strip(),
                    'entry': float(entry),
                    'sl': float(sl),
                    'tp': float(tp),
                }
                continue
            m = CLOSE_RE.search(line)
            if m:
                direction, entry, exit_p, reason, net, equity = m.groups()
                pos = open_positions.pop(direction, {})
                trades.append({
                    'open_time':  pos.get('open_time', '?'),
                    'direction':  direction.lower(),
                    'entry':      float(entry),
                    'exit':       float(exit_p),
                    'sl':         pos.get('sl'),
                    'tp':         pos.get('tp'),
                    'reason':     reason,
                    'net':        float(net),
                    'equity':     float(equity),
                })

    return trades


def metrics(trades: list[dict]) -> dict:
    if not trades:
        return {}
    wins      = [t for t in trades if t['net'] > 0]
    losses    = [t for t in trades if t['net'] <= 0]
    gross_win = sum(t['net'] for t in wins)
    gross_los = abs(sum(t['net'] for t in losses))
    pf = gross_win / gross_los if gross_los > 0 else float('inf')

    initial = trades[0]['equity'] - trades[0]['net']
    final   = trades[-1]['equity']
    ret_pct = (final - initial) / initial * 100

    peak   = initial
    max_dd = 0.0
    eq     = initial
    for t in trades:
        eq += t['net']
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        max_dd = max(max_dd, dd)

    return {
        'total':     len(trades),
        'wins':      len(wins),
        'losses':    len(losses),
        'win_rate':  len(wins) / len(trades) * 100,
        'pf':        pf,
        'net_usd':   sum(t['net'] for t in trades),
        'return_pct': ret_pct,
        'max_dd':    max_dd,
        'equity':    final,
    }


def print_report(trades: list[dict], days: int | None) -> None:
    period = f'(últimos {days} días)' if days else '(todos los logs)'
    print(f'\n{"="*75}')
    print(f'  PAPER TRADING — RESUMEN DE TRADES  {period}')
    print(f'{"="*75}')

    if not trades:
        print('  No se encontraron trades cerrados.\n')
        return

    # Tabla de trades
    print(f'\n  {"#":>3}  {"Apertura":20}  {"Dir":5}  {"Entry":>10}  {"Exit":>10}  {"Razón":6}  {"Net USD":>9}  {"Equity":>10}')
    print(f'  {"-"*73}')
    for i, t in enumerate(trades, 1):
        ts    = str(t['open_time'])[:16]
        sign  = '+' if t['net'] > 0 else ''
        print(f'  {i:>3}  {ts:20}  {t["direction"].upper():5}  {t["entry"]:>10.2f}  {t["exit"]:>10.2f}  {t["reason"]:6}  {sign}{t["net"]:>8.2f}  {t["equity"]:>10.2f}')

    # Métricas
    m = metrics(trades)
    print(f'\n{"─"*75}')
    print(f'  Trades       : {m["total"]} ({m["wins"]} wins / {m["losses"]} losses)')
    print(f'  Win rate     : {m["win_rate"]:.1f}%')
    print(f'  Profit Factor: {m["pf"]:.3f}')
    print(f'  Net P&L      : {m["net_usd"]:+.2f} USD')
    print(f'  Return       : {m["return_pct"]:+.2f}%')
    print(f'  Max DD       : {m["max_dd"]:.2f}%')
    print(f'  Equity actual: {m["equity"]:.2f} USD')

    # Comparar vs baseline EXP009
    print(f'\n  vs EXP009 backtest:')
    print(f'  {"":2} WR backtest     : BTC 39.4% | ETH 41.1%')
    print(f'  {"":2} PF backtest     : BTC 1.297 | ETH 1.375')
    print(f'  {"":2} Max DD backtest : BTC 7.78% | ETH 10.76%')

    # Estado del motor (paper_state.json)
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        print(f'\n{"─"*75}')
        print(f'  ESTADO LIVE (paper_state.json)')
        print(f'  Equity            : {state.get("equity", "?"):.2f} USD')
        positions = state.get('positions', {})
        if positions:
            print(f'  Posiciones abiertas:')
            for asset, pos in positions.items():
                print(f'    {asset}: {pos.get("direction","?").upper()} | entry={pos.get("entry","?")} | sl={pos.get("sl","?")} | tp={pos.get("tp","?")}')
        else:
            print(f'  Posiciones abiertas: ninguna')
        cb_until = state.get('cb_until')
        if cb_until:
            print(f'  Circuit breaker   : pausado hasta {cb_until}')
        cb_consec = state.get('cb_consecutive_losses', 0)
        if cb_consec:
            print(f'  Pérdidas consecutivas: {cb_consec}')

    print(f'{"="*75}\n')


def main():
    parser = argparse.ArgumentParser(description='Resumen de paper trading')
    parser.add_argument('--days', type=int, default=None,
                        help='Limitar a los últimos N días de logs')
    args = parser.parse_args()

    if not LOG_DIR.exists():
        print(f'No se encontró el directorio {LOG_DIR}.')
        return

    trades = parse_logs(days=args.days)
    print_report(trades, days=args.days)


if __name__ == '__main__':
    main()
