"""
InvestmentBot Monitor API

Starts the paper trading monitor automatically in a background thread on startup.
Single deploy command:
    uvicorn api.main:app --host 0.0.0.0 --port 8000

Endpoints:
    GET /status              → equity, positions, trade summary per asset
    GET /trades              → full trade history with computed fields
                               ?asset=BTC/USDT|ETH/USDT   filter by asset
                               ?result=win|loss            filter by outcome
                               ?limit=N                    last N trades (default: all)
    GET /orders              → posiciones abiertas con SL/TP, precio actual y estado de órdenes Binance
    GET /logs/latest         → last scan block from the most recent log file
                               ?asset=btc|eth              (default: eth)
    GET /logs/download       → download log file(s)
                               ?asset=btc|eth              (default: eth)
                               ?date=YYYY-MM-DD            single day
                               ?from=YYYY-MM-DD&to=...     date range (zip if >1 file)
"""

import io
import json
import threading
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import logging
import os

logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')

# Pre-load heavy modules at process start so the monitor thread finds them cached
from core.exchange import create_exchange, create_futures_exchange, create_public_exchange, ping_exchange
from core.paper_engine import PaperEngine
from core.live_engine import LiveEngine
from core import gcs_storage
from core.logger_v2 import setup_logger
from core.order_monitor import run_loop as run_order_monitor, get_status as get_orders_status
from paper_monitor import run_scan, ASSETS_CONFIG, SCAN_INTERVAL, RISK_PCT

# Shared engine registry — populated by monitor thread, read by /reset
_engines: dict = {}
_engines_lock  = threading.Lock()

ORDER_MONITOR_INTERVAL = int(os.getenv('ORDER_MONITOR_INTERVAL', '5'))
_order_monitor_exchange = None  # set by monitor thread when exchange is ready

LOGS_DIR        = Path('logs')
INITIAL_CAPITAL = 10_000.0
LIVE_MODE       = os.getenv('LIVE_TRADING', '0') == '1'

_state_suffix = '_live' if LIVE_MODE else ''
STATE_FILES = {
    'BTC/USDT': Path(f'btc_state{_state_suffix}.json'),
    'ETH/USDT': Path(f'eth_state{_state_suffix}.json'),
}

LOG_PREFIXES = {
    'btc': 'BTC/USDT',
    'eth': 'ETH/USDT',
}


# ── Monitor background thread ─────────────────────────────────────────────────

_monitor_status: dict = {"binance_ok": None, "binance_msg": "", "started_at": None}


def _run_monitor() -> None:
    """Run the paper trading monitor loop in a background thread."""
    try:
        _run_monitor_inner()
    except Exception as e:
        import traceback
        print(f"[MONITOR] FATAL: {e}", flush=True)
        traceback.print_exc()


