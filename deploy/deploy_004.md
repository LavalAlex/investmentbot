# Deploy 004 — V2 SLOPE_CAP Filter

**Fecha:** 2026-04-28  
**Rama:** `v2-regime-agnostic` → `master`  
**Experimentos que habilitan este deploy:** EXP019 ✅ + EXP021 ✅

---

## Qué cambia

Un único filtro de entrada añadido al sistema live: **SLOPE_CAP**.

Cuando EMA50 en 1h sube o baja más de 0.20%/5 barras, el mercado está en momentum
parabólico. Los pullbacks en ese contexto son trampas — el precio no regresa a la EMA
antes de continuar. El filtro evita entrar en esos momentos.

**Sin cambios a:** SL/TP, gestión de riesgo, circuit breaker, break-even stop, cooldown,
parámetros de activos, lógica de salida, infraestructura.

---

## Archivos modificados

### `core/indicators_v2.py`
- Añadida función `adx(df, period=14)` — Wilder ADX.
  (Calculado en `prepare_1h()` pero no usado como filtro de entrada en producción.)

### `core/strategy_pullback.py`
- `prepare_1h()`: calcula `adx14` y lo expone como `adx_1h` en el df alineado.
  (Infraestructura para futuros experimentos; no afecta la señal de trading.)

### `paper_monitor.py`  ← cambio operativo
- Añadido `import pandas as pd`.
- Añadido SLOPE_CAP gate en `scan_asset()`, después de `is_market_efficient()`:

```python
# EXP019 — SLOPE_CAP: skip when EMA50 is in parabolic momentum (>0.20%/5bars)
slope_pct = row.get('ema50_slope_pct')
if slope_pct is not None and not pd.isna(slope_pct) and abs(slope_pct) > 0.20:
    logger.info(
        f"[{asset}] SKIP slope_cap ema50_slope={slope_pct*100:.3f}% > 0.20%"
    )
    return
```

---

## Resultados de validación

### EXP019 (730d completos, con fees)

| Asset | BASE PF | SLOPE_CAP PF | Trades | MaxDD |
|-------|---------|-------------|--------|-------|
| BTC   | 1.126   | 1.390       | 99     | 7.01% |
| ETH   | 0.939   | 1.386       | 112    | 13.38% |

### EXP021 (walk-forward 4×182d, criterio combinado)

| Ventana | BTC PF | ETH PF | Combinado |
|---------|--------|--------|-----------|
| W1 Bull 2024 | 1.574 | 1.901 | **1.769** ✅ |
| W2 ATH 2024-25 | 1.456 | 1.168 | **1.284** ✅ |
| W3 Recovery 2025 | 1.531 | 0.541 | **1.051** ✅ |
| W4 Bear 2025-26 | 0.916 | 1.755 | **1.265** ✅ |

---

## Pasos del deploy

1. `git checkout master && git merge v2-regime-agnostic`
2. Verificar que los tests de importación pasan: `python -c "from paper_monitor import *"`
3. Redeploy en Cloud Run europe-west1 (mismo proceso que deploy_003)
4. Verificar en logs que el filtro SLOPE_CAP aparece: buscar `SKIP slope_cap` en primeras horas

---

## Criterio de evaluación post-deploy

- Tras 50+ trades en live: PF combinado BTC+ETH ≥ 1.0
- El log debe mostrar `SKIP slope_cap` ocasionalmente (confirma que el filtro se activa)
- Si nunca aparece `SKIP slope_cap` en 2 semanas → revisar que `ema50_slope_pct` está llegando al row

---

## Rollback

Revertir `paper_monitor.py` al commit `154599f` y redeploy.
Los cambios en `indicators_v2.py` y `strategy_pullback.py` no afectan el comportamiento
si `paper_monitor.py` no usa `adx_1h` ni el nuevo filtro.
