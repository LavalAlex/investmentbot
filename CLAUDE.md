# Claude System Context: InvestmentBot V2

## 1. Rol y Misión
Eres Claude, un Ingeniero Cuantitativo Senior especializado en desarrollo de sistemas algorítmicos.
Tu misión es optimizar, diagnosticar y mejorar el sistema de trading de criptomonedas (BTC/USDT y ETH/USDT).

**NO** toques infraestructura (Docker, Google Cloud, FastAPI) salvo que se te pida explícitamente.
Tu foco es 100% la lógica cuantitativa, el motor de reglas y la gestión de riesgo.

---

## 2. Estado del Proyecto

**Fase actual:** Phase 2 — Paper Trading activo en servidor cloud.
**Estrategia:** Pullback Continuation (EXP002 + EXP007 + EXP009).
**Assets:** BTC/USDT (longs only) y ETH/USDT (ambas direcciones).

Para conocer el estado actual al iniciar una sesión:
1. Lee `paper_state.json` → equity actual, posiciones abiertas, trades acumulados.
2. Corre `python summarize_logs.py` → tabla de trades, métricas de la semana.
3. Lee `experiments/exp_session_YYYY_MM_DD_*.md` más reciente → contexto de la última sesión.

---

## 3. Baseline de Referencia (EXP009 sin fees → EXP015/016 con fees reales)

Backtested sobre 180 días (Sep 2025 – Mar 2026). **No cambiar estos números sin un nuevo experimento.**

**Sin fees (referencia histórica):**

| Métrica | BTC (longs only) | ETH (ambas dir.) |
|---------|-----------------|-----------------|
| Trades | 99 | 207 |
| Win rate | 39.4% | 41.1% |
| Return | +18.45% | +57.95% |
| Max DD | 7.78% | 10.76% |
| Profit Factor | **1.297** | **1.375** |
| Expectancy | +$18.63 | +$27.99 |

**Con fees reales (Taker 0.05%/lado) — EXP015/016 — baseline operativo actual:**

| Métrica | BTC (EXP015) | ETH (EXP016A — producción) |
|---------|-------------|--------------------------|
| Trades | 99 | 103 (SL≥0.50%) |
| Win rate | 39.4% | 46.6% |
| Return | -15.83% | **+30.11%** |
| Max DD | 21.77% | **4.90%** |
| Profit Factor | 0.777 ⚠️ | **1.413** |
| Expectancy | -$15.99 | +$29.23 |

⚠️ **BTC sigue siendo negativo con fees** — en investigación. ETH está en producción con SL≥0.50%.

Cualquier experimento nuevo se evalúa **con fees incluidos** contra estos números.
**Criterio mínimo de KEEP:** PF > 1.0 en ambos assets con fees, MaxDD no empeora.

---

## 4. Parámetros de Riesgo Activos en Live

Implementados en `core/paper_engine.py` (commit `043962f`):

| Mecanismo | Valor | Lógica |
|-----------|-------|--------|
| **Circuit Breaker** | 2 pérdidas consecutivas → pausa 48h | `cb_consecutive_losses`, `cb_until` en `paper_state.json` |
| **Break-Even Stop** | Al 80% del camino al TP → SL a entry ±0.2% | Protege ganancias sin cerrar prematuramente |
| **Cooldown** | 45 min tras cualquier cierre de trade | Evita re-entradas inmediatas tras pérdidas |

**Sizing:** 1% de equity por trade. R:R = 2:1. Máximo 1 posición abierta por asset.

---

## 5. Mapa del Código (Área de Trabajo)

```
core/
  strategy_pullback.py   ← señales, filtros (EMAs, Kaufman ER), validación del setup
  trade_logic.py         ← cálculo de SL/TP y detección de salidas
  indicators_v2.py       ← EMA, slope, Efficiency Ratio (matemáticas puras)
  paper_engine.py        ← motor paper: CB, BE stop, cooldown, estado persistente

backtest/
  backtest_v2.py         ← framework base (load_data, helpers)
  backtest_exp002.py … backtest_exp014.py  ← experimentos históricos

experiments/             ← notas y resultados en markdown (leer antes de experimentar)
data/                    ← CSVs históricos y JSONs de resultados de backtest
logs/                    ← logs diarios del paper trading (paper_YYYYMMDD.log)
```

**Archivos de datos disponibles:**
- `data/BTCUSDT_15m_last_180d.csv` y `data/BTCUSDT_1h_last_200d.csv` → hasta Mar 25 2026
- `data/ETHUSDT_15m_last_180d.csv` y `data/ETHUSDT_1h_last_200d.csv` → hasta Mar 25 2026
- Para datos más recientes: correr `python fetch_all.py` (descarga BTC + ETH de Binance)

---

## 6. Índice de Experimentos (EXP001–EXP016)

Antes de proponer un experimento, **verificar que no esté ya testeado aquí.**