def _run_monitor_inner() -> None:
    import time
    print("[MONITOR] Thread started", flush=True)

    log_date = datetime.now(timezone.utc).strftime('%Y%m%d')

    # ── Credential check ──────────────────────────────────────────────────────
    from dotenv import load_dotenv
    load_dotenv()
    from pathlib import Path as _Path
    api_key     = os.getenv("BINANCE_API_KEY")
    secret      = os.getenv("BINANCE_SECRET", "")
    private_key = os.getenv("BINANCE_PRIVATE_KEY", "")
    private_key_file = any(_Path(p).exists() for p in [
        os.getenv("BINANCE_PRIVATE_KEY_FILE", ""),
        "/secrets/binance_private.pem",
        "binance_private.pem",
    ] if p)

    if not api_key or (not secret and not private_key and not private_key_file):
        fallback = setup_logger('paper_monitor_eth', log_file=f'logs/eth_{log_date}.log', mode='a')
        fallback.info("[MONITOR] ERROR — Missing Binance credentials.")
        _monitor_status["binance_ok"]  = False
        _monitor_status["binance_msg"] = "Missing credentials"
        return

    # ── Sync today's logs from GCS (resume after restart) ────────────────────
    print("[MONITOR] Syncing GCS logs...", flush=True)
    for asset, cfg in ASSETS_CONFIG.items():
        prefix = cfg['log_prefix']
        gcs_storage.download(f'logs/{prefix}_{log_date}.log', Path(f'logs/{prefix}_{log_date}.log'))

    print("[MONITOR] Creating loggers...", flush=True)
    loggers = {
        asset: setup_logger(
            f'paper_monitor_{cfg["log_prefix"]}',
            log_file=f'logs/{cfg["log_prefix"]}_{log_date}.log',
            mode='a',
        )
        for asset, cfg in ASSETS_CONFIG.items()
    }

    print("[MONITOR] Creating exchange...", flush=True)
    exchange = create_futures_exchange() if LIVE_MODE else create_public_exchange()
    if LIVE_MODE:
        global _order_monitor_exchange
        _order_monitor_exchange = exchange
    print("[MONITOR] Pinging Binance...", flush=True)
    ok, msg  = ping_exchange(create_public_exchange())
    _monitor_status["binance_ok"]  = ok
    _monitor_status["binance_msg"] = msg

    if not ok:
        for logger in loggers.values():
            logger.info(f"[MONITOR] ERROR — Binance connection failed: {msg}")
        return

    print(f"[MONITOR] Binance ping: ok={ok} msg={msg}", flush=True)
    if LIVE_MODE:
        print("[MONITOR] Creating LiveEngines...", flush=True)
        engines = {
            asset: LiveEngine(
                exchange=exchange,
                symbol=asset + ':USDT',
                state_file=cfg['state_file'].replace('.json', '_live.json'),
            )
            for asset, cfg in ASSETS_CONFIG.items()
        }
    else:
        engines = {
            asset: PaperEngine(state_file=cfg['state_file'])
            for asset, cfg in ASSETS_CONFIG.items()
        }
    with _engines_lock:
        _engines.update(engines)

    _monitor_status["started_at"] = datetime.now(timezone.utc).isoformat(timespec='seconds')

    for asset, cfg in ASSETS_CONFIG.items():
        logger = loggers[asset]
        engine = engines[asset]
        logger.info(f"[MONITOR] {'─'*50}")
        logger.info(f"[MONITOR] {cfg['label']}")
        logger.info(f"[MONITOR] Binance OK  : {msg}")
        logger.info(f"[MONITOR] SL min      : {cfg['min_sl_dist_pct']*100:.2f}%")
        logger.info(f"[MONITOR] Risk        : {RISK_PCT*100:.0f}% equity/trade  |  R:R 2:1")
        logger.info(f"[MONITOR] Equity      : {engine.equity:.2f} USD")
        logger.info(f"[MONITOR] Interval    : {SCAN_INTERVAL}s")
        logger.info(f"[MONITOR] {'─'*50}")

    last_candle_ts: dict = {}
    last_heartbeat: float = 0.0  # force send on startup

    while True:
        current_date = datetime.now(timezone.utc).strftime('%Y%m%d')
        if current_date != log_date:
            log_date = current_date
            for asset, cfg in ASSETS_CONFIG.items():
                prefix = cfg['log_prefix']
                gcs_storage.download(f'logs/{prefix}_{log_date}.log', Path(f'logs/{prefix}_{log_date}.log'))
                loggers[asset] = setup_logger(
                    f'paper_monitor_{prefix}',
                    log_file=f'logs/{prefix}_{log_date}.log',
                    mode='a',
                )
                loggers[asset].info(f"[MONITOR] Log rotated — new day: {log_date}")

        with _engines_lock:
            run_scan(exchange, engines, loggers, last_candle_ts, live=LIVE_MODE)

        for asset, cfg in ASSETS_CONFIG.items():
            prefix = cfg['log_prefix']
            gcs_storage.upload(Path(f'logs/{prefix}_{log_date}.log'), f'logs/{prefix}_{log_date}.log')

        if time.time() - last_heartbeat >= 43200:
            try:
                from core.notifier import notify_daily_status
                notify_daily_status(engines)
                last_heartbeat = time.time()
            except Exception as e:
                print(f'[HEARTBEAT] Error: {e}', flush=True)

        time.sleep(SCAN_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_run_monitor, daemon=True, name='paper-monitor')
    t.start()
    if LIVE_MODE:
        om = threading.Thread(
            target=_run_order_monitor, daemon=True, name='order-monitor'
        )
        om.start()
    yield


def _run_order_monitor() -> None:
    global _order_monitor_exchange
    import time as _time
    # Esperar a que el monitor principal inicialice el exchange
    for _ in range(60):
        if _order_monitor_exchange is not None:
            break
        _time.sleep(1)
    if _order_monitor_exchange is None:
        print('[ORDER_MONITOR] Exchange no disponible — abortando', flush=True)
        return
    run_order_monitor(
        _order_monitor_exchange, _engines, _engines_lock,
        live_mode=LIVE_MODE,
        interval=ORDER_MONITOR_INTERVAL,
    )


