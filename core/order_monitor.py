"""
Order Monitor — doble seguridad para SL/TP de posiciones live.

Corre en un thread independiente. Cada INTERVAL segundos:
  1. Obtiene precio actual de Binance (ticker)
  2. Compara contra SL y TP de cada posición abierta
  3. Si el precio cruzó el nivel → ejecuta MARKET close via check_and_close
  4. Verifica si las órdenes algo de Binance siguen activas (registro)

Complementa al check_and_close del scanner principal (que corre cada 30s
sobre velas cerradas). Este monitor actúa sobre precio en tiempo real.
"""

import logging
import time
import threading
from datetime import datetime, timezone
from typing import Optional

_logger = logging.getLogger('order_monitor')

INTERVAL_DEFAULT = 5   # segundos entre chequeos


# ── Loop principal ────────────────────────────────────────────────────────────

def run_loop(
    exchange,
    engines: dict,
    engines_lock: threading.Lock,
    live_mode: bool,
    interval: int = INTERVAL_DEFAULT,
) -> None:
    """Punto de entrada del thread. Corre indefinidamente."""
    _logger.info(f'[ORDER_MONITOR] Iniciado — interval={interval}s  live={live_mode}')
    while True:
        try:
            if live_mode:
                _check_all(exchange, engines, engines_lock)
        except Exception as e:
            _logger.error(f'[ORDER_MONITOR] Error inesperado: {e}')
        time.sleep(interval)


def _check_all(exchange, engines: dict, engines_lock: threading.Lock) -> None:
    with engines_lock:
        items = list(engines.items())

    for asset, engine in items:
        try:
            _check_asset(exchange, asset, engine, engines_lock)
        except Exception as e:
            _logger.error(f'[ORDER_MONITOR] {asset}: {e}')


def _check_asset(exchange, asset: str, engine, engines_lock: threading.Lock) -> None:
    pos = engine.get_position(asset)
    if pos is None:
        return

    # Precio actual
    symbol = asset + ':USDT'
    try:
        ticker = exchange.fetch_ticker(symbol)
        price  = float(ticker['last'])
    except Exception as e:
        _logger.warning(f'[{asset}] fetch_ticker failed: {e}')
        return

    direction = pos['direction']
    sl        = pos['sl']
    tp        = pos['tp']

    # ¿Cruzó SL o TP?
    if direction == 'long':
        triggered = price <= sl or price >= tp
    else:
        triggered = price >= sl or price <= tp

    if not triggered:
        return

    reason = _detect_reason(direction, price, sl, tp)
    _logger.warning(
        f'[ORDER_MONITOR] ⚠️ {asset} {reason} ALCANZADO — '
        f'precio={price:.4f}  sl={sl}  tp={tp} → cerrando'
    )

    # Bar sintético con high=low=precio actual para reutilizar check_and_close
    synthetic_bar = {
        'open_time': datetime.now(timezone.utc).isoformat(timespec='seconds') + '+00:00',
        'high':  price,
        'low':   price,
        'close': price,
    }

    with engines_lock:
        trade = engine.check_and_close(asset, synthetic_bar)

    if trade:
        _logger.info(
            f'[ORDER_MONITOR] ✅ {asset} cerrado por {trade["reason"]} '
            f'@ {trade["exit"]}  pnl={trade["pnl"]:+.4f} USD'
        )
    else:
        _logger.warning(f'[ORDER_MONITOR] {asset} check_and_close no registró cierre — reintentará')


def _detect_reason(direction: str, price: float, sl: float, tp: float) -> str:
    if direction == 'long':
        return 'SL' if price <= sl else 'TP'
    return 'SL' if price >= sl else 'TP'


# ── Status para endpoint GET /orders ─────────────────────────────────────────

def get_status(
    exchange,
    engines: dict,
    engines_lock: threading.Lock,
    live_mode: bool,
) -> list:
    """
    Devuelve estado de todas las posiciones abiertas: precio actual,
    distancia a SL/TP, y si las órdenes algo de Binance siguen activas.
    """
    result = []

    with engines_lock:
        items = list(engines.items())

    for asset, engine in items:
        pos = engine.get_position(asset)
        if pos is None:
            continue

        entry     = pos['entry']
        sl        = pos['sl']
        tp        = pos['tp']
        direction = pos['direction']
        qty       = pos['qty']

        # Precio actual
        current_price = None
        try:
            ticker        = exchange.fetch_ticker(asset + ':USDT')
            current_price = float(ticker['last'])
        except Exception:
            pass

        # PnL no realizado
        pnl_usd = None
        if current_price is not None:
            if direction == 'long':
                pnl_usd = (current_price - entry) * qty
            else:
                pnl_usd = (entry - current_price) * qty

        # Distancia a SL y TP en %
        dist_sl_pct = None
        dist_tp_pct = None
        if current_price:
            if direction == 'long':
                dist_sl_pct = round((current_price - sl) / entry * 100, 3)
                dist_tp_pct = round((tp - current_price) / entry * 100, 3)
            else:
                dist_sl_pct = round((sl - current_price) / entry * 100, 3)
                dist_tp_pct = round((current_price - tp) / entry * 100, 3)

        # Verificar si las órdenes algo siguen activas en Binance
        sl_binance = None
        tp_binance = None
        if live_mode:
            try:
                sym        = asset.replace('/', '').replace(':USDT', '')  # ETHUSDT
                open_algos = exchange.request(
                    'openAlgoOrders', 'fapiPrivate', 'GET', {'symbol': sym}
                )
                algo_ids   = {int(o['algoId']) for o in open_algos}
                sl_id      = pos.get('sl_order_id')
                tp_id      = pos.get('tp_order_id')
                sl_binance = (int(sl_id) in algo_ids) if sl_id else False
                tp_binance = (int(tp_id) in algo_ids) if tp_id else False
            except Exception as e:
                _logger.debug(f'[{asset}] openAlgoOrders check failed: {e}')

        result.append({
            'asset':             asset,
            'direction':         direction,
            'entry':             entry,
            'current_price':     current_price,
            'sl':                sl,
            'tp':                tp,
            'qty':               qty,
            'open_ts':           pos['open_ts'],
            'sl_order_id':       pos.get('sl_order_id'),
            'tp_order_id':       pos.get('tp_order_id'),
            'sl_order_type':     pos.get('sl_order_type'),
            'tp_order_type':     pos.get('tp_order_type'),
            'binance_sl_active': sl_binance,
            'binance_tp_active': tp_binance,
            'dist_sl_pct':       dist_sl_pct,
            'dist_tp_pct':       dist_tp_pct,
            'pnl_usd':           round(pnl_usd, 4) if pnl_usd is not None else None,
        })

    return result
