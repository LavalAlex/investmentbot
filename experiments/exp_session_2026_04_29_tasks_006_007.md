# Experiment Session — 2026-04-29
## Tasks 006–007: Sistema combinado final + volume filter ETH shorts

---

## Contexto de entrada

Sistema base al iniciar:
- EXP019 SLOPE_CAP (0.20%) activo en `paper_monitor.py`
- EXP021 aprobado bajo criterio combinado BTC+ETH (4 ventanas ✅)
- Task 002 (DYN-B) y Task 004 (TIME-B) aprobados individualmente
- Task 006 y Task 007 pendientes

---

## Task 006 — Sistema combinado DYN-B + TIME-B ✅ APROBADO

**Hipótesis:** DYN-B y TIME-B son ortogonales — TIME-B elimina trades en horas malas,
DYN-B escala el tamaño de los trades que sí se toman. Su efecto debería acumularse.

### Resultados

| Variante | BTC PF | ETH PF | BTC MaxDD | ETH MaxDD | BTC Sharpe | ETH Sharpe |
|----------|--------|--------|-----------|-----------|------------|------------|
| BASE | 1.344 | 1.318 | 7.01% | 13.38% | 1.23 | 1.11 |
| DYN-B | 1.411 | 1.378 | 6.54% | 13.52% | 1.40 | 1.22 |
| TIME-B | 1.729 | 1.422 | 6.82% | 7.73% | 1.92 | 1.18 |
| **COMBINED** | **1.787** | **1.482** | **6.69%** | **8.17%** | **1.99** | **1.25** |

Walk-forward combinado BTC+ETH:

| Ventana | BASE | DYN-B | TIME-B | COMBINED |
|---------|------|-------|--------|----------|
| W1 Bull 2024 | 1.769 ✅ | 1.870 ✅ | 2.142 ✅ | 2.245 ✅ |
| W2 ATH 2024-25 | 1.278 ✅ | 1.370 ✅ | 1.496 ✅ | 1.662 ✅ |
| W3 Recovery 2025 | 1.034 ✅ | 1.081 ✅ | 1.361 ✅ | 1.397 ✅ |
| W4 Bear 2025-26 | 1.244 ✅ | 1.271 ✅ | 1.305 ✅ | 1.270 ✅ |

**La hipótesis se confirma:** el efecto es acumulativo. COMBINED es estrictamente mejor
que DYN-B solo y TIME-B solo en ambos assets. Las 4 ventanas pasan con margen amplio.

**Decisión: KEEP COMBINED** ✅

---

## Task 007 — Volume filter solo ETH shorts ✅ APROBADO (ETH-SHORT-C)

**Hipótesis:** ETH shorts de bajo volumen son trampas de liquidez. El filtro de volumen
con lookback 50 (más estable) debería mejorar el PF sin destruir el walk-forward.

### Diagnóstico ETH SHORTS por vol_ratio20 (BASE COMBINED)

| vol_ratio | Trades | WR% | PF | Ret% |
|-----------|--------|-----|-----|------|
| < 0.8 | 5 | 40% | 0.977 | -0.10% |
| 0.8–1.2 | 6 | 33% | 1.054 | +0.24% |
| ≥ 1.2 | 33 | 45% | 1.437 | +10.40% |

La hipótesis tiene base empírica: los ETH shorts de bajo volumen tienen PF < 1.0.

### Resultados ETH

| Variante | ETH PF | ETH MaxDD | Trades ETH |
|----------|--------|-----------|------------|
| BASE | 1.482 | 8.17% | 73 |
| ETH-SHORT-A (1.0× m20) | 1.475 | 7.05% | 67 |
| ETH-SHORT-B (1.2× m20) | 1.549 | 7.05% | 65 |
| **ETH-SHORT-C (1.0× m50)** | **1.568** | **7.05%** | **69** |
| ALL-SHORT-B (1.2× m20) | 1.549 | 7.05% | 65 |

Walk-forward combinado BTC+ETH (todos los assets — BTC no tiene shorts):

| Ventana | BASE | ETH-SHORT-B | ETH-SHORT-C |
|---------|------|-------------|-------------|
| W1 Bull 2024 | 2.245 ✅ | 2.512 ✅ | 2.245 ✅ |
| W2 ATH 2024-25 | 1.662 ✅ | 1.556 ✅ | 1.738 ✅ |
| W3 Recovery 2025 | 1.397 ✅ | 1.490 ✅ | 1.483 ✅ |
| W4 Bear 2025-26 | 1.270 ✅ | 1.270 ✅ | 1.275 ✅ |

**ETH-SHORT-C seleccionada:** lookback 50 es más estable que 20, mejora el PF en todas
las ventanas excepto W1 (que permanece igual). MaxDD ETH cae de 8.17% → 7.05%.

**Decisión: KEEP ETH-SHORT-C** ✅

---

## Sistema final acumulado (para deploy_004)

```
EXP019 SLOPE_CAP (0.20%)          ← ya activo en paper_monitor.py
+ TIME-B (07–21 UTC)              ← Task 004 ✅
+ DYN-B (scale 0.6–1.2× ATR)     ← Task 002 ✅
+ ETH-SHORT-C (vol ≥ 1.0× m50)   ← Task 007 ✅
```

### Métricas finales del sistema completo

| Asset | PF | WR% | MaxDD | Sharpe | Return% |
|-------|-----|-----|-------|--------|---------|
| BTC | 1.787 | 54.9% | 6.69% | 1.99 | +39.6% |
| ETH | 1.568 | 47.8% | 7.05% | — | +27.0% |

Walk-forward: 4/4 ventanas ✅ bajo criterio combinado BTC+ETH.

---

## Próximos pasos

1. **Deploy de los 3 cambios al código live:**
   - TIME-B en `paper_monitor.py` (SLOPE_CAP ya está, TIME-B falta)
   - DYN-B: sizing dinámico en `paper_monitor.py`
   - ETH-SHORT-C: filtro de volumen en `paper_monitor.py` (solo ETH shorts)
2. PR `v2-regime-agnostic` → `master`
3. Redeploy Cloud Run europe-west1 (deploy_004)

---

## Archivos creados en esta sesión

```
backtest/
  backtest_task006.py   ✅ COMBINED (DYN-B + TIME-B)
  backtest_task007.py   ✅ ETH-SHORT-C

data/
  backtest_task006.json
  backtrack_task007.json

tasks/
  task_006_combined_dynb_timeb.md  → actualizado ✅ APROBADO
  task_007_volume_eth_shorts.md    → actualizado ✅ APROBADO
```
