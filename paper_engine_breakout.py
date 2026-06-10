"""
Daily Breakout Paper Trading Monitor

Dos ciclos por ejecución horaria:
  1. Position management: chequea SL/TP sobre velas 1h cerradas
  2. Signal detection: una vez por día (cuando la vela diaria está completa)

Estrategia: breakout de N días con filtro de volumen (longs únicamente)
  BTC: 10d, vol≥1.5×, ATR×1.5, RR=2  → PF=1.735 (5y IS) / 1.627 (730d OOS)
  ETH: 10d, vol≥1.5×, ATR×1.5, RR=2  → PF=1.711 (5y IS) / 1.442 (730d OOS)

Usage:
  python paper_engine_breakout.py           → single scan, then exit
  python paper_engine_breakout.py --loop    → loop every 3600s (1h)
"""

import argparse
import time
from datetime import datetime, timezone

import pandas as pd

from core.exchange import create_futures_exchange, create_public_exchange, fetch_ohlcv
from core.strategy_breakout import prepare_daily, is_breakout_signal, calculate_position
from core.paper_engine import PaperEngine
from core.logger_v2 import setup_logger, log_open, log_close
from core.notifier import notify_trade_open, notify_trade_close

# ── Config ────────────────────────────────────────────────────────────────────

ASSETS_CONFIG = {
    'BTC/USDT': {
        'state_file': 'btc_breakout_state.json',
        'log_prefix': 'btc_breakout',
    },
    'ETH/USDT': {
        'state_file': 'eth_breakout_state.json',
        'log_prefix': 'eth_breakout',
    },
}

# 60 días × 24h = 1440 velas — suficiente para ATR14, vol20, nd_high=10
CANDLE_LIMIT_SIGNAL = 1440
# 5 días × 24h = 120 velas — suficiente para monitorear posición abierta
CANDLE_LIMIT_POSITION = 120

SCAN_INTERVAL = 3600  # segundos entre scans (1 hora)


# ── Ciclo 1: Monitoreo de posición abierta ────────────────────────────────────

def check_open_position(
    exchange,
    asset: str,
    engine: PaperEngine,
    logger,
) -> dict | None:
    """
    Procesa en orden todas las velas 1h cerradas posteriores a la apertura
    de la posición. Cierra la posición en el primer SL o TP alcanzado.

    Devuelve el trade cerrado (dict) o None si la posición sigue abierta.
    """
    pos = engine.get_position(asset)
    if pos is None:
        return None

    df = fetch_ohlcv(exchange, asset, '1h', CANDLE_LIMIT_POSITION)
    if df.empty:
        logger.info(f'[{asset}] 1h fetch failed — skipping position check')
        return None

    df = df.iloc[:-1]  # descartar vela en progreso
    df = df.reset_index().rename(columns={'timestamp': 'open_time'})

    # Solo procesar velas estrictamente posteriores a la entrada
    open_ts = pd.Timestamp(pos['open_ts'], tz='UTC') if '+' not in str(pos['open_ts']) \
              else pd.Timestamp(pos['open_ts'])
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    after_open = df[df['open_time'] > open_ts].sort_values('open_time')

    for _, bar in after_open.iterrows():
        trade = engine.check_and_close(asset, bar)
        if trade is not None:
            log_close(
                logger, asset, trade['direction'],
                trade['entry'], trade['exit'], trade['reason'],
                trade['pnl'], engine.equity, fee_usd=trade.get('fee_usd', 0.0),
            )
            notify_trade_close(
                asset, trade['direction'], trade['entry'], trade['exit'],
                trade['reason'], trade['pnl'], engine.equity,
            )
            return trade

    # Posición sigue abierta — loguear estado
    latest_price = float(df.iloc[-1]['close']) if not df.empty else pos['entry']
    engine.log_status(logger, asset, latest_price)
    return None


# ── Ciclo 2: Detección de señal diaria ───────────────────────────────────────

