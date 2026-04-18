"""
InvestmentBot Monitor API

Starts the paper trading monitor automatically in a background thread on startup.
Single deploy command:
    uvicorn api.main:app --host 0.0.0.0 --port 8000

Endpoints:
    GET /status              → equity, positions, trade summary, last scan timestamp
    GET /logs/latest         → last scan block from the most recent log file
    GET /logs/download       → download log file(s)
                               ?date=YYYY-MM-DD          single day
                               ?from=YYYY-MM-DD&to=...   date range (returns zip if >1 file)
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

LOGS_DIR        = Path('logs')
STATE_FILE      = Path('paper_state.json')
INITIAL_CAPITAL = 10_000.0


# ── Monitor background thread ─────────────────────────────────────────────────

_monitor_status: dict = {"binance_ok": None, "binance_msg": "", "started_at": None}


def _run_monitor() -> None:
    """Run the paper trading monitor loop in a background thread."""
    import time
    import os
    from core.logger_v2 import setup_logger

    log_date = datetime.now(timezone.utc).strftime('%Y%m%d')
    logger   = setup_logger('paper_monitor', log_file=f'logs/paper_{log_date}.log', mode='a')

    # ── Credential check ──────────────────────────────────────────────────────
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("BINANCE_API_KEY")
    secret  = os.getenv("BINANCE_SECRET")
    if not api_key or not secret:
        logger.info("[MONITOR] ERROR — Missing Binance credentials. Set BINANCE_API_KEY and BINANCE_SECRET.")
        _monitor_status["binance_ok"]  = False
        _monitor_status["binance_msg"] = "Missing credentials"
        return

    # ── Connectivity check ────────────────────────────────────────────────────
    try:
        from core.exchange import create_exchange, ping_exchange
        from core.paper_engine import PaperEngine
        from paper_monitor import run_scan, ASSETS, SCAN_INTERVAL, RISK_PCT
    except Exception as e:
        logger.info(f"[MONITOR] ERROR — Failed to load modules: {e}")
        _monitor_status["binance_ok"]  = False
        _monitor_status["binance_msg"] = str(e)
        return

    exchange = create_exchange()
    ok, msg  = ping_exchange(exchange)
    _monitor_status["binance_ok"]  = ok
    _monitor_status["binance_msg"] = msg

    if not ok:
        logger.info(f"[MONITOR] ERROR — Binance connection failed: {msg}")
        return

    logger.info(f"[MONITOR] Binance connection OK — {msg}")

    # ── Start loop ────────────────────────────────────────────────────────────
    engine         = PaperEngine()
    last_candle_ts: dict = {}
    _monitor_status["started_at"] = datetime.now(timezone.utc).isoformat(timespec='seconds')

    logger.info(f"[MONITOR] EXP002 paper trading started.")
    logger.info(f"[MONITOR] Assets: {ASSETS} | Risk: {RISK_PCT*100:.0f}% | Interval: {SCAN_INTERVAL}s")

    while True:
        current_date = datetime.now(timezone.utc).strftime('%Y%m%d')
        if current_date != log_date:
            log_date = current_date
            logger   = setup_logger('paper_monitor', log_file=f'logs/paper_{log_date}.log', mode='a')
            logger.info(f"[MONITOR] Log rotated — new day: {log_date}")

        run_scan(exchange, engine, logger, last_candle_ts)
        time.sleep(SCAN_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_run_monitor, daemon=True, name='paper-monitor')
    t.start()
    yield


app = FastAPI(title='InvestmentBot Monitor', version='1.0', lifespan=lifespan)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'equity': INITIAL_CAPITAL, 'positions': {}, 'trades': []}


def _last_scan_block(log_path: Path) -> str:
    """Return everything from the last [SCAN] line to end of file."""
    if not log_path.exists():
        return ''
    text = log_path.read_text(encoding='utf-8')
    idx = text.rfind('[SCAN]')
    return text[idx:].strip() if idx != -1 else text.strip()


def _most_recent_log() -> Optional[Path]:
    logs = sorted(LOGS_DIR.glob('paper_*.log'))
    return logs[-1] if logs else None


def _log_for_date(date_str: str) -> Path:
    """date_str = YYYY-MM-DD"""
    return LOGS_DIR / f"paper_{date_str.replace('-', '')}.log"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get('/status')
def get_status():
    """Current equity, open positions, trade statistics, and last scan time."""
    state  = _load_state()
    trades = state.get('trades', [])
    equity = state.get('equity', INITIAL_CAPITAL)

    wins   = sum(1 for t in trades if t.get('pnl', 0) > 0)
    losses = len(trades) - wins
    pnl_total = sum(t.get('pnl', 0) for t in trades)
    gross_profit = sum(t['pnl'] for t in trades if t.get('pnl', 0) > 0)
    gross_loss   = abs(sum(t['pnl'] for t in trades if t.get('pnl', 0) <= 0))
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None

    # Last scan timestamp from today's log (or most recent)
    today    = datetime.now(timezone.utc).strftime('%Y%m%d')
    log_path = LOGS_DIR / f'paper_{today}.log'
    if not log_path.exists():
        log_path = _most_recent_log()

    last_scan = None
    if log_path and log_path.exists():
        text = log_path.read_text(encoding='utf-8')
        idx  = text.rfind('[SCAN]')
        if idx != -1:
            last_scan = text[idx:].split('\n')[0].replace('[SCAN]', '').strip()

    return {
        'equity':         round(equity, 2),
        'return_pct':     round((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'total_pnl':      round(pnl_total, 2),
        'total_trades':   len(trades),
        'wins':           wins,
        'losses':         losses,
        'win_rate_pct':   round(wins / len(trades) * 100, 1) if trades else None,
        'profit_factor':  profit_factor,
        'open_positions': state.get('positions', {}),
        'last_scan':      last_scan,
    }


@app.get('/logs/latest')
def get_latest_logs():
    """Last scan block (signals, status, summary) from the most recent log file."""
    today    = datetime.now(timezone.utc).strftime('%Y%m%d')
    log_path = LOGS_DIR / f'paper_{today}.log'

    if not log_path.exists():
        log_path = _most_recent_log()

    if log_path is None:
        raise HTTPException(status_code=404, detail='No log files found.')

    block = _last_scan_block(log_path)
    if not block:
        raise HTTPException(status_code=404, detail=f'Log file {log_path.name} is empty.')

    return {
        'file':      log_path.name,
        'last_scan': block,
    }


@app.get('/logs/download')
def download_logs(
    date: Optional[str]      = Query(None, description='Single date: YYYY-MM-DD'),
    from_date: Optional[str] = Query(None, alias='from', description='Range start: YYYY-MM-DD'),
    to_date: Optional[str]   = Query(None, alias='to',   description='Range end:   YYYY-MM-DD'),
):
    """
    Download log file(s).
    - Single day:  ?date=2026-04-18
    - Date range:  ?from=2026-04-15&to=2026-04-18  (zip if more than one file)
    """
    if date:
        path = _log_for_date(date)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f'No log found for {date}.')
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
            p = _log_for_date(day.strftime('%Y-%m-%d'))
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
        zip_name = f'logs_{from_date}_to_{to_date}.zip'
        return StreamingResponse(
            buf,
            media_type='application/zip',
            headers={'Content-Disposition': f'attachment; filename={zip_name}'},
        )

    raise HTTPException(
        status_code=400,
        detail="Provide 'date' for a single day, or both 'from' and 'to' for a range.",
    )


@app.get('/health')
def get_health():
    """Service health — API status, Binance connectivity, monitor state, and uptime info."""
    state  = _load_state()
    trades = state.get('trades', [])
    equity = state.get('equity', INITIAL_CAPITAL)

    # Most recent log file
    today    = datetime.now(timezone.utc).strftime('%Y%m%d')
    log_path = LOGS_DIR / f'paper_{today}.log'
    if not log_path.exists():
        log_path = _most_recent_log()

    last_scan = None
    if log_path and log_path.exists():
        text = log_path.read_text(encoding='utf-8')
        idx  = text.rfind('[SCAN]')
        if idx != -1:
            last_scan = text[idx:].split('\n')[0].replace('[SCAN]', '').strip()

    binance_ok = _monitor_status.get("binance_ok")

    return {
        "api":     "ok",
        "binance": {
            "connected": binance_ok,
            "detail":    _monitor_status.get("binance_msg", ""),
        },
        "monitor": {
            "running":    binance_ok is True,
            "started_at": _monitor_status.get("started_at"),
            "last_scan":  last_scan,
        },
        "paper_trading": {
            "equity":       round(equity, 2),
            "return_pct":   round((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
            "total_trades": len(trades),
            "open_positions": list(state.get("positions", {}).keys()),
        },
    }
