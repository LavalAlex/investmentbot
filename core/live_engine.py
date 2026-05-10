"""
Live Trading Engine — ejecución real de órdenes en Binance Futures USDM.

Misma interfaz que PaperEngine para que paper_monitor.py pueda switchear
con el flag --live sin cambiar la lógica de scan.

Diferencias clave vs PaperEngine:
  - open_position  → orden MARKET + SL stop_market + TP limit en Binance
  - check_and_close → detecta si Binance ya ejecutó SL o TP (no lo calcula)
  - equity         → saldo USDT real de la cuenta Futures
  - has_position   → verifica contra Binance, no solo el JSON local

Requisitos:
  - Cuenta Binance con Futures USDM habilitado
  - API key con permiso "Futures"
  - USDT en el wallet de Futures (no Spot)

Testnet: pasar testnet=True al constructor para usar testnet.binancefuture.com
"""

import json
import logging
import math
import time
from pathlib import Path
from typing import Optional

from . import gcs_storage
from .notifier import notify_trade_open, notify_trade_close, notify_trade_opened_live

INITIAL_CAPITAL  = 10_000.0
FEE_PER_SIDE_PCT = 0.0005

_logger = logging.getLogger('live_engine')


class LiveEngine:
    """
    Motor de órdenes reales para un único asset.

    Uso:
        engine = LiveEngine(exchange, 'BTC/USDT:USDT', 'btc_state.json')
        engine.open_position(...)
        trade = engine.check_and_close(asset, bar)
    """

    def __init__(
        self,
        exchange,
        symbol: str,
        state_file: str,
        testnet: bool = False,
    ):
        self._exchange   = exchange
        self._symbol     = symbol          # e.g. 'BTC/USDT:USDT'
        self._state_file = state_file
        self._state_path = Path(state_file)
        self._testnet    = testnet

        self._exchange.load_markets()
        self._market   = self._exchange.market(symbol)
        self._qty_step = float(self._market['precision']['amount'])
        self._min_qty  = float(self._market['limits']['amount']['min'])
        self._min_cost = float(self._market['limits']['cost']['min'] or 0)

        self.state = self._load()

    # ── State persistence ────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self._state_path.exists():
            gcs_storage.download(self._state_file, self._state_path)
        if self._state_path.exists():
            with open(self._state_path) as f:
                return json.load(f)
        return {'equity': INITIAL_CAPITAL, 'positions': {}, 'trades': []}

    def _save(self) -> None:
        with open(self._state_file, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)
        gcs_storage.upload(self._state_path, self._state_file)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _floor_qty(self, qty: float) -> float:
        """Truncar qty al step size — nunca sobrepasar el riesgo calculado."""
        return math.floor(qty / self._qty_step) * self._qty_step

    def _round_price(self, price: float) -> float:
        precision = self._market['precision']['price']
        factor = 10 ** int(-math.log10(float(precision)))
        return round(round(price * factor) / factor, 10)

    def _cancel_open_orders(self, asset: str) -> None:
        """Cancela órdenes estándar y algo pendientes del asset."""
        try:
            self._exchange.cancel_all_orders(asset)
            _logger.info(f'[{asset}] Órdenes estándar canceladas')
        except Exception as e:
            _logger.warning(f'[{asset}] Error cancelando órdenes estándar: {e}')
        try:
            open_algo = self._exchange.request(
                'order/algo/openOrders', 'fapiPrivate', 'GET',
                {'symbol': self._market['id']}
            )
            for o in open_algo.get('orders', []):
                self._cancel_algo_order(o['strategyId'])
        except Exception as e:
            _logger.warning(f'[{asset}] Error cancelando algo orders: {e}')

    def _cancel_algo_order(self, strategy_id: int) -> None:
        try:
            self._exchange.request(
                'order/algo', 'fapiPrivate', 'DELETE',
                {'strategyId': strategy_id}
            )
            _logger.info(f'[algo] strategyId={strategy_id} cancelado')
        except Exception as e:
            _logger.warning(f'[algo] Error cancelando strategyId={strategy_id}: {e}')

    def _place_sl_algo(self, side: str, qty: float, stop_price: float) -> int:
        resp = self._exchange.request(
            'order/algo/market', 'fapiPrivate', 'POST', {
                'symbol': self._market['id'],
                'side': side,
                'quantity': str(qty),
                'stopPrice': str(stop_price),
                'reduceOnly': 'true',
                'workingType': 'CONTRACT_PRICE',
            }
        )
        return resp['strategyId']

    def _place_tp_algo(self, side: str, qty: float, stop_price: float) -> int:
        resp = self._exchange.request(
            'order/algo/takeProfit', 'fapiPrivate', 'POST', {
                'symbol': self._market['id'],
                'side': side,
                'quantity': str(qty),
                'stopPrice': str(stop_price),
                'reduceOnly': 'true',
                'workingType': 'CONTRACT_PRICE',
            }
        )
        return resp['strategyId']

    # ── Read ─────────────────────────────────────────────────────────────────

    @property
    def equity(self) -> float:
        """Saldo USDT disponible en el wallet Futures."""
        try:
            balance = self._exchange.fetch_balance()
            return float(balance.get('USDT', {}).get('free', 0.0))
        except Exception as e:
            _logger.warning(f'[live] fetch_balance failed: {e}')
            return self.state.get('equity', INITIAL_CAPITAL)

    def has_position(self, asset: str) -> bool:
        """Verifica en Binance si hay posición abierta (fuente de verdad)."""
        try:
            positions = self._exchange.fetch_positions([self._symbol])
            for p in positions:
                if float(p.get('contracts', 0)) != 0:
                    return True
            return False
        except Exception as e:
            _logger.warning(f'[{asset}] fetch_positions failed: {e}')
            # Fallback al estado local
            return asset in self.state.get('positions', {})

    def get_position(self, asset: str) -> Optional[dict]:
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
    ) -> bool:
        """
        1. Validar qty vs mínimos Binance
        2. Orden MARKET (entry)
        3. Orden stop_market (SL) + limit (TP) — reduceOnly
        4. Guardar estado local
        Returns True if position was opened, False if skipped.
        """
        side      = 'BUY' if direction == 'long' else 'SELL'
        side_exit = 'SELL' if direction == 'long' else 'BUY'

        qty_floored = self._floor_qty(qty)
        notional    = qty_floored * entry

        def _warn(msg):
            _logger.warning(msg)
            if logger:
                logger.info(msg)

        if qty_floored < self._min_qty:
            _warn(f'[{asset}] SKIP — qty {qty_floored} < min_qty {self._min_qty}  (equity too low)')
            return False
        if notional < self._min_cost:
            _warn(f'[{asset}] SKIP — notional ${notional:.2f} < min_cost ${self._min_cost}  (equity too low)')
            return False

        sl_price = self._round_price(sl)
        tp_price = self._round_price(tp)

        # ── 1. Entry MARKET ──────────────────────────────────────────────────
        try:
            entry_order = self._exchange.create_order(
                symbol=self._symbol,
                type='MARKET',
                side=side,
                amount=qty_floored,
            )
            fill_price = float(entry_order.get('average') or entry_order.get('price') or entry)
            _logger.info(
                f'[{asset}] MARKET {side} {qty_floored} @ {fill_price:.4f}  '
                f'(order_id={entry_order["id"]})'
            )
        except Exception as e:
            _logger.error(f'[{asset}] Entry MARKET failed: {e}')
            notify_trade_opened_live(asset, direction, entry, sl, tp, risk_usd,
                                     sl_ok=False, tp_ok=False,
                                     sl_error=f'Entry falló: {e}', tp_error='')
            return False

        # ── 2. SL — algo stop_market ─────────────────────────────────────────
        sl_order_id = None
        sl_ok       = False
        sl_error    = ''
        try:
            sl_order_id = self._place_sl_algo(side_exit, qty_floored, sl_price)
            sl_ok = True
            _logger.info(f'[{asset}] SL algo_stop_market @ {sl_price}  (strategyId={sl_order_id})')
        except Exception as e:
            sl_error = str(e)
            _logger.error(f'[{asset}] SL order failed: {e} — POSICIÓN SIN PROTECCIÓN')

        # ── 3. TP — algo take_profit_market ──────────────────────────────────
        tp_order_id = None
        tp_ok       = False
        tp_error    = ''
        if sl_ok:
            try:
                tp_order_id = self._place_tp_algo(side_exit, qty_floored, tp_price)
                tp_ok = True
                _logger.info(f'[{asset}] TP algo_take_profit @ {tp_price}  (strategyId={tp_order_id})')
            except Exception as e:
                tp_error = str(e)
                _logger.error(f'[{asset}] TP order failed: {e}')

        # ── 4. Guardar estado ────────────────────────────────────────────────
        self.state.setdefault('positions', {})[asset] = {
            'direction':   direction,
            'entry':       fill_price,
            'sl':          sl_price,
            'tp':          tp_price,
            'qty':         qty_floored,
            'open_ts':     ts,
            'risk_usd':    round(risk_usd, 4),
            'sl_order_id': sl_order_id,
            'tp_order_id': tp_order_id,
        }
        self._save()
        notify_trade_opened_live(asset, direction, fill_price, sl_price, tp_price, risk_usd,
                                 sl_ok=sl_ok, tp_ok=tp_ok,
                                 sl_error=sl_error, tp_error=tp_error)
        return True

    def check_and_close(self, asset: str, bar) -> Optional[dict]:
        """
        Detecta si Binance ya ejecutó el SL o TP verificando las órdenes.
        Si la posición ya no existe en Binance → registrar cierre.
        """
        pos = self.state.get('positions', {}).get(asset)
        if pos is None:
            return None

        # No evaluar en la misma vela de entrada
        if str(bar['open_time']) == pos['open_ts']:
            return None

        # Verificar si la posición sigue abierta en Binance
        still_open = self.has_position(asset)
        if still_open:
            return None

        # La posición se cerró — determinar precio y razón por trades recientes
        sl_id = pos.get('sl_order_id')
        tp_id = pos.get('tp_order_id')
        reason     = 'SL'
        exit_price = pos['sl']

        try:
            recent = self._exchange.fetch_my_trades(self._symbol, limit=10)
            closing_side = 'sell' if pos['direction'] == 'long' else 'buy'
            closing = [t for t in recent if t['side'] == closing_side]
            if closing:
                exit_price = float(closing[-1]['price'])
                midpoint = (pos['sl'] + pos['tp']) / 2
                if pos['direction'] == 'long':
                    reason = 'TP' if exit_price > midpoint else 'SL'
                else:
                    reason = 'TP' if exit_price < midpoint else 'SL'
        except Exception as e:
            _logger.warning(f'[{asset}] Error fetching trades for close detection: {e}')

        # Cancelar la orden algo huérfana
        orphan_id = tp_id if reason == 'SL' else sl_id
        if orphan_id:
            self._cancel_algo_order(orphan_id)

        # Calcular PnL
        if pos['direction'] == 'long':
            gross_pnl = (exit_price - pos['entry']) * pos['qty']
        else:
            gross_pnl = (pos['entry'] - exit_price) * pos['qty']

        fee_usd = (pos['entry'] + exit_price) * pos['qty'] * FEE_PER_SIDE_PCT
        pnl     = gross_pnl - fee_usd

        # Equity real desde Binance
        current_equity = self.equity

        trade = {
            'asset':     asset,
            'direction': pos['direction'],
            'entry':     pos['entry'],
            'exit':      round(exit_price, 8),
            'sl':        pos['sl'],
            'tp':        pos['tp'],
            'qty':       pos['qty'],
            'open_ts':   pos['open_ts'],
            'close_ts':  str(bar['open_time']),
            'reason':    reason,
            'gross_pnl': round(gross_pnl, 4),
            'fee_usd':   round(fee_usd, 4),
            'pnl':       round(pnl, 4),
            'equity':    current_equity,
        }

        self.state.setdefault('trades', []).append(trade)
        self.state['equity'] = current_equity
        del self.state['positions'][asset]
        self._save()

        notify_trade_close(
            asset, pos['direction'], pos['entry'], exit_price,
            reason, pnl, current_equity,
        )
        return trade

    def reset(self) -> None:
        self._cancel_open_orders(self._symbol)
        self.state = {'equity': INITIAL_CAPITAL, 'positions': {}, 'trades': []}
        self._save()

    # ── Status ───────────────────────────────────────────────────────────────

    def log_status(self, logger, asset: str, current_price: float,
                   candle_high: float = None, candle_low: float = None) -> None:
        pos = self.get_position(asset)
        if pos is None:
            return
        side     = 'LONG' if pos['direction'] == 'long' else 'SHORT'
        tp, sl   = pos['tp'], pos['sl']
        entry    = pos['entry']
        if pos['direction'] == 'long':
            progress = (current_price - entry) / (tp - entry) * 100 if tp != entry else 0
        else:
            progress = (entry - current_price) / (entry - tp) * 100 if entry != tp else 0
        sign = '+' if progress >= 0 else ''
        logger.info(
            f'[STATUS] {side} {asset} | entry={entry:.4f} | current={current_price:.4f}'
            f' | tp={tp:.4f} | sl={sl:.4f} | progress_to_tp={sign}{progress:.1f}%'
        )

    def print_summary(self, logger, label: str = 'LIVE TRADING SUMMARY') -> None:
        trades = self.state.get('trades', [])
        n      = len(trades)
        eq     = self.equity
        logger.info(f"\n{'─'*55}")
        logger.info(f"{label}")
        logger.info(f"{'─'*55}")
        logger.info(f"Equity (real) : {eq:.2f} USD")
        if n == 0:
            logger.info(f"Trades        : 0")
        else:
            wins = sum(1 for t in trades if t['pnl'] > 0)
            gp   = sum(t['pnl'] for t in trades if t['pnl'] > 0)
            gl   = abs(sum(t['pnl'] for t in trades if t['pnl'] <= 0))
            pf   = gp / gl if gl > 0 else float('inf')
            logger.info(f"Trades        : {n}  (W={wins} / L={n-wins})")
            logger.info(f"Profit factor : {pf:.3f}")
            logger.info(f"Total PnL     : {sum(t['pnl'] for t in trades):+.2f} USD")
        logger.info(f"{'─'*55}\n")
