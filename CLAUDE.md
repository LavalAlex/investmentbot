# Claude System Context: InvestmentBot V3

## 1. Rol y Misión

Eres Claude, un Ingeniero Cuantitativo Senior especializado en desarrollo de sistemas algorítmicos.
Tu misión es operar un sistema de trading de criptomonedas (BTC/USDT y ETH/USDT) basado en
**Daily Breakout**: PF > 1.2 con fees, robusto en cualquier régimen de mercado.

**NO** toques infraestructura (Docker, Google Cloud, FastAPI) salvo que se te pida explícitamente.
Tu foco es 100% la lógica cuantitativa, el motor de reglas y la gestión de riesgo.

---

## 2. Estado del Proyecto

**Fase actual:** V3 — Daily Breakout. Estrategia validada, arquitectura construida, pendiente deploy.
**Producción activa (master):** Pullback EXP017-B (BTC) + EXP016A (ETH) — **a reemplazar**.

### Al iniciar una sesión:
1. Lee `experiments/v2_roadmap.md` → estado de cada fase
2. Lee el `experiments/exp_session_*.md` más reciente → contexto de la última sesión
3. Lee `btc_breakout_state.json` / `eth_breakout_state.json` → equity y posiciones del breakout
4. (Opcional) Lee `paper_state.json` → equity del pullback en producción (sistema viejo)

---

## 3. Estrategia Activa: Daily Breakout

### Lógica de señal

```
Señal LONG (diaria, longs únicamente):
  1. close > max(close, últimos 10 días)   — nuevo máximo de 10 días
  2. volume ≥ 1.5 × media(volumen 20 días) — volumen confirma el movimiento

SL = close - ATR(14) × 1.5
TP = entry + 2 × (entry - SL)
Risk = 1% del equity por trade
```

### Validación completa (sesiones 2026-06-09 y 2026-06-10)

| Test | BTC | ETH | Resultado |
|------|-----|-----|-----------|
| IS 5 años | PF=1.735, MaxDD=4.0% | PF=1.711, MaxDD=5.1% | ✅ |
| OOS 730d | PF=1.627, MaxDD=3.0% | PF=1.442, MaxDD=3.0% | ✅ |
| Walk-forward 3 ventanas | 3/3 | 3/3 (mínimo PF=1.065) | ✅ |
| Slippage entrada | Δpf=0.000 | Δpf=0.000 | ✅ no issue |
| Alpha vs Buy & Hold | Calmar 0.835 vs 0.165 | Calmar >> BnH en todos los períodos | ✅ |

### Por qué el breakout reemplaza al pullback

| Métrica | Pullback (730d) | Breakout (730d) |
|---------|----------------|----------------|
| PF BTC | 1.126 | **1.627** |
| PF ETH | 0.964 (pérdida) | **1.442** |
| PF BTC 5y | 0.896 (pérdida) | **1.735** |
| Trades/año BTC | 120+ | ~13 |
| Fees 730d BTC+ETH | **$8,168** | **$50** |
| MaxDD BTC | 11.8% | **3.0%** |

El pullback ganó +23.6% en BTC en los 730d específicos por el bull market 2024, pero sobre
5 años pierde dinero. El breakout es robusto en todos los regímenes.

---

## 4. Mapa del Código

```
core/
  strategy_breakout.py   ← NUEVA estrategia activa (Daily Breakout)
  strategy_pullback.py   ← estrategia ARCHIVADA (en producción hasta reemplazo)
  strategy_mean_reversion.py  ← descartada (sin edge en crypto con fees)
  trade_logic.py         ← cálculo SL/TP y detección de salidas
  indicators_v2.py       ← EMA, slope, ER, ADX, BB, RSI
  paper_engine.py        ← motor paper genérico (state, GCS sync)

paper_engine_breakout.py   ← NUEVO motor (reemplaza paper_monitor.py)
paper_monitor.py           ← motor ARCHIVADO (pullback, a desactivar en deploy)

backtest/
  backtest_camino1_breakout.py     ← IS 5y BTC+ETH (Camino 1 ganador)
  backtest_breakout_oos.py         ← OOS 730d (configs validadas)
  backtest_breakout_combined.py    ← sistema combinado BTC+ETH 5y+730d
  backtest_breakout_optimize.py    ← grid search parámetros
  backtest_breakout_eth5y.py       ← ETH IS 5y vol≥1.5× grid
  backtest_breakout_slippage.py    ← test slippage (Δpf=0 en crypto 24/7)
  backtest_breakout_wf.py          ← walk-forward 3 ventanas
  backtest_breakout_bnh.py         ← comparativa vs buy & hold

experiments/
  v2_roadmap.md                               ← roadmap detallado
  exp_session_2026_06_09_breakout_analysis.md ← sesión de descubrimiento
  exp_session_2026_06_10_breakout_architecture.md ← sesión de validación + arquitectura

data/
  BTCUSDT_1h_last_5y.csv    ← datos IS 5 años
  ETHUSDT_1h_last_5y.csv
  BTCUSDT_1h_last_740d.csv  ← datos OOS 730d
  ETHUSDT_1h_last_740d.csv
```

---

## 5. Estado del Sistema

### Breakout (nuevo — paper trading local)

| Asset | Config | PF IS 5y | PF OOS 730d | State file | Logs |
|-------|--------|----------|-------------|-----------|------|
| BTC/USDT | 10d vol≥1.5× ATR×1.5 RR=2 | 1.735 | 1.627 | btc_breakout_state.json | btc_breakout_YYYYMMDD.log |
| ETH/USDT | 10d vol≥1.5× ATR×1.5 RR=2 | 1.711 | 1.442 | eth_breakout_state.json | eth_breakout_YYYYMMDD.log |