app = FastAPI(title='InvestmentBot Monitor', version='2.0', lifespan=lifespan)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_state(asset: str | None = None) -> dict:
    """Load state for one asset, or merge both if asset is None."""
    if asset and asset in STATE_FILES:
        p = STATE_FILES[asset]
        if p.exists():
            with open(p) as f:
                return json.load(f)
        return {'equity': INITIAL_CAPITAL, 'positions': {}, 'trades': []}

    # Merge both states: combined trade list, combined positions, separate equities
    combined = {'equities': {}, 'positions': {}, 'trades': []}
    for sym, p in STATE_FILES.items():
        if p.exists():
            with open(p) as f:
                s = json.load(f)
        else:
            s = {'equity': INITIAL_CAPITAL, 'positions': {}, 'trades': []}
        combined['equities'][sym] = s.get('equity', INITIAL_CAPITAL)
        combined['positions'].update(s.get('positions', {}))
        combined['trades'].extend(s.get('trades', []))

    combined['trades'].sort(key=lambda t: t.get('close_ts', ''))
    return combined


def _last_scan_block(log_path: Path) -> str:
    if not log_path.exists():
        return ''
    text = log_path.read_text(encoding='utf-8')
    idx = text.rfind('[SCAN]')
    return text[idx:].strip() if idx != -1 else text.strip()


def _most_recent_log(prefix: str = 'eth') -> Optional[Path]:
    logs = sorted(LOGS_DIR.glob(f'{prefix}_*.log'))
    return logs[-1] if logs else None


def _log_for_date(date_str: str, prefix: str = 'eth') -> Path:
    return LOGS_DIR / f"{prefix}_{date_str.replace('-', '')}.log"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get('/status')
def get_status():
    """Equity, positions, and trade stats — per asset and combined."""
    with _engines_lock:
        live_engines = dict(_engines)

    def _asset_stats(trades: list, equity: float, initial_equity: float = INITIAL_CAPITAL) -> dict:
        wins         = sum(1 for t in trades if t.get('pnl', 0) > 0)
        pnl_total    = sum(t.get('pnl', 0) for t in trades)
        gross_profit = sum(t['pnl'] for t in trades if t.get('pnl', 0) > 0)
        gross_loss   = abs(sum(t['pnl'] for t in trades if t.get('pnl', 0) <= 0))
        pf           = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None
        return {
            'equity':        round(equity, 2),
            'return_pct':    round((equity - initial_equity) / initial_equity * 100, 2) if initial_equity else 0.0,
            'total_pnl':     round(pnl_total, 2),
            'total_trades':  len(trades),
            'wins':          wins,
            'losses':        len(trades) - wins,
            'win_rate_pct':  round(wins / len(trades) * 100, 1) if trades else None,
            'profit_factor': pf,
        }

    today    = datetime.now(timezone.utc).strftime('%Y%m%d')
    last_scans = {}
    for prefix in ('btc', 'eth'):
        log_path = LOGS_DIR / f'{prefix}_{today}.log'
        if not log_path.exists():
            log_path = _most_recent_log(prefix)
        last_scan = None
        if log_path and log_path.exists():
            text = log_path.read_text(encoding='utf-8')
            idx  = text.rfind('[SCAN]')
            if idx != -1:
                last_scan = text[idx:].split('\n')[0].replace('[SCAN]', '').strip()
        last_scans[prefix] = last_scan

    per_asset     = {}
    total_equity  = 0.0
    total_initial = 0.0

    for sym in STATE_FILES:
        engine = live_engines.get(sym)
        if engine:
            equity          = engine.equity
            trades          = engine.state.get('trades', [])
            pos             = engine.state.get('positions', {})
            initial_equity  = engine.state.get('initial_equity', INITIAL_CAPITAL)
        else:
            s               = _load_state(sym)
            equity          = s.get('equity', INITIAL_CAPITAL)
            trades          = s.get('trades', [])
            pos             = s.get('positions', {})
            initial_equity  = s.get('initial_equity', INITIAL_CAPITAL)
        total_equity    += equity
        total_initial   += initial_equity
        stats = _asset_stats(trades, equity, initial_equity)
        stats['open_positions'] = pos
        per_asset[sym] = stats

    return {
        'total_equity':     round(total_equity, 2),
        'total_return_pct': round((total_equity - total_initial) / total_initial * 100, 2) if total_initial else 0.0,
        'last_scans':       last_scans,
        'assets':           per_asset,
    }