def check_daily_signal(
    exchange,
    asset: str,
    engine: PaperEngine,
    logger,
) -> bool:
    """
    Evalúa si la última vela diaria completa genera una señal de breakout.
    Dedup: usa engine.state['last_daily_check'] para no procesar el mismo día dos veces.

    Devuelve True si se abrió una posición nueva.
    """
    df_1h = fetch_ohlcv(exchange, asset, '1h', CANDLE_LIMIT_SIGNAL)
    if df_1h.empty:
        logger.info(f'[{asset}] 1h fetch failed — skipping signal check')
        return False

    df_1h = df_1h.reset_index().rename(columns={'timestamp': 'open_time'})
    daily = prepare_daily(df_1h)

    if daily.empty:
        return False

    # Solo considerar días anteriores al UTC actual (velas diarias completas)
    today_utc = datetime.now(timezone.utc).date()
    daily['open_time'] = pd.to_datetime(daily['open_time'], utc=True)
    completed = daily[daily['open_time'].dt.date < today_utc].dropna(
        subset=['nd_high', 'atr14', 'vol20']
    )

    if completed.empty:
        logger.info(f'[{asset}] No hay velas diarias completas con indicadores listos')
        return False

    last_candle = completed.iloc[-1]
    candle_date = str(last_candle['open_time'])[:10]  # "YYYY-MM-DD"

    # Dedup: ya procesamos este día
    if engine.state.get('last_daily_check') == candle_date:
        logger.info(f'[{asset}] Señal diaria ya evaluada para {candle_date} — skip')
        return False

    # Marcar como procesado (con o sin señal)
    engine.state['last_daily_check'] = candle_date
    engine._save()

    if not is_breakout_signal(last_candle):
        logger.info(
            f'[{asset}] Sin señal en {candle_date} | '
            f'close={last_candle["close"]:.2f}  nd_high={last_candle["nd_high"]:.2f}  '
            f'vol={last_candle["volume"]:.0f}  vol20={last_candle["vol20"]:.0f}'
        )
        return False

    # ── Señal válida ──────────────────────────────────────────────────────────
    pos_params = calculate_position(last_candle, engine.equity)
    if pos_params is None:
        logger.info(f'[{asset}] Señal en {candle_date} pero cálculo de posición falló')
        return False

    # El timestamp de apertura es el cierre de la vela diaria (available_at = día siguiente 00:00 UTC)
    entry_ts = str(last_candle['available_at'])

    engine.open_position(
        asset=asset,
        direction='long',
        entry=pos_params['entry'],
        sl=pos_params['sl'],
        tp=pos_params['tp'],
        qty=pos_params['qty'],
        ts=entry_ts,
        risk_usd=pos_params['risk_usd'],
        logger=logger,
    )

    log_open(logger, asset, 'long', entry_ts,
             pos_params['entry'], pos_params['sl'], pos_params['tp'])
    notify_trade_open(
        asset, 'long',
        pos_params['entry'], pos_params['sl'], pos_params['tp'],
        pos_params['risk_usd'],
    )

    logger.info(
        f'[{asset}] BREAKOUT {candle_date} | '
        f'close={last_candle["close"]:.2f}  nd_high={last_candle["nd_high"]:.2f}  '
        f'vol_ratio={last_candle["volume"]/last_candle["vol20"]:.2f}× | '
        f'entry={pos_params["entry"]:.2f}  sl={pos_params["sl"]:.2f}  '
        f'tp={pos_params["tp"]:.2f}  qty={pos_params["qty"]:.6f}  '
        f'risk_usd=${pos_params["risk_usd"]:.2f}'
    )
    return True


# ── Scan ──────────────────────────────────────────────────────────────────────

def run_scan(exchange, engines: dict, loggers: dict) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')

    for asset, cfg in ASSETS_CONFIG.items():
        engine = engines[asset]
        logger = loggers[asset]
        logger.info(f'\n[SCAN] {ts}')

        try:
            if engine.get_position(asset) is not None:
                # Ciclo 1: gestión de posición abierta
                check_open_position(exchange, asset, engine, logger)
            else:
                # Ciclo 2: detección de señal diaria
                check_daily_signal(exchange, asset, engine, logger)

        except Exception as e:
            logger.info(f'[{asset}] ERROR: {e}', exc_info=True)

        engine.print_summary(logger, label=f'{asset} BREAKOUT PAPER SUMMARY')


# ── Equity sync ───────────────────────────────────────────────────────────────

def _sync_equity_from_binance(engines: dict, loggers: dict) -> None:
    """
    On first deploy, init each engine's equity from the real Binance USDT spot balance.
    No-op if any engine already has trades (equity reflects paper P&L, not initial balance).
    """
    any_active = any(
        e.state.get('trades') or e.state.get('positions')
        for e in engines.values()
    )
    if any_active:
        return

    try:
        auth_exchange = create_futures_exchange()
        auth_exchange.timeout = 10000  # 10s max — non-fatal if it hangs
        balance = auth_exchange.fetch_balance()
        usdt_free = float(balance.get('USDT', {}).get('free', 0.0))
        if usdt_free <= 0:
            return
        for asset, engine in engines.items():
            logger = loggers[asset]
            engine.init_equity(usdt_free)
            logger.info(f'[INIT] Equity sincronizado desde Binance: {usdt_free:.2f} USDT')
    except Exception as e:
        # Non-fatal: fallback to whatever is in state
        first_logger = next(iter(loggers.values()))
        first_logger.info(f'[INIT] No se pudo sincronizar equity desde Binance: {e}')


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Daily Breakout Paper Trading Monitor')
    parser.add_argument(
        '--loop',
        action='store_true',
        help=f'Ejecutar en loop cada {SCAN_INTERVAL}s ({SCAN_INTERVAL//3600}h)',
    )
    args = parser.parse_args()

    log_date = datetime.now(timezone.utc).strftime('%Y%m%d')

    loggers = {
        asset: setup_logger(
            f'breakout_{cfg["log_prefix"]}',
            log_file=f'logs/{cfg["log_prefix"]}_{log_date}.log',
            mode='a',
        )
        for asset, cfg in ASSETS_CONFIG.items()
    }

    exchange = create_public_exchange()

    engines = {
        asset: PaperEngine(state_file=cfg['state_file'])
        for asset, cfg in ASSETS_CONFIG.items()
    }

    # Sync equity from real Binance balance if engines are in pristine state
    _sync_equity_from_binance(engines, loggers)

    if not args.loop:
        run_scan(exchange, engines, loggers)
        return

    for asset, cfg in ASSETS_CONFIG.items():
        loggers[asset].info(
            f'[MONITOR] Breakout Paper Trading iniciado | '
            f'intervalo={SCAN_INTERVAL}s | strategy=breakout_10d_vol1.5x'
        )

    while True:
        current_date = datetime.now(timezone.utc).strftime('%Y%m%d')
        if current_date != log_date:
            log_date = current_date
            for asset, cfg in ASSETS_CONFIG.items():
                loggers[asset] = setup_logger(
                    f'breakout_{cfg["log_prefix"]}',
                    log_file=f'logs/{cfg["log_prefix"]}_{log_date}.log',
                    mode='a',
                )
                loggers[asset].info(f'[MONITOR] Log rotado — nuevo día: {log_date}')

        run_scan(exchange, engines, loggers)
        time.sleep(SCAN_INTERVAL)


if __name__ == '__main__':
    main()
