import ccxt
import pandas as pd
from config import BINANCE_API_KEY, BINANCE_SECRET


def create_exchange() -> ccxt.binance:
    return ccxt.binance({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })


def ping_exchange(exchange: ccxt.binance) -> tuple[bool, str]:
    """
    Test connectivity by fetching BTC/USDT ticker.
    Returns (ok, message).
    """
    try:
        ticker = exchange.fetch_ticker("BTC/USDT")
        price  = ticker.get("last") or ticker.get("close")
        return True, f"BTC/USDT last={price}"
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
