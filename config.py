import os
from dotenv import load_dotenv

load_dotenv()

# Binance credentials — loaded from .env, never hardcoded
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET  = os.getenv("BINANCE_SECRET", "")

# Ed25519 private key — read from file path or inline env var
_key_file = os.getenv("BINANCE_PRIVATE_KEY_FILE", "")
if _key_file and os.path.exists(_key_file):
    with open(_key_file) as _f:
        BINANCE_PRIVATE_KEY = _f.read()
else:
    BINANCE_PRIVATE_KEY = os.getenv("BINANCE_PRIVATE_KEY", "")

if not BINANCE_API_KEY:
    raise EnvironmentError("BINANCE_API_KEY must be set in .env")

# Analysis target — BTC/USDT only (live monitoring)
SYMBOL = "BTC/USDT"

# Multi-coin research universe (backtesting and transferability analysis only)
SYMBOL_UNIVERSE = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "DOGE/USDT",
]

TIMEFRAME = os.getenv("TIMEFRAME", "1h")
CANDLE_LIMIT = int(os.getenv("CANDLE_LIMIT", "100"))

# Monitoring
MONITOR_INTERVAL_SECONDS = int(os.getenv("MONITOR_INTERVAL_SECONDS", "60"))

# Snapshot output directory
SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", "logs")

# Claude trade filter (disabled by default — set ENABLE_CLAUDE_FILTER=true to activate)
ENABLE_CLAUDE_FILTER = os.getenv("ENABLE_CLAUDE_FILTER", "false").lower() == "true"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_FILTER_MODEL = os.getenv("CLAUDE_FILTER_MODEL", "claude-haiku-4-5-20251001")
