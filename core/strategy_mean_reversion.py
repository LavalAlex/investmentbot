"""
Strategy B — Mean Reversion (EXP_C)

Opera cuando el mercado está en régimen ranging (ADX_1h < 20).
Señal: precio toca banda de Bollinger extrema + RSI en zona opuesta + vela de reversión en 15m.
TP: banda central (BB mid = SMA20). SL: swing reciente del lado contrario.

Indicadores en 1h:
  - BB(20, 2σ) sobre close_1h
  - RSI(14) sobre close_1h
  - ADX(14) — ya computado en prepare_1h()

Alineados al 15m mediante merge_asof (igual que los indicadores 1h actuales).
"""

import pandas as pd
from .indicators_v2 import bollinger_bands, rsi, adx, ema

# ── Parámetros ────────────────────────────────────────────────────────────────

BB_PERIOD   = 20
BB_STD      = 2.0
RSI_PERIOD  = 14
RSI_OS      = 35     # oversold threshold para longs
RSI_OB      = 65     # overbought threshold para shorts
ADX_RANGING = 20     # por debajo de esto = régimen ranging

MIN_BODY_RATIO = 0.50   # vela de reversión: body ≥ 50% del range
MIN_BB_TOUCH   = 0.002  # precio debe estar a ≤0.2% de la banda para calificar


# ── Preparación 1h con indicadores MR ────────────────────────────────────────

def prepare_1h_mr(df_1h: pd.DataFrame) -> pd.DataFrame:
    """
    Añade BB y RSI al df de 1h ya preparado por prepare_1h().
    Recibe el output de prepare_1h() (que ya tiene adx_1h, ema20, etc.).
    """
    out = df_1h.copy()
    bb_upper, bb_mid, bb_lower = bollinger_bands(out['close'], BB_PERIOD, BB_STD)
    out['bb_upper'] = bb_upper
    out['bb_mid']   = bb_mid
    out['bb_lower'] = bb_lower
    out['rsi14']    = rsi(out['close'], RSI_PERIOD)
    return out


def align_1h_mr_to_15m(df_aligned: pd.DataFrame, df_1h_mr: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega columnas MR del 1h al df ya alineado (output de align_1h_to_15m).
    Usa merge_asof sobre available_at para no introducir lookahead.
    """
    cols_1h = df_1h_mr[['available_at', 'bb_upper', 'bb_mid', 'bb_lower', 'rsi14']].copy()
    cols_1h = cols_1h.dropna(subset=['bb_upper', 'rsi14'])

    df_aligned = df_aligned.copy()
    df_aligned['open_time'] = pd.to_datetime(df_aligned['open_time'])
    cols_1h['available_at'] = pd.to_datetime(cols_1h['available_at'])

    merged = pd.merge_asof(
        df_aligned.sort_values('open_time'),
        cols_1h.sort_values('available_at'),
        left_on='open_time',
        right_on='available_at',
        direction='backward',
    )
    return merged


# ── Filtros de señal ──────────────────────────────────────────────────────────

def is_ranging_regime(row) -> bool:
    """ADX_1h < 20 — mercado sin tendencia clara."""
    adx_val = row.get('adx_1h')
    if adx_val is None or pd.isna(adx_val):
        return False
    return adx_val < ADX_RANGING


def is_mr_long_signal(row) -> bool:
    """
    Condición de entrada long (reversión desde soporte):
    - Precio toca BB inferior (close ≤ bb_lower × (1 + MIN_BB_TOUCH))
    - RSI < RSI_OS (oversold)
    """
    close     = row.get('close')
    bb_lower  = row.get('bb_lower')
    rsi_val   = row.get('rsi14')
    if any(v is None or pd.isna(v) for v in [close, bb_lower, rsi_val]):
        return False
    touching_lower = close <= bb_lower * (1 + MIN_BB_TOUCH)
    return touching_lower and rsi_val < RSI_OS


def is_mr_short_signal(row) -> bool:
    """
    Condición de entrada short (reversión desde resistencia):
    - Precio toca BB superior (close ≥ bb_upper × (1 - MIN_BB_TOUCH))
    - RSI > RSI_OB (overbought)
    """
    close     = row.get('close')
    bb_upper  = row.get('bb_upper')
    rsi_val   = row.get('rsi14')
    if any(v is None or pd.isna(v) for v in [close, bb_upper, rsi_val]):
        return False
    touching_upper = close >= bb_upper * (1 - MIN_BB_TOUCH)
    return touching_upper and rsi_val > RSI_OB


def is_mr_reversal_candle(row, direction: str) -> bool:
    """
    Vela de reversión en 15m:
    - Body ≥ 50% del range
    - Dirección correcta: long = close > open, short = close < open
    """
    o, c, h, l = row.get('open'), row.get('close'), row.get('high'), row.get('low')
    if any(v is None or pd.isna(v) for v in [o, c, h, l]):
        return False
    candle_range = h - l
    if candle_range <= 0:
        return False
    body = abs(c - o)
    if body / candle_range < MIN_BODY_RATIO:
        return False
    if direction == 'long':
        return c > o
    else:
        return c < o


def calculate_mr_sl_tp(row, direction: str):
    """
    SL: swing del lado contrario de la vela (high para short, low para long).
    TP: BB mid (media de la banda), que es la zona de reversión esperada.
    Returns (sl, tp) o (None, None) si el setup es inválido.
    """
    entry    = row.get('close')
    bb_mid   = row.get('bb_mid')
    candle_l = row.get('low')
    candle_h = row.get('high')

    if any(v is None or pd.isna(v) for v in [entry, bb_mid, candle_l, candle_h]):
        return None, None

    if direction == 'long':
        sl = candle_l
        tp = bb_mid
        if sl >= entry or tp <= entry:
            return None, None
    else:
        sl = candle_h
        tp = bb_mid
        if sl <= entry or tp >= entry:
            return None, None

    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0 or reward <= 0:
        return None, None

    # Mínimo RR 1.2:1 para que el setup valga la pena
    if reward / risk < 1.2:
        return None, None

    return sl, tp


def get_mr_direction(row) -> str | None:
    """Retorna 'long', 'short' o None si no hay señal MR válida."""
    if is_mr_long_signal(row) and is_mr_reversal_candle(row, 'long'):
        return 'long'
    if is_mr_short_signal(row) and is_mr_reversal_candle(row, 'short'):
        return 'short'
    return None