@app.get('/trades')
def get_trades(
    asset:  Optional[str] = Query(None, description='Filter: BTC/USDT or ETH/USDT'),
    result: Optional[str] = Query(None, description='Filter: win or loss'),
    limit:  Optional[int] = Query(None, description='Last N trades (default: all)'),
):
    """Full trade history. Sorted newest first."""
    with _engines_lock:
        live_engines = dict(_engines)

    if asset and asset in STATE_FILES:
        engine = live_engines.get(asset)
        if engine:
            trades = engine.state.get('trades', [])
            equity = engine.equity
        else:
            s      = _load_state(asset)
            trades = s.get('trades', [])
            equity = s.get('equity', INITIAL_CAPITAL)
    else:
        trades = []
        equity = 0.0
        for sym in STATE_FILES:
            engine = live_engines.get(sym)
            if engine:
                trades.extend(engine.state.get('trades', []))
                equity += engine.equity
            else:
                s = _load_state(sym)
                trades.extend(s.get('trades', []))
                equity += s.get('equity', INITIAL_CAPITAL)
        trades.sort(key=lambda t: t.get('close_ts', ''))

    def _enrich(t: dict, idx_from_end: int) -> dict:
        pnl       = t.get('pnl', 0.0)
        entry     = t.get('entry', 0.0)
        exit_px   = t.get('exit', 0.0)
        direction = t.get('direction', '')
        reason    = t.get('reason', '')

        outcome = 'win' if pnl > 0 else ('loss' if pnl < 0 else 'breakeven')

        duration_min = None
        try:
            open_dt  = datetime.fromisoformat(t['open_ts'])
            close_dt = datetime.fromisoformat(t['close_ts'])
            duration_min = round((close_dt - open_dt).total_seconds() / 60, 1)
        except Exception:
            pass

        move_pct = None
        if entry:
            raw = (exit_px - entry) / entry * 100
            move_pct = round(raw if direction == 'long' else -raw, 3)

        equity_before = t.get('equity', 0.0) - pnl
        pnl_pct = round(pnl / equity_before * 100, 3) if equity_before else None

        reason_label = {
            'TP': 'Take Profit',
            'SL': 'Stop Loss',
            'BE': 'Break-Even Stop',
        }.get(reason, reason)

        return {
            'n':             idx_from_end,
            'asset':         t.get('asset'),
            'type':          direction,
            'result':        outcome,
            'entry':         entry,
            'exit':          exit_px,
            'sl':            t.get('sl'),
            'tp':            t.get('tp'),
            'qty':           round(t.get('qty', 0), 6),
            'open_ts':       t.get('open_ts'),
            'close_ts':      t.get('close_ts'),
            'duration_min':  duration_min,
            'move_pct':      move_pct,
            'pnl_usd':       round(pnl, 2),
            'pnl_pct':       pnl_pct,
            'equity_after':  round(t.get('equity', 0.0), 2),
            'exit_reason':   reason_label,
            'be_triggered':  t.get('be_triggered', False),
        }

    enriched = [_enrich(t, len(trades) - i) for i, t in enumerate(reversed(trades))]

    if result:
        enriched = [t for t in enriched if t['result'] == result]
    if limit and limit > 0:
        enriched = enriched[:limit]

    wins         = sum(1 for t in enriched if t['result'] == 'win')
    total_pnl    = sum(t['pnl_usd'] for t in enriched)
    gross_profit = sum(t['pnl_usd'] for t in enriched if t['pnl_usd'] > 0)
    gross_loss   = abs(sum(t['pnl_usd'] for t in enriched if t['pnl_usd'] < 0))
    pf           = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None
    avg_win      = round(gross_profit / wins, 2) if wins else None
    avg_loss     = round(gross_loss / (len(enriched) - wins), 2) if (len(enriched) - wins) else None

    return {
        'summary': {
            'equity':        round(equity, 2) if isinstance(equity, float) else equity,
            'return_pct':    round((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2) if isinstance(equity, float) else None,
            'total_trades':  len(enriched),
            'wins':          wins,
            'losses':        len(enriched) - wins,
            'win_rate_pct':  round(wins / len(enriched) * 100, 1) if enriched else None,
            'profit_factor': pf,
            'total_pnl_usd': round(total_pnl, 2),
            'avg_win_usd':   avg_win,
            'avg_loss_usd':  avg_loss,
        },
        'trades': enriched,
    }


@app.get('/logs/latest')
def get_latest_logs(
    asset: Optional[str] = Query('eth', description='Asset prefix: btc or eth'),
):
    """Last scan block from the most recent log file for the specified asset."""
    prefix   = asset.lower() if asset else 'eth'
    today    = datetime.now(timezone.utc).strftime('%Y%m%d')
    log_path = LOGS_DIR / f'{prefix}_{today}.log'

    if not log_path.exists():
        log_path = _most_recent_log(prefix)

    if log_path is None:
        raise HTTPException(status_code=404, detail=f'No log files found for {prefix}.')

    block = _last_scan_block(log_path)
    if not block:
        raise HTTPException(status_code=404, detail=f'Log file {log_path.name} is empty.')

    return {
        'file':      log_path.name,
        'last_scan': block,
    }


@app.get('/logs/download')
def download_logs(
    asset:     Optional[str] = Query('eth', description='Asset prefix: btc or eth'),
    date:      Optional[str] = Query(None, description='Single date: YYYY-MM-DD'),
    from_date: Optional[str] = Query(None, alias='from', description='Range start: YYYY-MM-DD'),
    to_date:   Optional[str] = Query(None, alias='to',   description='Range end:   YYYY-MM-DD'),
):
    """Download log file(s) for a given asset prefix (btc or eth)."""
    prefix = asset.lower() if asset else 'eth'

    if date:
        path = _log_for_date(date, prefix)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f'No log found for {prefix}/{date}.')
        return FileResponse(str(path), filename=path.name, media_type='text/plain')

    if from_date and to_date:
        try:
            start = datetime.strptime(from_date, '%Y-%m-%d')
            end   = datetime.strptime(to_date,   '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail='Dates must be YYYY-MM-DD.')
        if start > end:
            raise HTTPException(status_code=400, detail="'from' must be <= 'to'.")

        files = []
        day = start
        while day <= end:
            p = _log_for_date(day.strftime('%Y-%m-%d'), prefix)
            if p.exists():
                files.append(p)
            day += timedelta(days=1)

        if not files:
            raise HTTPException(status_code=404, detail='No logs found in that date range.')

        if len(files) == 1:
            return FileResponse(str(files[0]), filename=files[0].name, media_type='text/plain')

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, f.name)
        buf.seek(0)
        zip_name = f'logs_{prefix}_{from_date}_to_{to_date}.zip'
        return StreamingResponse(
            buf,
            media_type='application/zip',
            headers={'Content-Disposition': f'attachment; filename={zip_name}'},
        )

    raise HTTPException(
        status_code=400,
        detail="Provide 'date' for a single day, or both 'from' and 'to' for a range.",
    )


