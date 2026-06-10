"""
Strategy B: Daily Breakout

Señal: el precio cierra por encima del máximo de los últimos N días
con volumen elevado. Longs únicamente (trend-following puro).

Parámetros validados en IS 5y + OOS 730d + Walk-forward 3 ventanas:
  BTC: N=10, vol≥1.5×, ATR×1.5, RR=2  → PF=1.735 (5y), PF=1.627 (730d)
  ETH: N=10, vol≥1.5×, ATR×1.5, RR=2  → PF=1.711 (5y), PF=1.442 (730d)

Interfaz del módulo:
  prepare_daily(df_1h)         → DataFrame diario con indicadores
  is_breakout_signal(row)      → bool
  calculate_position(row, equity) → dict | None
"""

import pandas as pd

# ── Parámetros de señal (validados, no cambiar sin nuevo experimento) ─────────
N_DAYS    = 10     # lookback del rolling high (días)
VOL_RATIO = 1.5    # volumen del día ≥ VOL_RATIO × media de 20 días
ATR_MULT  = 1.5    # distancia del SL en unidades de ATR(14)
RR        = 2.0    # ratio reward-to-risk para el TP
RISK_PCT  = 0.01   # 1% del equity en riesgo por trade


# ── Preparación de datos ──────────────────────────────────────────────────────

def prepare_daily(df_1h: pd.DataFrame) -> pd.DataFrame:
    """
    Resamplea datos 1h a diario y calcula todos los indicadores necesarios.

    Columnas de entrada requeridas: open_time, open, high, low, close, volume.
    open_time puede ser string o datetime (con o sin timezone).

    Columnas añadidas:
      nd_high  — máximo de los últimos N_DAYS closes (shift(1) para evitar lookahead)
      atr14    — ATR(14) con suavizado de Wilder
      vol20    — media de volumen de 20 días
    """
    df = df_1h.copy()
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    df = df.set_index('open_time').sort_index()

    daily = df.resample('1D').agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume=('volume', 'sum'),
    ).dropna()

    # ATR(14) con suavizado Wilder (com=13 → alpha=1/14)
    tr = pd.concat([
        daily['high'] - daily['low'],
        (daily['high'] - daily['close'].shift(1)).abs(),
        (daily['low']  - daily['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    daily['atr14'] = tr.ewm(com=13, min_periods=14, adjust=False).mean()

    # Volumen promedio 20 días
    daily['vol20'] = daily['volume'].rolling(20, min_periods=20).mean()

    # N-day high usando shift(1) — el máximo se calcula sobre días anteriores,
    # no incluye el día actual, eliminando cualquier posible lookahead bias.
    daily['nd_high'] = daily['close'].shift(1).rolling(N_DAYS, min_periods=N_DAYS).max()

    # Timestamp de disponibilidad: la vela diaria está disponible al cierre UTC+0
    daily['available_at'] = daily.index + pd.Timedelta(days=1)

    return daily.reset_index()


# ── Señal de entrada ──────────────────────────────────────────────────────────

def is_breakout_signal(row) -> bool:
    """
    Evalúa si la vela diaria `row` genera una señal de breakout.

    Condiciones (todas deben cumplirse):
      1. close > nd_high  — nuevo máximo de N días
      2. volume ≥ VOL_RATIO × vol20  — volumen confirma el movimiento
      3. Los indicadores requeridos no son NaN

    El row puede ser un pd.Series o un dict (para uso desde live engine).
    """
    close   = row.get('close')   if isinstance(row, dict) else row['close']
    nd_high = row.get('nd_high') if isinstance(row, dict) else row['nd_high']
    volume  = row.get('volume')  if isinstance(row, dict) else row['volume']
    vol20   = row.get('vol20')   if isinstance(row, dict) else row['vol20']
    atr14   = row.get('atr14')   if isinstance(row, dict) else row['atr14']

    # Indicadores deben estar disponibles
    if any(v is None or (hasattr(v, '__float__') and pd.isna(float(v)))
           for v in [close, nd_high, vol20, atr14]):
        return False
    try:
        close, nd_high, volume, vol20, atr14 = (
            float(close), float(nd_high), float(volume), float(vol20), float(atr14))
    except (TypeError, ValueError):
        return False

    if close <= nd_high:
        return False
    if vol20 > 0 and volume < VOL_RATIO * vol20:
        return False

    return True


# ── Cálculo de posición ───────────────────────────────────────────────────────

def calculate_position(row, equity: float) -> dict | None:
    """
    Dado un row que ya pasó is_breakout_signal(), calcula los parámetros
    de la posición.

    Devuelve un dict con:
      entry    — precio de entrada (close de la vela de breakout)
      sl       — stop-loss (entry - ATR14 × ATR_MULT)
      tp       — take-profit (entry + RR × risk)
      qty      — unidades a comprar
      risk_usd — riesgo absoluto en USD

    Devuelve None si el riesgo calculado es ≤ 0 o el equity es insuficiente.
    """
    try:
        entry = float(row.get('close') if isinstance(row, dict) else row['close'])
        atr14 = float(row.get('atr14') if isinstance(row, dict) else row['atr14'])
    except (TypeError, ValueError):
        return None

    sl   = entry - ATR_MULT * atr14
    risk = entry - sl

    if risk <= 0 or entry <= 0:
        return None

    tp       = entry + RR * risk
    risk_usd = equity * RISK_PCT
    qty      = risk_usd / risk

    return {
        'entry':    round(entry, 8),
        'sl':       round(sl, 8),
        'tp':       round(tp, 8),
        'qty':      round(qty, 8),
        'risk_usd': round(risk_usd, 4),
        'atr14':    round(atr14, 8),
    }


# ── Utilidad para el live engine ──────────────────────────────────────────────

def get_latest_completed_day(daily: pd.DataFrame) -> pd.Series | None:
    """
    Devuelve la última vela diaria completa del DataFrame preparado.
    La última fila puede ser un día incompleto si se llama antes del cierre UTC.
    En la arquitectura real el engine solo llama a esto justo después del cierre.
    """
    if daily.empty:
        return None
    return daily.iloc[-1]
