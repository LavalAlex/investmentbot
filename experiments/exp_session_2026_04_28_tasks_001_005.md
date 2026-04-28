# Experiment Session — 2026-04-28 (parte 2)
## Tasks 001–005: evaluación de mejoras al sistema V2

---

## Contexto de entrada

Sistema base al iniciar esta sesión:
- **EXP019 SLOPE_CAP activo** en `paper_monitor.py` (deploy_004 pendiente de PR)
- **EXP021 aprobado** bajo criterio combinado BTC+ETH (4 ventanas ✅)
- Pregunta central: ¿se puede mejorar el PF de forma sostenible sin cambiar la lógica core?

Creado folder `tasks/` con 5 tasks priorizadas. Corridas en secuencia en esta sesión.

---

## Resultados por task

### Task 001 — Trailing Stop ❌ REVERT

**Hipótesis:** Reemplazar TP fijo 2:1 con trailing stop aumenta el retorno dejando correr los winners.

**Resultado:**

| Variante | BTC PF | ETH PF |
|----------|--------|--------|
| BASE | 1.344 | 1.318 |
| TRAIL-A (1.5×ATR desde +1R) | 0.835 | 0.674 |
| TRAIL-B (2.0×ATR desde +1R) | 1.026 | 0.641 |
| TRAIL-C (1.5×ATR desde BE) | 0.414 | 0.352 |
| HYBRID (TP 2:1 o trail 3×ATR) | 1.048 | 0.890 |

Walk-forward: 0/4 ventanas ✅ para todas las variantes de trailing.

**Por qué falló:** El `avg_exit_mult` del BASE es 0.46× en BTC y 0.36× en ETH.
El precio promedio de salida está a menos de la mitad del camino al TP.
El trailing se activa, el precio retrocede levemente, cierra con ganancia mínima.
Solo el 2–5% de los trades superó el 2:1 original. El pullback continuation tiene
trades cortos y precisos — no tendencias extendidas donde el trailing puede trabajar.

**Conclusión:** TP fijo 2:1 es el mecanismo correcto para esta estrategia.

---

### Task 002 — Dynamic Position Sizing ✅ KEEP (DYN-B)

**Hipótesis:** Escalar el tamaño inversamente al ATR ratio mejora el Sharpe sin cambiar el edge.

**Resultado:**

| Variante | BTC PF | ETH PF | BTC MaxDD | ETH MaxDD | BTC Sharpe | ETH Sharpe |
|----------|--------|--------|-----------|-----------|------------|------------|
| BASE | 1.344 | 1.318 | 7.01% | 13.38% | 1.23 | 1.11 |
| DYN-A (0.5–1.5×) | 1.400 | 1.389 | 6.97% | 13.53% | 1.33 | 1.24 |
| **DYN-B (0.6–1.2×)** | **1.411** | **1.378** | **6.54%** | **13.52%** | **1.40** | **1.22** |
| DYN-C (0.5–1.0×) | 1.382 | 1.358 | 6.30% | 12.65% | 1.35 | 1.21 |

Walk-forward DYN-B: 4/4 ventanas ✅.

**Variante seleccionada: DYN-B** (scale 0.6–1.2×). Mejor Sharpe en BTC (1.23→1.40),
mejor Calmar en BTC (3.71→4.88). El rango moderado evita oversizing en mercados tranquilos.

---

### Task 003 — Volume Filter 🔄 ITERAR (→ Task 007)

**Hipótesis:** Volumen ≥ 1.2× promedio en vela de trigger mejora win rate.

**Resultado:**

| Variante | BTC PF | ETH PF | Walk-fwd W3 |
|----------|--------|--------|-------------|
| BASE | 1.344 | 1.318 | 1.034 ✅ |
| VOL-A (1.0× mean20) | 1.394 | 1.217 | 0.947 ❌ |
| VOL-B (1.2× mean20) | 1.439 | 1.356 | 0.925 ❌ |
| VOL-C (1.5× mean20) | 1.185 | 1.512 | 0.682 ❌ |
| **VOL-D (1.0× mean50)** | 1.369 | **1.556** | 0.881 ❌ |

Paradoja: el volumen mejora ETH sobre 730d pero destruye W3 (Recovery 2025) en walk-forward.
Hipótesis: la mejora proviene principalmente de ETH shorts — aplicar el filtro solo ahí
podría conservar la mejora sin dañar W3.

**Iteración → Task 007:** volume filter solo en ETH shorts.

---

### Task 004 — Time-of-Day Filter ✅ KEEP (TIME-B)

**Hipótesis:** La sesión asiática (00–07 UTC) tiene peor calidad de señal por baja liquidez.

