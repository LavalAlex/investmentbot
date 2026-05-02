import ccxt
import pandas as pd
from config import BINANCE_API_KEY, BINANCE_SECRET, BINANCE_PRIVATE_KEY


def create_exchange() -> ccxt.binance:
    return ccxt.binance({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })


def create_futures_exchange(testnet: bool = False) -> ccxt.binance:
    """Binance USDM Futures exchange. testnet=True uses testnet.binancefuture.com.
    Uses Ed25519 private key if BINANCE_PRIVATE_KEY is set, else falls back to HMAC secret.
    """
    secret = BINANCE_PRIVATE_KEY if BINANCE_PRIVATE_KEY else BINANCE_SECRET
    params = {
        "apiKey": BINANCE_API_KEY,
        "secret": secret,
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
            "fetchCurrencies": False,  # avoid SAPI spot endpoint on load_markets
        },
    }
    exchange = ccxt.binance(params)
    if testnet:
        exchange.set_sandbox_mode(True)
    return exchange


def ping_exchange(exchange: ccxt.binance) -> tuple[bool, str]:
    """
    Test connectivity using the same public klines endpoint the monitor uses.
    Avoids SAPI account endpoints that trigger geo-restrictions.
    Returns (ok, message).
    """
    try:
        raw = exchange.publicGetKlines({"symbol": "BTCUSDT", "interval": "1m", "limit": 1})
        close = float(raw[0][4]) if raw else None
        return True, f"BTC/USDT last={close}"
    except Exception as e:
        return False, str(e)


def fetch_ohlcv(exchange: ccxt.binance, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """
    Fetch OHLCV candles and return a DataFrame.
    Returns an empty DataFrame if data is unavailable or insufficient.
    """
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception as e:
        print(f"[exchange] fetch_ohlcv failed for {symbol}: {e}")
        return pd.DataFrame()

    if not raw or len(raw) < 2:
        print(f"[exchange] insufficient candle data for {symbol}")
        return pd.DataFrame()

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    return df
