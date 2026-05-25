# Sesión 2026-05-24 — Task010-B: Filtro 4h BTC (DESCARTADO)

## Rama
`feat/4h-btc-filter` — eliminada el 2026-05-24.

## Qué se hizo
Se implementó y backtestó un filtro de macro-dirección 4h para BTC longs:
- `prepare_4h()`: resamplea 1h → 4h, calcula EMA20 + slope
- `align_4h_to_15m()`: adjunta el slope 4h a cada barra 15m
- `is_4h_aligned()`: gate — BTC long solo si EMA20 4h slope > 0%

El filtro aplica **solo a BTC longs**. ETH sin cambios.

## Resultado del backtest (730d, fees incluidas)

| Métrica       | BASE (actual) | Task010-B (4h gate) |
|---------------|---------------|----------------------|
| Trades BTC    | 71            | 49 (-31%)            |
| PF BTC        | 1.787         | **2.343** (+31%)     |
| WR BTC        | 54.9%         | **61.2%**            |
| MaxDD BTC     | 6.69%         | **4.97%**            |
| PF ETH        | 1.568         | 1.568 (sin cambio)   |

Walk-forward 4×182d: **todas las ventanas pasan** (PF > 1.0).

El filtro mejora sustancialmente el PF eliminando entradas en mercados bajistas en 4h.

## Por qué se descartó

**No por los números** — el backtest es sólido.

**Por practicidad de validación**: para confirmar el edge en producción se necesitan ~30-40 trades BTC, que con la frecuencia actual (~71 trades/730d → ~1 trade/10 días) implica ~5-6 meses de paper trading. No es razonable mantener una rama separada ese tiempo.

**Alternativa considerada**: deploy en modo paper paralelo al live. Descartada porque el sistema actual ya está funcionando correctamente y la adición de complejidad no justifica el beneficio marginal a corto plazo.

## Decisión
REVERT temporal — no se merge a master. Los números quedan documentados aquí para recuperar en el futuro si se decide retomar.

## Commits que contenía la rama
- `49987a3` — Task010-B: 4h EMA20 macro gate (backtest)
- `7d8fae3` — WebSocket order monitor (ya en master vía cherry-pick `a309b63`)
