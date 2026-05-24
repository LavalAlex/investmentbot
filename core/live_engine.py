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
from .notifier import notify_trade_open, notify_trade_close, notify_trade_opened_live, notify_ws_status

INITIAL_CAPITAL  = 10_000.0
FEE_PER_SIDE_PCT = 0.0005

_ORDER_ALGO     = 'algo'
_ORDER_STANDARD = 'standard'

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

        if not self._exchange.markets:
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
            # DELETE /fapi/v1/algoOpenOrders cancela todas las conditional orders del symbol
            self._exchange.request(
                'algoOpenOrders', 'fapiPrivate', 'DELETE',
                {'symbol': self._market['id']}
            )
            _logger.info(f'[{asset}] Algo open orders canceladas')
        except Exception as e:
            _logger.warning(f'[{asset}] Error cancelando algo orders: {e}')

    def _cancel_algo_order(self, algo_id: int) -> None:
        # DELETE /fapi/v1/algoOrder — API de conditional orders (migrado dic 2025)
        try:
            self._exchange.request(
                'algoOrder', 'fapiPrivate', 'DELETE',
                {'algoId': algo_id}
            )
            _logger.info(f'[algo] algoId={algo_id} cancelado')
        except Exception as e:
            _logger.warning(f'[algo] Error cancelando algoId={algo_id}: {e}')

    def _place_sl_algo(self, side: str, qty: float, stop_price: float) -> int:
        # POST /fapi/v1/algoOrder — conditional orders API (migrado dic 2025)
        resp = self._exchange.request(
            'algoOrder', 'fapiPrivate', 'POST', {
                'algoType':     'CONDITIONAL',
                'symbol':       self._market['id'],
                'side':         side,
                'type':         'STOP_MARKET',
                'quantity':     str(qty),
                'triggerPrice': str(stop_price),
                'reduceOnly':   'true',
                'workingType':  'CONTRACT_PRICE',
            }
        )
        return resp['algoId']

    def _place_tp_algo(self, side: str, qty: float, stop_price: float) -> int:
        resp = self._exchange.request(
            'algoOrder', 'fapiPrivate', 'POST', {
                'algoType':     'CONDITIONAL',
                'symbol':       self._market['id'],
                'side':         side,
                'type':         'TAKE_PROFIT_MARKET',
                'quantity':     str(qty),
                'triggerPrice': str(stop_price),
                'reduceOnly':   'true',
                'workingType':  'CONTRACT_PRICE',
            }
        )
        return resp['algoId']

    def _place_exit_order(self, order_type: str, side: str, qty: float, stop_price: float) -> str:
        resp = self._exchange.create_order(
            self._symbol, order_type, side, qty,
            params={'stopPrice': stop_price, 'reduceOnly': True, 'workingType': 'CONTRACT_PRICE'},
        )
        return str(resp['id'])

    def _place_order_with_fallback(
        self, asset: str, label: str,
        algo_fn, std_order_type: str,
        side: str, qty: float, price: float,
    ) -> tuple:
        order_id, order_type, ok, error = None, _ORDER_ALGO, False, ''
        try:
            order_id = algo_fn(side, qty, price)
            ok = True
            _logger.info(f'[{asset}] {label} algo @ {price}  (strategyId={order_id})')
        except Exception as e:
            _logger.warning(f'[{asset}] {label} algo failed ({e}), retrying with standard {std_order_type}')
            try:
                order_id   = self._place_exit_order(std_order_type, side, qty, price)
                order_type = _ORDER_STANDARD
                ok         = True
                _logger.info(f'[{asset}] {label} standard {std_order_type} @ {price}  (orderId={order_id})')
            except Exception as e2:
                error = str(e2)
                suffix = ' — POSICIÓN SIN PROTECCIÓN' if label == 'SL' else ''
                _logger.error(f'[{asset}] {label} order failed: {e2}{suffix}')
        return order_id, order_type, ok, error

    def _cancel_order(self, order_id, order_type: str) -> None:
        if order_type == _ORDER_STANDARD:
            try:
                self._exchange.cancel_order(order_id, self._symbol)
            except Exception as e:
                _logger.warning(f'[live] Error cancelando orden standard {order_id}: {e}')
        else:
            self._cancel_algo_order(order_id)

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

        # ── 2. SL + 3. TP — algo con fallback a standard ─────────────────────
        sl_order_id, sl_order_type, sl_ok, sl_error = self._place_order_with_fallback(
            asset, 'SL', self._place_sl_algo, 'STOP_MARKET', side_exit, qty_floored, sl_price,
        )
        tp_order_id, tp_order_type, tp_ok, tp_error = None, _ORDER_ALGO, False, ''
        if sl_ok:
            tp_order_id, tp_order_type, tp_ok, tp_error = self._place_order_with_fallback(
                asset, 'TP', self._place_tp_algo, 'TAKE_PROFIT_MARKET', side_exit, qty_floored, tp_price,
            )

        # ── 4. Guardar estado ────────────────────────────────────────────────
        self.state.setdefault('positions', {})[asset] = {
            'direction':    direction,
            'entry':        fill_price,
            'sl':           sl_price,
            'tp':           tp_price,
            'qty':          qty_floored,
            'open_ts':      ts,
            'risk_usd':     round(risk_usd, 4),
            'sl_order_id':  sl_order_id,
            'tp_order_id':  tp_order_id,
            'sl_order_type': sl_order_type,
            'tp_order_type': tp_order_type,
        }
        self._save()
        software_sltp = not sl_ok and not tp_ok
        notify_trade_opened_live(asset, direction, fill_price, sl_price, tp_price, risk_usd,
                                 sl_ok=sl_ok, tp_ok=tp_ok,
                                 sl_error=sl_error, tp_error=tp_error,
                                 software_sltp=software_sltp)
        return True

    def record_close(
        self,
        asset: str,
        exit_price: float,
        reason: str,
        close_ts: str,
        order_id: str = '',
    ) -> Optional[dict]:
        """
        Registra el cierre de una posición ejecutado por Binance (SL/TP algo).

        Llamado desde dos paths:
          1. order_monitor (WebSocket) — en tiempo real, < 200 ms tras el fill
          2. check_and_close (scanner fallback) — cada 15 min como red de seguridad

        La protección contra doble registro es implícita: si la posición ya fue
        eliminada del state por el primer llamador, pos será None y retorna None.
        Ambos paths están bajo engines_lock, por lo que no hay race condition.
        """
        pos = self.state.get('positions', {}).get(asset)
        if pos is None:
            return None

        # Cancelar la orden huérfana (la que NO se ejecutó)
        sl_id       = pos.get('sl_order_id')
        tp_id       = pos.get('tp_order_id')
        orphan_id   = tp_id   if reason == 'SL' else sl_id
        orphan_type = (pos.get('tp_order_type', 'algo') if reason == 'SL'
                       else pos.get('sl_order_type', 'algo'))
        if orphan_id and str(orphan_id) != str(order_id):
            self._cancel_order(orphan_id, orphan_type)

        # PnL
        if pos['direction'] == 'long':
            gross_pnl = (exit_price - pos['entry']) * pos['qty']
        else:
            gross_pnl = (pos['entry'] - exit_price) * pos['qty']

        fee_usd        = (pos['entry'] + exit_price) * pos['qty'] * FEE_PER_SIDE_PCT
        pnl            = gross_pnl - fee_usd
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
            'close_ts':  close_ts,
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

    def check_and_close(self, asset: str, bar) -> Optional[dict]:
        """
        Fallback de seguridad: detecta cierres que el WebSocket pudo haber
        perdido (reconexión, restart de Cloud Run, etc.).

        Corre cada 15 min al cerrar vela. El path primario es el WebSocket
        en order_monitor que detecta fills en tiempo real.
        """
        pos = self.state.get('positions', {}).get(asset)
        if pos is None:
            return None

        # No evaluar en la misma vela de entrada
        if str(bar['open_time']) == pos['open_ts']:
            return None

        # Si Binance todavía muestra posición abierta → nada que hacer
        if self.has_position(asset):
            return None

        # Posición cerrada en Binance pero state no actualizado → detectar
        _logger.warning(f'[{asset}] Posición cerrada en Binance (fallback scan) — detectando cierre')
        notify_ws_status('error', f'{asset}: cierre detectado por fallback scan (WS pudo haber perdido el evento)')

        direction  = pos['direction']
        exit_price = pos['sl']
        reason     = 'SL'
        try:
            recent       = self._exchange.fetch_my_trades(self._symbol, limit=10)
            closing_side = 'sell' if direction == 'long' else 'buy'
            closing      = [t for t in recent if t['side'] == closing_side]
            if closing:
                exit_price = float(closing[-1]['price'])
                midpoint   = (pos['sl'] + pos['tp']) / 2
                if direction == 'long':
                    reason = 'TP' if exit_price > midpoint else 'SL'
                else:
                    reason = 'TP' if exit_price < midpoint else 'SL'
        except Exception as e:
            _logger.warning(f'[{asset}] Error fetching trades for fallback close: {e}')

        return self.record_close(asset, exit_price, reason, str(bar['open_time']))

    def reset(self) -> None:
        self._cancel_open_orders(self._symbol)
        real_equity = self.equity  # fetch real Binance balance as baseline
        self.state = {'equity': real_equity, 'initial_equity': real_equity, 'positions': {}, 'trades': []}
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
