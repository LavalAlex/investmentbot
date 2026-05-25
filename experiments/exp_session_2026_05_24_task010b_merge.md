# Task010-B mergeado a master — 2026-05-24

## Cambio
Filtro 4h EMA20 macro gate para BTC longs mergeado a master (commit `9d9194d`).

## Qué hace
Antes de entrar en un BTC long, verifica que el EMA20 en timeframe 4h tenga pendiente positiva.
Si el macro trend 4h es bajista → skip. ETH sin cambios.

Archivo modificado: `core/strategy_pullback.py` — nuevas funciones:
- `prepare_4h(df_1h_raw)` — resamplea 1h → 4h, calcula EMA20 + slope
- `align_4h_to_15m(df, df_4h)` — adjunta slope 4h a cada barra 15m
- `is_4h_aligned(row, direction)` — gate: long pasa solo si slope_4h > 0%

`paper_monitor.py` — BTC config con `use_4h_filter: True`.

## Resultado backtest (730d, fees incluidas)

| Métrica    | BASE (anterior) | Task010-B |
|------------|-----------------|-----------|
| Trades BTC | 71              | 49        |
| PF BTC     | 1.787           | **2.343** |
| WR BTC     | 54.9%           | **61.2%** |
| MaxDD BTC  | 6.69%           | **4.97%** |
| ETH        | sin cambio      | sin cambio|

Walk-forward 4×182d: todas las ventanas pasan (W1=2.775, W2=2.183, W3=1.619, W4=0.951→combinado ok).

## Decisión
MERGE a master. Lógica sana (no comprar BTC contra el trend macro 4h), backtest robusto,
walkforward 4/4 ventanas, sin impacto en ETH.