@app.post('/reset')
def post_reset():
    """
    Reset paper trading to a clean initial state.

    Actions (atomic under engine lock):
      1. Reset in-memory engine state for all assets (equity, positions, trades)
      2. Persist fresh state files to disk and GCS
      3. Delete all local log files

    The monitor thread continues running — next scan starts from clean state.
    Call /status immediately after to confirm equity = 10 000 per asset.
    """
    from core import gcs_storage

    reset_time = datetime.now(timezone.utc).isoformat(timespec='seconds')
    results    = {}

    with _engines_lock:
        if not _engines:
            raise HTTPException(
                status_code=503,
                detail='Monitor not ready yet — engines not initialised.',
            )

        for asset, engine in _engines.items():
            engine.reset()
            results[asset] = {
                'equity':    engine.equity,
                'positions': engine.state.get('positions', {}),
                'trades':    len(engine.state.get('trades', [])),
            }

    # Delete local logs
    deleted_logs = []
    if LOGS_DIR.exists():
        for f in sorted(LOGS_DIR.iterdir()):
            if f.is_file() and f.suffix == '.log':
                f.unlink()
                deleted_logs.append(f.name)

    # Delete GCS logs
    gcs_logs_deleted = 0
    try:
        bucket_name = __import__('os').getenv('GCS_BUCKET', '')
        if bucket_name:
            from google.cloud import storage
            bucket = storage.Client().bucket(bucket_name)
            for blob in bucket.list_blobs(prefix='logs/'):
                blob.delete()
                gcs_logs_deleted += 1
    except Exception:
        pass

    return {
        'reset_at':        reset_time,
        'assets':          results,
        'logs_deleted':    deleted_logs,
        'gcs_logs_deleted': gcs_logs_deleted,
    }


