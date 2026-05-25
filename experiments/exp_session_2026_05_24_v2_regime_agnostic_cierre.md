# Cierre rama v2-regime-agnostic — 2026-05-24

## Rama eliminada
`v2-regime-agnostic` — eliminada el 2026-05-24.

## Objetivo original
Construir un sistema regime-agnostic: PF > 1.2 con fees en cualquier ventana de 90 días,
usando una arquitectura de dos estrategias con clasificador ADX:

```
ADX(14) en 1h > 25  →  Strategy A: Pullback Continuation
ADX(14) en 1h < 20  →  Strategy B: Mean Reversion (nueva)
ADX entre 20-25     →  Sin trades
```

## Estado de cada experimento al cierre

| Exp    | Estado     | Resultado |
|--------|------------|-----------|
| EXP018 | ❌ FALLÓ   | ADX(14) en 1h **no separa regímenes** — filtra los mejores trades, no los peores. El clasificador ADX no funciona como gate para pullback continuation. |
| EXP019 | ✅ APROBADO | SLOPE_CAP (skip cuando EMA50 slope > 0.20%) mejora PF. **Ya mergeado a master.** |
| EXP020 | ✅ OBSOLETO | Arquitectura dos-estrategias descartada. La diversificación BTC+ETH ya cubre todos los regímenes sin routing adicional. |
| EXP021 | ✅ APROBADO | Walk-forward 4×182d: sistema combinado BTC+ETH pasa todas las ventanas. |
| Fase 5 | ✅ ABSORBIDO | Los cambios aprobados (EXP019/SLOPE_CAP) ya están en master. El resto se descartó. |

## Por qué se descarta la rama completa

1. **EXP018 falló**: sin clasificador de régimen funcional, toda la arquitectura V2 pierde su
   fundamento. No hay forma de routear entre Strategy A y Strategy B sin un gate confiable.

2. **Lo que funcionó ya está en master**: SLOPE_CAP (EXP019) fue el único cambio aprobado
   y se mergeó directamente a master sin necesitar la arquitectura V2.

3. **La hipótesis central no se validó**: BTC+ETH corriendo en paralelo con los filtros
   actuales ya produce un sistema suficientemente robusto entre regímenes. No se necesita
   una segunda estrategia de mean reversion.

4. **Deuda técnica**: la rama tiene commits desactualizados respecto a master (order monitor,
   fixes de live engine, etc.) que harían el merge costoso sin beneficio real.

## Qué queda pendiente (no en ninguna rama)

Si en el futuro se quiere retomar la idea de regime-agnostic, los puntos de partida son:
- Buscar un clasificador mejor que ADX para separar trending vs choppy en crypto
  (candidatos: ATR_ratio, Hurst exponent, fractal dimension)
- La estrategia de mean reversion (BB + RSI) nunca se llegó a backtest en profundidad
- EXP018 dejó claro que el ADX en crypto es leading indicator de lo contrario: ADX alto
  suele marcar el final del trend, no el inicio

## Commits relevantes de la rama
- `4bed521` — v2: exp020 (sistema combinado, luego descartado)
- `a248e51` — v2 roadmap inicial y CLAUDE.md actualizado
