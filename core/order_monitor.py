"""
Order Monitor — Binance WebSocket User Data Stream.

Reemplaza el polling de precio con detección event-driven:
  1. POST /fapi/v1/listenKey → obtiene clave de sesión (válida 60 min)
  2. wss://fstream.binance.com/ws/{listenKey} → push en tiempo real
  3. ORDER_TRADE_UPDATE con status=FILLED → llama engine.record_close()
  4. Keepalive thread: PUT /fapi/v1/listenKey cada 30 min
  5. Reconexión automática ante cualquier error de red

Ventaja vs polling de precio anterior:
  - Latencia < 200 ms vs 5-10 s
  - Sin llamadas redundantes a _close_market (que fallaba porque Binance
    ya había cerrado la posición con la orden algo)
  - El state file se actualiza siempre que Binance ejecute el SL o TP
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone

from .notifier import notify_ws_status

_logger = logging.getLogger('order_monitor')

_WS_URL      = 'wss://fstream.binance.com/ws/{listen_key}'
_KEEPALIVE_S = 1800  # 30 min — Binance expira la key a los 60 min sin renovar

_SYMBOL_TO_ASSET = {
    'BTCUSDT': 'BTC/USDT',
    'ETHUSDT': 'ETH/USDT',
}


# ── Entry point ───────────────────────────────────────────────────────────────

def run_loop(
    exchange,
    engines: dict,
    engines_lock: threading.Lock,
    live_mode: bool,
    **_kwargs,
) -> None:
    """Punto de entrada del thread. Corre indefinidamente con reconexión automática."""
    if not live_mode:
        _logger.info('[ORDER_MONITOR] Modo paper — WebSocket desactivado')
        return

    _logger.info('[ORDER_MONITOR] Iniciando WebSocket User Data Stream')
    _reconnect_count = 0
    while True:
        try:
            _session(exchange, engines, engines_lock, _reconnect_count)
            _reconnect_count += 1
        except Exception as e:
            _logger.error(f'[ORDER_MONITOR] Sesión terminada ({e}) — reconectando en 5s')
            notify_ws_status('error', str(e)[:120])
            _reconnect_count += 1
        time.sleep(5)


# ── WebSocket session ─────────────────────────────────────────────────────────

def _session(
    exchange,
    engines: dict,
    engines_lock: threading.Lock,
    reconnect_count: int = 0,
) -> None:
    """Una sesión completa: crea key, conecta WebSocket, escucha hasta desconexión."""
    from websockets.sync.client import connect

    listen_key = _create_listen_key(exchange)
    _logger.info(f'[ORDER_MONITOR] ListenKey: {listen_key[:12]}...')

    stop = threading.Event()
    ka = threading.Thread(
        target=_keepalive_loop,
        args=(exchange, listen_key, stop),
        daemon=True,
        name='ws-keepalive',
    )
    ka.start()

    try:
        with connect(_WS_URL.format(listen_key=listen_key)) as ws:
            event = 'reconnected' if reconnect_count > 0 else 'connected'
            detail = f'Reconexión #{reconnect_count}' if reconnect_count > 0 else 'Escuchando fills en tiempo real'
            _logger.info(f'[ORDER_MONITOR] {event.capitalize()} — {detail}')
            notify_ws_status(event, detail)

            for raw in ws:
                try:
                    _handle(json.loads(raw), engines, engines_lock)
                except Exception as e:
                    _logger.error(f'[ORDER_MONITOR] Error procesando evento: {e}')
    finally:
        stop.set()
        _logger.warning('[ORDER_MONITOR] WebSocket desconectado')
        notify_ws_status('disconnected', 'Intentando reconectar...')
        _delete_listen_key(exchange, listen_key)


# ── Listen key management ─────────────────────────────────────────────────────

def _create_listen_key(exchange) -> str:
    resp = exchange.fapiPrivatePostListenKey()
    return resp['listenKey']


def _keepalive_loop(exchange, listen_key: str, stop: threading.Event) -> None:
    while not stop.wait(_KEEPALIVE_S):
        try:
            exchange.fapiPrivatePutListenKey({'listenKey': listen_key})
            _logger.debug('[ORDER_MONITOR] ListenKey renovado')
        except Exception as e:
            _logger.warning(f'[ORDER_MONITOR] Keepalive falló: {e}')


def _delete_listen_key(exchange, listen_key: str) -> None:
    try:
        exchange.fapiPrivateDeleteListenKey({'listenKey': listen_key})
    except Exception:
        pass


# ── Event handler ─────────────────────────────────────────────────────────────

def _handle(data: dict, engines: dict, engines_lock: threading.Lock) -> None:
    if data.get('e') != 'ORDER_TRADE_UPDATE':
        return

    order = data.get('o', {})
    if order.get('X') != 'FILLED':
        return

    symbol     = order.get('s', '')     # BTCUSDT
    order_type = order.get('o', '')     # STOP_MARKET, TAKE_PROFIT_MARKET, MARKET …
    side       = order.get('S', '')     # BUY / SELL
    fill_price = float(order.get('L') or order.get('ap') or 0)
    order_id   = str(order.get('i', ''))
    close_ts   = (
        datetime.fromtimestamp(data.get('T', 0) / 1000, tz=timezone.utc)
        .isoformat(timespec='seconds') + '+00:00'
    )

    asset = _SYMBOL_TO_ASSET.get(symbol)
    if not asset:
        return

    _logger.info(
        f'[ORDER_MONITOR] FILL {symbol}  {order_type}  {side}  '
        f'price={fill_price}  orderId={order_id}'
    )

    with engines_lock:
        engine = engines.get(asset)
        if engine is None:
            return

        pos = engine.get_position(asset)
        if pos is None:
            _logger.debug(f'[ORDER_MONITOR] {asset}: sin posición en state — ignorando')
            return

        # Solo el lado de cierre: sell para long, buy para short
        expected_close = 'SELL' if pos['direction'] == 'long' else 'BUY'
        if side != expected_close:
            _logger.debug(f'[ORDER_MONITOR] {asset}: {side} no cierra {pos["direction"]}')
            return

        reason = _classify_reason(order_type, fill_price, pos)
        trade  = engine.record_close(asset, fill_price, reason, close_ts, order_id)

        if trade:
            _logger.info(
                f'[ORDER_MONITOR] ✅ {asset} {reason} @ {fill_price}  '
                f'pnl={trade["pnl"]:+.4f}  equity={trade["equity"]:.2f}'
            )
        else:
            _logger.warning(f'[ORDER_MONITOR] {asset}: record_close retornó None')


def _classify_reason(order_type: str, fill_price: float, pos: dict) -> str:
    if order_type in ('STOP_MARKET', 'STOP'):
        return 'SL'
    if order_type in ('TAKE_PROFIT_MARKET', 'TAKE_PROFIT'):
        return 'TP'
    # Fallback: comparar precio de fill con midpoint entre SL y TP
    mid = (pos['sl'] + pos['tp']) / 2
    if pos['direction'] == 'long':
        return 'TP' if fill_price > mid else 'SL'
    return 'TP' if fill_price < mid else 'SL'


# ── Status para GET /orders ───────────────────────────────────────────────────

def get_status(
    exchange,
    engines: dict,
    engines_lock: threading.Lock,
    live_mode: bool,
) -> list:
    """
    Devuelve estado de todas las posiciones abiertas: precio actual,
    distancia a SL/TP, y si las órdenes algo siguen activas en Binance.
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

        current_price = None
        try:
            ticker        = exchange.fetch_ticker(asset + ':USDT')
            current_price = float(ticker['last'])
        except Exception:
            pass

        pnl_usd = None
        if current_price is not None:
            mult    = 1 if direction == 'long' else -1
            pnl_usd = (current_price - entry) * qty * mult

        dist_sl_pct = dist_tp_pct = None
        if current_price:
            if direction == 'long':
                dist_sl_pct = round((current_price - sl) / entry * 100, 3)
                dist_tp_pct = round((tp - current_price) / entry * 100, 3)
            else:
                dist_sl_pct = round((sl - current_price) / entry * 100, 3)
                dist_tp_pct = round((current_price - tp) / entry * 100, 3)

        sl_binance = tp_binance = None
        if live_mode:
            try:
                sym        = asset.replace('/', '').replace(':USDT', '')
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