### Pullback (viejo — a reemplazar)

| Asset | Estrategia | PF | State file |
|-------|-----------|-----|-----------|
| BTC/USDT | EXP017-B | 1.126 (730d) | btc_state.json |
| ETH/USDT | EXP016A | 0.964 (730d) | eth_state.json |

### Parámetros de riesgo (breakout)

| Mecanismo | Valor |
|-----------|-------|
| Risk por trade | 1% equity |
| R:R | 2:1 |
| Dirección | Longs únicamente |
| Frecuencia | ~13 trades/año por asset |
| Tiempo en mercado | ~25% |

---

## 6. Próximo Paso: Deploy V3

**Pendiente:** reemplazar `paper_monitor.py` (pullback) por `paper_engine_breakout.py` (breakout) en Cloud Run.

Pasos:
1. Actualizar Dockerfile: `CMD ["python", "paper_engine_breakout.py", "--loop"]`
2. Crear `deploy/deploy_005_FECHA.md` con el registro del cambio
3. Deploy a Cloud Run europe-west1
4. Monitorear primeras señales

**NO hacer deploy sin aprobación explícita del usuario.**

---

## 7. Historial de Experimentos

### EXP001–EXP017 — Pullback Continuation (completados, archivados)

| Exp | Descripción | Decisión |
|-----|-------------|----------|
| EXP001 | Baseline: EMA20 pullback + trigger 15m | BASE |
| EXP002 | Filtros calidad: EMA50 slope, dist EMA50, body ratio, range floor | KEEP |
| EXP003 | Kaufman ER ≥ 0.15 (eficiencia direccional) | KEEP |
| EXP004 | TP más ajustado | REVERT |
| EXP005 | Cross-asset (BNB, DOGE, SOL, XRP) | REVERT |
| EXP006 | Walk-forward validation | Validación |
| EXP007 | SL mínimo 0.15% | KEEP |
| EXP008 | Filtro EMA200 + ATR crash detector | REVERT |
| EXP009 | BTC longs only | KEEP |
| EXP010–014 | Varios filtros de régimen | REVERT todos |
| EXP015 | Fees reales 0.05%/lado — informativo | — |
| EXP016 | SL≥0.50% ETH | KEEP ETH PF=1.413 |
| EXP017 | BTC 730d: SL≥0.30% longs only | KEEP BTC PF=1.126 |

### EXP018–EXP021 — Regime-Agnostic (descartado, pivotado a breakout)

| Exp | Descripción | Resultado |
|-----|-------------|-----------|
| EXP018 | ADX filter en pullback | ❌ ADX empeora los resultados |
| EXP019 | SLOPE_CAP (EMA50 slope > 0.20%) | ✅ aprobado pero estrategia completa descartada |
| EXP020 | Sistema combinado A+B | ✅ obsoleto — diversificación BTC+ETH más simple |
| EXP021 | Walk-forward 4 ventanas | ✅ sistema combinado pasa |

### Sesión 2026-06-09 — Análisis de breakout (pivote de estrategia)

Probados y descartados: ETH ADX gate, BTC 4h gate, mean reversion BB+RSI, daily SMA gate,
pin bar MR, ATH proximity gate, equity drawdown pause.

**Winner:** Daily Breakout — BTC PF=1.475 (5y), ETH PF=1.549 (5y).
Ver: `experiments/exp_session_2026_06_09_breakout_analysis.md`

### Sesión 2026-06-10 — Validación completa + arquitectura

Validación final: ETH IS 5y ✅, slippage ✅, walk-forward 3v ✅, alpha vs BnH ✅.
Arquitectura: `core/strategy_breakout.py` + `paper_engine_breakout.py`.
Ver: `experiments/exp_session_2026_06_10_breakout_architecture.md`

---

## 8. Reglas de Modificación (No cambiar)

1. **Nunca inventes datos.** Si un log está incompleto, pide más información.
2. **Una variable a la vez.** Cada experimento aísla un único cambio.
3. **Solo diffs.** Cuando propongas código, solo la función modificada + archivo.
4. **No sobreajustar.** No agregues filtros para evitar un trade perdedor específico.
5. **Fricciones de mercado.** Todos los backtests incluyen fees 0.05%/lado. Sin excepción.
6. **Datos mínimos: 730d.** Los 180d son insuficientes para separar edge de ruido.

---

## 9. Protocolo de Experimento

1. **Leer** `experiments/v2_roadmap.md` → confirmar qué EXP toca y sus criterios
2. **Hipótesis** → por qué el cambio mejora el sistema
3. **Código** → crear `backtest/backtest_expNNN.py` con el cambio aislado
4. **Correr** → sobre datos 730d mínimo, con fees, BTC y ETH
5. **Validar** → comparar contra criterios del roadmap
6. **Decidir** → KEEP / REVERT / ITERAR + actualizar roadmap
7. **Documentar** → `experiments/exp_session_YYYY_MM_DD_*.md` antes de cerrar

---

## 10. Entorno Técnico

```bash
# Activar entorno virtual
source venv/bin/activate

# Correr el engine breakout (single scan)
python paper_engine_breakout.py

# Correr el engine breakout en loop
python paper_engine_breakout.py --loop

# Correr un backtest
python backtest/backtest_breakout_wf.py

# Descargar datos frescos
python fetch_all.py --2y

# Ver resumen de paper trading (pullback viejo)
python summarize_logs.py
```

**Credenciales:** Solo lectura de Binance. Configuradas en `.env` (no commitear).
**State breakout:** `btc_breakout_state.json` / `eth_breakout_state.json` (GCS cuando se deploya).
**State pullback (legacy):** `btc_state.json` / `eth_state.json`.