@app.get('/orders')
def get_orders():
    """
    Posiciones abiertas con SL/TP, precio actual y estado de órdenes Binance.

    Campos por posición:
      - entry / current_price / sl / tp / qty
      - dist_sl_pct / dist_tp_pct — distancia en % al SL y TP
      - pnl_usd — PnL no realizado
      - binance_sl_active / binance_tp_active — si la orden algo sigue viva en Binance
      - sl_order_id / tp_order_id — algoId de cada orden
    """
    with _engines_lock:
        live_engines = dict(_engines)

    exchange = _order_monitor_exchange or (
        create_futures_exchange() if LIVE_MODE else None
    )
    if exchange is None:
        return {'orders': [], 'monitor': 'paper_mode'}

    orders = get_orders_status(exchange, live_engines, _engines_lock, LIVE_MODE)
    return {
        'monitor_interval_s': ORDER_MONITOR_INTERVAL,
        'live_mode':          LIVE_MODE,
        'orders':             orders,
    }


@app.post('/wsp')
def post_wsp():
    """Send WhatsApp status message on demand."""
    from core.notifier import notify_daily_status
    with _engines_lock:
        live_engines = dict(_engines)
    if not live_engines:
        raise HTTPException(status_code=503, detail='Monitor not ready yet.')
    sent = notify_daily_status(live_engines)
    return {'sent': sent}


class OpenRequest(BaseModel):
    asset:     str            # "BTC/USDT" or "ETH/USDT"
    direction: str            # "long" or "short"
    sl_pct:    float          # SL distance as % of entry price, e.g. 0.5
    tp_pct:    float          # TP distance as % of entry price, e.g. 1.0
    risk_usd:  Optional[float] = None  # if None → 1% of equity


class CloseRequest(BaseModel):
    asset:  str
    reason: str = 'MANUAL'


@app.post('/open')
def post_open(
    req:     OpenRequest,
    confirm: bool = Query(False, description='Must be true to execute real order'),
):
    """
    Manually open a position for testing.
    Fetches current market price, computes SL/TP/qty, then calls engine.open_position().
    Only works in LIVE_MODE. Requires ?confirm=true.
    """
    if not LIVE_MODE:
        raise HTTPException(status_code=400, detail='Only available in live mode (LIVE_TRADING=1).')
    if not confirm:
        raise HTTPException(status_code=400, detail='Pass ?confirm=true to execute a real order.')
    if req.direction not in ('long', 'short'):
        raise HTTPException(status_code=400, detail='direction must be "long" or "short".')

    with _engines_lock:
        engine = _engines.get(req.asset)
    if engine is None:
        raise HTTPException(status_code=503, detail=f'Engine for {req.asset!r} not ready. Valid assets: {list(STATE_FILES.keys())}')

    if engine.get_position(req.asset) is not None:
        raise HTTPException(status_code=409, detail=f'{req.asset} already has an open position.')

    exchange = _order_monitor_exchange
    if exchange is None:
        raise HTTPException(status_code=503, detail='Exchange not available yet.')

    ticker    = exchange.fetch_ticker(req.asset + ':USDT')
    entry     = float(ticker['last'])
    sl_dist   = entry * req.sl_pct / 100
    tp_dist   = entry * req.tp_pct / 100

    if req.direction == 'long':
        sl, tp = entry - sl_dist, entry + tp_dist
    else:
        sl, tp = entry + sl_dist, entry - tp_dist

    risk_usd = req.risk_usd if req.risk_usd is not None else engine.equity * 0.01
    qty      = risk_usd / sl_dist
    ts       = datetime.now(timezone.utc).isoformat(timespec='seconds') + '+00:00'

    ok = engine.open_position(req.asset, req.direction, entry, sl, tp, qty, ts, risk_usd)
    if not ok:
        raise HTTPException(status_code=500, detail='open_position failed — check logs (qty below min?).')

    return {
        'opened':        True,
        'asset':         req.asset,
        'direction':     req.direction,
        'entry_approx':  entry,
        'sl':            round(sl, 4),
        'tp':            round(tp, 4),
        'qty_approx':    round(qty, 6),
        'risk_usd':      round(risk_usd, 2),
    }


