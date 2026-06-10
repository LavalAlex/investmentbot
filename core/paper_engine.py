"""
Paper Trading Engine — state management for paper trades.

One open position allowed per asset (same constraint as the backtest).
State is persisted to a per-asset JSON file (eth_state.json, btc_state.json).

No orders are placed. This is simulation only.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .trade_logic import check_exit
from . import gcs_storage

INITIAL_CAPITAL  = 10_000.0
FEE_PER_SIDE_PCT = 0.0005   # 0.05% taker, Binance USDM Futures VIP0


# ── Engine ────────────────────────────────────────────────────────────────────

class PaperEngine:
    """
    Manages paper positions and equity for a single asset.

    Usage:
        engine = PaperEngine('eth_state.json')
        engine.open_position(...)   # when signal fires
        trade = engine.check_and_close(asset, bar)  # on each new bar
        engine.log_status(logger, asset, current_price)
    """

    def __init__(self, state_file: str = 'eth_state.json'):
        self._state_file = state_file
        self._state_path = Path(state_file)
        self._gcs_state  = state_file
        self.state = self._load()

    def _load(self) -> dict:
        if not self._state_path.exists():
            gcs_storage.download(self._gcs_state, self._state_path)
        if self._state_path.exists():
            with open(self._state_path) as f:
                data = json.load(f)
            if 'initial_equity' not in data:
                data['initial_equity'] = data.get('equity', INITIAL_CAPITAL)
            return data
        return {'equity': INITIAL_CAPITAL, 'initial_equity': INITIAL_CAPITAL, 'positions': {}, 'trades': []}

    def _save(self) -> None:
        with open(self._state_file, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)
        gcs_storage.upload(self._state_path, self._gcs_state)

    # ── Read ─────────────────────────────────────────────────────────────────

    @property
    def equity(self) -> float:
        return self.state['equity']

    def has_position(self, asset: str) -> bool:
        return asset in self.state['positions']

    def get_position(self, asset: str) -> dict | None:
        return self.state['positions'].get(asset)

    # ── Write ────────────────────────────────────────────────────────────────

    def open_position(
        self,
        asset: str,
        direction: str,
        entry: float,
        sl: float,
        tp: float,
        qty: float,
        ts: str,
        risk_usd: float,
        logger=None,
    ) -> None:
        """Record a new paper position."""
        self.state['positions'][asset] = {
            'direction': direction,
            'entry':     round(entry, 8),
            'sl':        round(sl, 8),
            'tp':        round(tp, 8),
            'qty':       round(qty, 8),
            'open_ts':   ts,
            'risk_usd':  round(risk_usd, 4),
        }
        self._save()

    def check_and_close(self, asset: str, bar) -> dict | None:
        """
        Check whether SL or TP was hit on `bar`.
        bar must support bar['low'], bar['high'], bar['open'], bar['close'].

        Returns a completed trade record if closed, None otherwise.
        Equity is updated in place.
        """
        pos = self.state['positions'].get(asset)
        if pos is None:
            return None

        # Never evaluate exits on the same candle as entry.
        # SL = candle low/high, so the condition would always be true.
        if str(bar['open_time']) == pos['open_ts']:
            return None

        result = check_exit(pos['direction'], pos['sl'], pos['tp'], bar)
        if result is None:
            return None

        reason, exit_price = result

        if pos['direction'] == 'long':
            gross_pnl = (exit_price - pos['entry']) * pos['qty']
        else:
            gross_pnl = (pos['entry'] - exit_price) * pos['qty']

        fee_usd = (pos['entry'] + exit_price) * pos['qty'] * FEE_PER_SIDE_PCT
        pnl     = gross_pnl - fee_usd

        self.state['equity'] = round(self.state['equity'] + pnl, 4)

        trade = {
            'asset':      asset,
            'direction':  pos['direction'],
            'entry':      pos['entry'],
            'exit':       round(exit_price, 8),
            'sl':         pos['sl'],
            'tp':         pos['tp'],
            'qty':        pos['qty'],
            'open_ts':    pos['open_ts'],
            'close_ts':   str(bar['open_time']),
            'reason':     reason,
            'gross_pnl':  round(gross_pnl, 4),
            'fee_usd':    round(fee_usd, 4),
            'pnl':        round(pnl, 4),
            'equity':     self.state['equity'],
        }
        self.state['trades'].append(trade)
        del self.state['positions'][asset]
        self._save()
        return trade

    # ── Status ───────────────────────────────────────────────────────────────

    def progress_to_tp(self, asset: str, current_price: float) -> float:
        """
        Progress from entry toward TP as a percentage.
        0% = at entry, 100% = at TP, negative = moving against trade.
        """
        pos = self.get_position(asset)
        if pos is None:
            return 0.0
        entry = pos['entry']
        tp    = pos['tp']
        if pos['direction'] == 'long':
            span = tp - entry
            progress = (current_price - entry) / span * 100 if span != 0 else 0.0
        else:
            span = entry - tp
            progress = (entry - current_price) / span * 100 if span != 0 else 0.0
        return round(progress, 1)

    def time_in_trade(self, asset: str) -> str:
        pos = self.get_position(asset)
        if pos is None:
            return '—'
        open_ts = datetime.fromisoformat(pos['open_ts'])
        if open_ts.tzinfo is None:
            open_ts = open_ts.replace(tzinfo=timezone.utc)
        delta   = datetime.now(timezone.utc) - open_ts
        hours   = int(delta.total_seconds() // 3600)
        minutes = int((delta.total_seconds() % 3600) // 60)
        return f'{hours}h{minutes:02d}m'

    def log_status(
        self,
        logger,
        asset: str,
        current_price: float,
        candle_high: float = None,
        candle_low: float = None,
    ) -> None:
        pos = self.get_position(asset)
        if pos is None:
            return
        side     = 'LONG' if pos['direction'] == 'long' else 'SHORT'
        progress = self.progress_to_tp(asset, current_price)
        elapsed  = self.time_in_trade(asset)
        sign     = '+' if progress >= 0 else ''
        hl_str   = (
            f" | candle_hi={candle_high:.4f} candle_lo={candle_low:.4f}"
            if candle_high is not None and candle_low is not None
            else ''
        )
        logger.info(
            f"[STATUS] {side} {asset} | entry={pos['entry']:.4f} | current={current_price:.4f}"
            f"{hl_str}"
            f" | tp={pos['tp']:.4f} | sl={pos['sl']:.4f}"
            f" | progress_to_tp={sign}{progress:.1f}% | time_in_trade={elapsed}"
        )

    def init_equity(self, amount: float) -> None:
        """Set initial equity from real balance. Only applies when state is pristine (no trades)."""
        if self.state.get('trades') or self.state.get('positions'):
            return
        self.state['equity'] = round(amount, 4)
        self.state['initial_equity'] = round(amount, 4)
        self._save()

    def reset(self) -> None:
        """Wipe all trades, positions, and CB state. Equity back to INITIAL_CAPITAL."""
        self.state = {
            'equity':         INITIAL_CAPITAL,
            'initial_equity': INITIAL_CAPITAL,
            'positions':      {},
            'trades':         [],
        }
        self._save()

    # ── Summary ───────────────────────────────────────────────────────────────

    def print_summary(self, logger, label: str = 'PAPER TRADING SUMMARY') -> None:
        trades = self.state['trades']
        n      = len(trades)
        initial = self.state.get('initial_equity', INITIAL_CAPITAL)
        logger.info(f"\n{'─'*55}")
        logger.info(f"{label}")
        logger.info(f"{'─'*55}")
        logger.info(f"Equity       : {self.equity:.2f} USD")
        logger.info(f"Return       : {(self.equity - initial) / initial * 100:+.2f}%")
        if n == 0:
            logger.info(f"Trades       : 0")
        else:
            wins = sum(1 for t in trades if t['pnl'] > 0)
            gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
            gross_loss   = abs(sum(t['pnl'] for t in trades if t['pnl'] <= 0))
            pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            logger.info(f"Trades       : {n}  (W={wins} / L={n-wins})")
            logger.info(f"Win rate     : {wins/n*100:.1f}%")
            logger.info(f"Profit factor: {pf:.3f}")
            logger.info(f"Total PnL    : {sum(t['pnl'] for t in trades):+.2f} USD")
        open_pos = self.state['positions']
        if open_pos:
            logger.info(f"Open positions: {list(open_pos.keys())}")
        logger.info(f"{'─'*55}\n")