**Diagnóstico BTC por sesión:**

| Sesión | Trades | WR% | PF | Ret% |
|--------|--------|-----|-----|------|
| ASIA 00–07 | 22 | 36% | **0.810** | -3.79% |
| EUROPE 07–13 | 16 | 56% | 1.786 | +8.02% |
| OVERLAP 13–17 | 38 | **58%** | **2.005** | +22.65% |
| US_LATE 17–24 | 27 | 41% | 0.961 | -0.89% |

ETH: sorprendentemente, ASIA tiene PF 1.462 para ETH (BTC longs son los que sufren en Asia).

**Resultado TIME-B (07–21 UTC):**

| | BTC BASE | BTC TIME-B | ETH BASE | ETH TIME-B |
|--|---------|-----------|---------|-----------|
| PF | 1.344 | **1.729** | 1.318 | **1.422** |
| WR% | 48.5% | **54.9%** | 45.2% | 46.6% |
| MaxDD | 7.01% | **6.82%** | 13.38% | **7.73%** |
| Trades | 103 | 71 | 115 | 73 |

Walk-forward TIME-B: 4/4 ventanas ✅. W3 Recovery 2025 mejora de 1.034 → 1.361.

**Conclusión:** TIME-B es la mejora de mayor impacto de las 5 tasks. Los trades de BTC
en sesión asiática (22 trades, WR 36%, PF 0.810) son el subconjunto más dañino del sistema.
Eliminarlos sube el WR de 48.5% a 54.9% y el PF de 1.344 a 1.729.

---

### Task 005 — Tercer Activo SOL ❌ REVERT

**Hipótesis:** SOL/USDT con los mismos parámetros tiene PF > 1.2 y aporta diversificación.

**Resultado:**

| Variante | PF | WR% | MaxDD |
|----------|-----|-----|-------|
| SOL SL≥0.40% | 0.626 | 27.2% | 32.4% |
| SOL SL≥0.50% | 0.633 | 27.1% | 30.5% |
| SOL SL≥0.60% | **0.675** | 28.2% | 26.2% |
| SOL SL≥0.70% | 0.613 | 26.0% | 26.4% |

Régimen de SOL: solo Bull 2024 tiene PF > 1.0. ATH, Recovery y Bear todos negativos.
Añadir SOL reduce el PF combinado en todas las ventanas de walk-forward.

**Por qué falla:** SOL tiene movimientos más explosivos e irregulares. Los pullbacks
a EMA20 son menos predecibles — el precio "overshoot" la EMA frecuentemente.
La estrategia de pullback continuation necesita tendencias ordenadas.

---

## Resumen de decisiones

| Task | Estado | Acción |
|------|--------|--------|
| 001 Trailing Stop | ❌ REVERT | TP fijo 2:1 es correcto para esta estrategia |
| 002 DYN-B Sizing | ✅ KEEP | Integrar en próximo backtest combinado |
| 003 Volume Filter | 🔄 ITERAR | → Task 007: solo ETH shorts |
| 004 TIME-B Filter | ✅ KEEP | Integrar en próximo backtest combinado |
| 005 SOL | ❌ REVERT | No hay edge con pullback en SOL |

## Sistema acumulado propuesto (base para próxima sesión)

```
EXP019 SLOPE_CAP (0.20%)     → base
+ DYN-B (scale 0.6–1.2×)    → Task 002 ✅
+ TIME-B (07–21 UTC)         → Task 004 ✅
```

## Tasks generadas para próxima sesión

- **Task 006:** Backtest combinado DYN-B + TIME-B → verificar efecto acumulativo
- **Task 007:** Volume filter solo en ETH shorts → iteración Task 003

## Archivos creados en esta sesión

```
tasks/
  README.md
  task_001_trailing_stop.md     ❌ REVERT
  task_002_dynamic_sizing.md    ✅ KEEP
  task_003_volume_filter.md     🔄 ITERAR
  task_004_time_filter.md       ✅ KEEP
  task_005_third_asset.md       ❌ REVERT
  task_006_combined_dynb_timeb.md   ⬜ PRÓXIMA SESIÓN
  task_007_volume_eth_shorts.md     ⬜ PRÓXIMA SESIÓN

backtest/
  backtest_task001.py   backtest_task002.py
  backtest_task003.py   backtest_task004.py
  backtest_task005.py

data/
  backtest_task001.json   backtest_task002.json
  backtest_task003.json   backtest_task004.json
  backtest_task005.json
  SOLUSDT_15m_last_730d.csv
  SOLUSDT_1h_last_740d.csv
```