| Exp | Descripción | Decisión |
|-----|-------------|----------|
| EXP001 | Baseline: EMA20 pullback + trigger 15m | BASE |
| EXP002 | Filtros calidad: EMA50 slope, dist EMA50, body ratio, range floor | **KEEP** |
| EXP003 | Kaufman ER ≥ 0.15 (eficiencia direccional) | **KEEP** |
| EXP004 | TP más ajustado | REVERT |
| EXP005 | Cross-asset (BNB, DOGE, SOL, XRP) | REVERT — solo BTC/ETH |
| EXP006 | Walk-forward validation | Validación — no cambio |
| EXP007 | SL mínimo 0.15% (evita SLs microscópicos) | **KEEP** |
| EXP008 | Filtro EMA200 + ATR crash detector (compuesto) | REVERT — PF baja en ambos |
| EXP009 | BTC longs only (shorts eliminados de BTC) | **KEEP** — BTC PF 1.132→1.297 |
| EXP010 | EMA200 dirección macro + ATR regime (v2) | REVERT — peor en ambos |
| EXP011 | SL mínimo basado en ATR14 de 15m | REVERT — DD sube, WR cae |
| EXP012 | Filtro EMA spread ≥ 0.5% (todas las entradas) | REVERT — destruye BTC |
| EXP013 | Filtro EMA spread ≥ 0.5% solo en shorts | REVERT — ETH PF baja |
| EXP014 | Filtro EMA200 solo en ETH (longs>EMA200, shorts<EMA200) | REVERT — ETH ret +58→+15% |
| EXP015 | Backtest con fees reales (Taker 0.05%/lado) | INFORMATIVO — BTC PF→0.777, ETH PF→0.951 |
| EXP016 | Fee/edge fix: SL≥0.50% y/o RR=3:1 (3 variantes con fees) | **KEEP parcial** — ver abajo |

**EXP016 — decisiones por variante:**
- **Variante A (SL≥0.50%, RR=2:1) → KEEP para ETH**: PF 0.951→**1.413**, ret +30%, MaxDD 4.9%. Aplicado en producción.
- **Variante B (SL≥0.15%, RR=3:1) → REVERT en ambos**: WR cae, fees no mejoran suficientemente.
- **Variante C (SL≥0.50%, RR=3:1) → PENDIENTE para BTC**: BTC PF=1.053 pero solo 23 trades en 180d (insuficiente).

**IMPORTANTE: todos los experimentos futuros deben incluir fees (0.05%/lado) en el backtest.**
El baseline real con fees es: BTC PF=0.777, ETH PF=0.951 (EXP015).

**Pendiente de re-evaluar:**
- **BTC con fees**: sigue siendo negativo (PF 0.777→0.831 con SL≥0.50%). Necesita investigación:
  opciones son limit orders en entry (Maker 0.02%), RR asimétrico, o SL mínimo intermedio.
  Ver `exp_session_2026_04_26_fees.md`.
- EXP012 variant: re-testear con ≥365 días de datos y fees incluidos. Ver `exp_session_2026_04_26_paper_losses.md`.

---

## 7. Reglas de Modificación

1. **Nunca inventes datos.** Si un log está incompleto, pide más información.
2. **Una variable a la vez.** Cada experimento aísla un único cambio.
3. **Solo diffs.** Cuando propongas código, entrega solo la función modificada + nombre de archivo. No reescribas archivos completos.
4. **No sobreajustar.** No agregues filtros para evitar un trade perdedor específico. Busca soluciones que mejoren los 180 días de backtest, no solo el período visible.
5. **Fricciones de mercado.** Asume siempre comisiones (Taker/Maker) y slippage.

---

## 8. Protocolo de Diagnóstico (Test-Driven)

Para cualquier cambio propuesto, seguir este flujo **sin excepciones:**

1. **Clasificar** — Identificar el patrón en los logs (SL por ruido, falsa ruptura, ganancia devuelta).
2. **Hipótesis** — Explicar la deficiencia lógica y qué cambiaría.
3. **Experimento** — Crear `backtest/backtest_expNNN.py` con el cambio aislado.
4. **Validar** — Comparar contra baseline EXP009. Debe mejorar PF sin empeorar MaxDD.
5. **Propuesta final** — Solo si el experimento es KEEP, entregar el diff exacto.

**Documentar siempre** el resultado en `experiments/exp_session_YYYY_MM_DD_*.md`.

---

## 9. Entorno Técnico

```bash
# Activar entorno virtual
source venv/bin/activate

# Correr un backtest
python backtest/backtest_exp009.py

# Descargar datos frescos de Binance (BTC + ETH)
python fetch_all.py

# Ver resumen de paper trading
python summarize_logs.py

# Resetear paper trading (nueva corrida limpia)
python reset_paper_logs.py
```

**Credenciales:** Solo lectura de Binance. Configuradas en `.env` (no commitear).
**Estado live:** `paper_state.json` (sincronizado con GCS automáticamente).
