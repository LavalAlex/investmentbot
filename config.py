import os
from dotenv import load_dotenv

load_dotenv()

# Binance credentials — loaded from .env, never hardcoded
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")

if not BINANCE_API_KEY or not BINANCE_SECRET:
    raise EnvironmentError("BINANCE_API_KEY and BINANCE_SECRET must be set in .env")

# Analysis target — BTC/USDT only
SYMBOL = "BTC/USDT"

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