@app.post('/close')
def post_close(
    req:     CloseRequest,
    confirm: bool = Query(False, description='Must be true to execute real order'),
):
    """
    Manually close an open position for testing.
    Cancels pending SL/TP orders, places a MARKET close, records the trade.
    Only works in LIVE_MODE. Requires ?confirm=true.
    """
    if not LIVE_MODE:
        raise HTTPException(status_code=400, detail='Only available in live mode (LIVE_TRADING=1).')
    if not confirm:
        raise HTTPException(status_code=400, detail='Pass ?confirm=true to execute a real order.')
    with _engines_lock:
        engine = _engines.get(req.asset)
    if engine is None:
        raise HTTPException(status_code=503, detail=f'Engine for {req.asset!r} not ready.')

    pos = engine.get_position(req.asset)
    if pos is None:
        raise HTTPException(status_code=404, detail=f'No open position for {req.asset}.')

    exchange = _order_monitor_exchange
    if exchange is None:
        raise HTTPException(status_code=503, detail='Exchange not available yet.')

    direction = pos['direction']
    qty       = pos['qty']
    side      = 'SELL' if direction == 'long' else 'BUY'

    # Cancel all pending SL/TP orders before placing market close
    try:
        engine._cancel_open_orders(engine._symbol)
    except Exception as e:
        pass  # best-effort; MARKET reduceOnly will still close the position

    try:
        close_order = exchange.create_order(
            engine._symbol, 'MARKET', side, qty,
            params={'reduceOnly': True},
        )
        fill_price = float(close_order.get('average') or close_order.get('price') or 0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'MARKET close order failed: {e}')

    close_ts = datetime.now(timezone.utc).isoformat(timespec='seconds') + '+00:00'

    with _engines_lock:
        trade = engine.record_close(req.asset, fill_price, req.reason, close_ts)

    if trade is None:
        return {
            'closed':     True,
            'note':       'record_close returned None — WS may have already processed this close.',
            'fill_price': fill_price,
        }

    return {
        'closed':    True,
        'asset':     req.asset,
        'direction': direction,
        'reason':    req.reason,
        'fill_price': fill_price,
        'pnl_usd':   round(trade['pnl'], 4),
        'equity':    round(trade['equity'], 2),
    }


@app.get('/health')
def get_health():
    """Service health — API status, Binance connectivity, monitor state, per-asset equity."""
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    last_scans = {}
    for prefix in ('btc', 'eth'):
        log_path = LOGS_DIR / f'{prefix}_{today}.log'
        if not log_path.exists():
            log_path = _most_recent_log(prefix)
        last_scan = None
        if log_path and log_path.exists():
            text = log_path.read_text(encoding='utf-8')
            idx  = text.rfind('[SCAN]')
            if idx != -1:
                last_scan = text[idx:].split('\n')[0].replace('[SCAN]', '').strip()
        last_scans[prefix] = last_scan

    per_asset = {}
    with _engines_lock:
        live_engines = dict(_engines)

    for sym in STATE_FILES:
        engine = live_engines.get(sym)
        if engine:
            equity = engine.equity
            trades = engine.state.get('trades', [])
            pos    = engine.state.get('positions', {})
        else:
            s      = _load_state(sym)
            equity = s.get('equity', INITIAL_CAPITAL)
            trades = s.get('trades', [])
            pos    = s.get('positions', {})
        wins   = sum(1 for t in trades if t.get('pnl', 0) > 0)
        pnl    = sum(t.get('pnl', 0) for t in trades)
        per_asset[sym] = {
            'equity':         round(equity, 2),
            'mode':           'live' if LIVE_MODE else 'paper',
            'total_trades':   len(trades),
            'wins':           wins,
            'losses':         len(trades) - wins,
            'total_pnl':      round(pnl, 2),
            'open_positions': list(pos.keys()),
        }

    binance_ok = _monitor_status.get("binance_ok")

    return {
        'api':     'ok',
        'mode':    'live' if LIVE_MODE else 'paper',
        'binance': {
            'connected': binance_ok,
            'detail':    _monitor_status.get("binance_msg", ""),
        },
        'monitor': {
            'running':    binance_ok is True,
            'started_at': _monitor_status.get("started_at"),
            'last_scans': last_scans,
        },
        'assets': per_asset,
    }
