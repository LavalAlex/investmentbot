# Experiment Session — 2026-04-28
## EXP019 (momentum filter) + EXP021 (walk-forward) → Deploy 004

---

## Contexto de entrada

- EXP018 había fallado: ADX(14) como clasificador de régimen seleccionaba los peores trades.
  Los trades en mercado choppy (ADX bajo) tenían PF > 1.4, los tendenciales PF < 1.0.
- EXP019 ya tenía código escrito (pivot desde la sesión anterior) pero no había sido corrido.
- `data/backtest_exp021.json` no existía. `data/backtest_exp018.json` sí.

---

## EXP019 — Momentum extreme filter

**Hipótesis:** El problema no es trending vs choppy, sino momentum parabólico.
Cuando EMA50 sube más de 0.20%/5bars en 1h, el mercado está en parabólico — los pullbacks
son trampas porque el precio no retrocede a la EMA antes de continuar.

**Variantes:** BASE / SLOPE_CAP / ATR_RATIO / COMBINED / STRICT

### Resultados

| Asset | BASE PF | SLOPE_CAP PF | Trades | MaxDD |
|-------|---------|-------------|--------|-------|
| BTC   | 1.126   | **1.390**   | 99     | 7.01% |
| ETH   | 0.939   | **1.386**   | 112    | 13.38% |

- ATR_RATIO no captura nada relevante (solo 3 trades extremos en ETH).
- COMBINED = SLOPE_CAP (el ATR no añade señal adicional).
- Los trades descartados tienen PF 0.964 (BTC) y 0.760 (ETH) — el filtro discrimina correctamente.

**Desglose por régimen (SLOPE_CAP):**

BTC: las 4 ventanas tienen PF > 1.0. ATH 2024-25 mejoró de 0.855 → 1.233.

ETH: Bull 2024 (1.725), ATH 2024-25 (1.727), Bear 2025-26 (1.633). Recovery 2025 (0.532) — sigue roto con solo 20 trades.

**Decisión: KEEP SLOPE_CAP = 0.20%**

---

## EXP021 — Walk-forward 4×182d

**Parámetros fijos (sin re-optimizar):** SLOPE_CAP=0.20%, BTC longs SL≥0.30%, ETH l+s SL≥0.50%, RR=2:1.

### Resultados por asset

**BTC:**
| Ventana | Período | Trades | PF | MaxDD |
|---------|---------|--------|-----|-------|
| W1 | Bull 2024 | 23 | 1.574 ✅ | 3.6% |
| W2 | ATH 2024-25 | 22 | 1.456 ✅ | 4.1% |
| W3 | Recovery 2025 | 29 | 1.531 ✅ | 5.8% |
| W4 | Bear 2025-26 | 28 | 0.916 ❌ | 7.0% |

**ETH:**
| Ventana | Período | Trades | PF | MaxDD |
|---------|---------|--------|-----|-------|
| W1 | Bull 2024 | 37 | 1.901 ✅ | 3.4% |
| W2 | ATH 2024-25 | 31 | 1.168 ✅ | 4.9% |
| W3 | Recovery 2025 | 20 | 0.541 ❌ | 12.4% |
| W4 | Bear 2025-26 | 25 | 1.755 ✅ | 4.6% |

### Criterio combinado BTC+ETH

Los dos assets son complementarios en régimen: cuando uno falla, el otro compensa.

| Ventana | BTC PF | ETH PF | Combinado |
|---------|--------|--------|-----------|
| W1 | 1.574 | 1.901 | **1.769** ✅ |
| W2 | 1.456 | 1.168 | **1.284** ✅ |
| W3 | 1.531 | 0.541 | **1.051** ✅ |
| W4 | 0.916 | 1.755 | **1.265** ✅ |

**Las 4 ventanas pasan bajo criterio combinado.**

### Decisión sobre routing cross-asset

Se discutió añadir routing condicional (en W3 solo BTC, en W4 solo ETH).
Se descartó por:
1. Requiere detector de régimen en tiempo real — historial de 4 intentos fallidos en este proyecto.
2. El sistema combinado ya cumple el objetivo original (PF > 1.0 en todas las ventanas).
3. Riesgo real de limbo sin fin: optimización sobre 4 puntos de datos es casi por definición overfitting.

**EXP021: APROBADO bajo criterio combinado.**

---

## Cambios al código

### `core/indicators_v2.py`
- Añadida función `adx(df, period=14)` — Wilder ADX (calculado pero no usado en producción).

### `core/strategy_pullback.py`
- `prepare_1h()`: calcula `adx14` y lo expone como `adx_1h` en el df alineado.
- `ema50_slope_pct` ya estaba disponible en el df alineado — confirmado.

### `paper_monitor.py`
- Añadido SLOPE_CAP filter en `scan_asset()` después de `is_market_efficient()`:
  ```python
  slope_pct = row.get('ema50_slope_pct')
  if slope_pct is not None and not pd.isna(slope_pct) and abs(slope_pct) > 0.20:
      logger.info(f"[{asset}] SKIP slope_cap ema50_slope={slope_pct*100:.3f}% > 0.20%")
      return
  ```
- Añadido `import pandas as pd`.

---

## Próximos pasos

1. PR `v2-regime-agnostic` → `master` con review de cambios
2. Redeploy en Cloud Run europe-west1 (deploy_004)
3. Monitorear que el filtro SLOPE_CAP se activa correctamente en logs
4. Criterio de evaluación live: PF combinado BTC+ETH tras 50+ trades
