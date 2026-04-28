# V2 Roadmap — Sistema Regime-Agnostic
**Rama:** `v2-regime-agnostic`  
**Inicio:** 2026-04-26  
**Objetivo:** PF > 1.2 con fees en cualquier ventana de 90 días, independiente del régimen de mercado.

---

## Contexto y Problema

El sistema actual (pullback continuation EXP002) tiene edge real, pero solo en un régimen:
**trending con pullbacks**. En los otros 3 regímenes (momentum extremo, sideways, crash) el PF
cae por debajo de 1.0 con fees.

Esto fue confirmado con validación over 730 días:
- ETH EXP016A: PF=1.413 (180d IS) → PF=0.944 (730d OOS)
- BTC EXP017-B: PF=1.126 (730d) pero concentrado en regímenes tendenciales

La directiva es: **"quiero un sistema que funcione siempre en cualquier régimen."**

La solución es una **arquitectura de dos estrategias + clasificador de régimen**:

```
ADX(14) en 1h > 25  →  Strategy A: Pullback Continuation (actual)
ADX(14) en 1h < 20  →  Strategy B: Mean Reversion (nueva)
ADX entre 20-25     →  Sin trades (zona de transición)
```

---

## Estado actual al iniciar v2

| Asset   | Estrategia activa | SL min  | PF backtest | Estado  |
|---------|-------------------|---------|-------------|---------|
| BTC/USDT | EXP017-B         | ≥0.30%  | 1.126 (730d)| Live    |
| ETH/USDT | EXP016A          | ≥0.50%  | 1.413 (180d)| Live    |

Live en: Cloud Run europe-west1. State: `btc_state.json` / `eth_state.json`.
Logs: `logs/btc_YYYYMMDD.log` / `logs/eth_YYYYMMDD.log`.

---

## Fases y Tareas

---

### FASE 1 — Validar el clasificador de régimen
**Experimento:** EXP018  
**Archivo:** `backtest/backtest_exp018.py`  
**Estado:** ❌ FALLÓ — ADX selecciona los peores trades

**Objetivo:**
Confirmar que ADX(14) en 1h separa correctamente los regímenes en los 730d de BTC y ETH.
El pullback strategy debería tener PF significativamente mayor cuando ADX > 25.

**Datos requeridos:**
- `data/BTCUSDT_15m_last_730d.csv` + `data/BTCUSDT_1h_last_740d.csv`
- `data/ETHUSDT_15m_last_730d.csv` + `data/ETHUSDT_1h_last_740d.csv`
- Ya descargados con `python fetch_all.py --2y`

**Implementación:**
1. Copiar `backtest_exp017.py` como base → nuevo `backtest_exp018.py`
2. Añadir cálculo de ADX(14) en el 1h dentro de `prepare_1h()` de `backtest_v2.py`,
   o como función local en el backtest (más rápido para iterar)
3. Añadir filtro de entrada: `if row['adx_1h'] < 25: continue` (solo entra en trending)
4. Añadir también la variante inversa: `if row['adx_1h'] > 20: continue` (solo entra en choppy)
   → esto permite ver cuántos trades caen en cada régimen y qué PF tienen

**Variantes a testear en EXP018:**
| Variante | Filtro              | Asset |
|----------|---------------------|-------|
| A        | ADX > 25 (trending) | BTC   |
| B        | ADX > 25 (trending) | ETH   |
| C        | ADX > 20 (relajado) | BTC   |
| D        | ADX > 20 (relajado) | ETH   |

**Criterios de éxito (CUALQUIERA de estas combinaciones):**
- PF > 1.2 con fees, o
- PF mejora vs baseline (EXP017-B/EXP016A) sin aumentar MaxDD
- Trade count no cae por debajo de 80 en 730d (mínimo estadístico)

**Criterio de fracaso:**
- ADX no diferencia: PF con ADX filter ≈ PF sin filter → clasificador no funciona
- En ese caso: probar EXP018-variante con `ATR_ratio = ATR(14) / precio` como clasificador
  (alto ATR_ratio = momentum/volatil, bajo = rango)

**Output esperado del script:**
```
=== BTC EXP018-A (ADX>25, SL≥0.30%) ===
Trades: 180  (de 241 sin filtro)
Win rate: 41.2%
PF: 1.31  (vs 1.126 sin filtro)
Return: +28.4%
MaxDD: 9.1%

=== BTC trades descartados por ADX (choppy) ===
Trades descartados: 61
PF de esos trades: 0.73  ← confirma que el filtro elimina los malos
```

---

### FASE 2 — Filtro de momentum extremo (pivot desde EXP018)
**Experimento:** EXP019  
**Archivo:** `backtest/backtest_exp019.py`  
**Estado:** ✅ APROBADO — SLOPE_CAP (EMA50 slope > 0.20%) mejora PF en ambos assets

**Objetivo:**
Diseñar y validar una estrategia de mean reversion que sea rentable (PF > 1.1 con fees)
específicamente en períodos donde ADX < 20 (mercados choppy/ranging).

**Lógica de la estrategia:**
```
Condición de régimen:
  ADX(14) en 1h < 20  → mercado en rango

Señal de entrada LONG en 15m:
  1. Precio toca o cruza la Banda Bollinger inferior (BB20, 2σ)
  2. RSI(14) < 35 en 15m  (sobrevendido)
  3. Vela de reversión: close > open, body ≥ 40% del range de la vela
  4. El precio está entre EMA20 y EMA50 (no en free-fall)

Señal de entrada SHORT en 15m:
  1. Precio toca o cruza la Banda Bollinger superior
  2. RSI(14) > 65 en 15m
  3. Vela bajista de reversión
  4. El precio está entre EMA20 y EMA50 (no en momentum extremo)

SL: más allá del swing high/low de las últimas 3 velas 15m + 0.1%
    SL mínimo: 0.30% del precio (cubre fees)

TP: media de las Bollinger Bands (precio de equilibrio del rango)
    Si el TP implica RR < 1.5:1, descartar el trade

RR mínimo: 1.5:1
Risk: 1% equity por trade (igual que Strategy A)
```

**Implementación:**
1. Crear `backtest/backtest_exp019.py`
2. Calcular BB20(2σ) y RSI(14) sobre el 15m → añadir en `prepare_15m()` o localmente
3. Calcular ADX(14) sobre el 1h → mismo que EXP018
4. Implementar lógica de entrada/salida descrita arriba
5. Testear únicamente sobre los períodos donde ADX < 20 en los 730d
6. Comparar el equity curve vs los períodos donde EXP018 (Strategy A) no opera

**Criterios de éxito:**
- PF > 1.1 con fees sobre 730d
- MaxDD < 15%
- Al menos 80 trades (significativo estadísticamente)
- Expectancy > $10 por trade (con $10,000 de equity)
- El equity curve de Strategy B es creciente en períodos donde Strategy A pierde

**Criterio de fracaso:**
- PF < 1.0: la mean reversion no funciona en crypto con fees → considerar:
  - Variante: BB + RSI + volumen confirma (high volume en reversión)
  - Variante: usar solo RSI extremo en 1h (más lento, más confiable)
  - Variante: trailing SL en lugar de SL fijo

**Iteraciones previstas:**
- EXP019-A: diseño base (descrito arriba)
- EXP019-B si A falla: BB(30, 2.5σ) + RSI(21) < 30 (señales más extremas, menos trades, más limpios)
- EXP019-C si B falla: solo longs en BTC (igual que Strategy A, más conservador)

---

### FASE 3 — Sistema combinado
**Experimento:** EXP020  
**Archivo:** `backtest/backtest_exp020.py`  
**Estado:** ✅ OBSOLETO — arquitectura dos-estrategias descartada; diversificación BTC+ETH cubre todos los regímenes sin routing

**Objetivo:**
Backtest del sistema completo: Strategy A (trending) + Strategy B (choppy) + classifier ADX.
Verificar que la combinación es mejor que cualquiera de las dos solas.

**Implementación:**
1. Crear `backtest/backtest_exp020.py`
2. En cada barra de 15m, evaluar el ADX del 1h:
   - ADX > 25 → correr lógica Strategy A
   - ADX < 20 → correr lógica Strategy B
   - ADX 20-25 → skip (sin trades)
3. Un solo equity pool, máx 1 posición abierta por asset
4. Misma gestión de riesgo: 1% equity, circuit breaker, cooldown

**Métricas a calcular:**
- PF combinado sobre 730d
- PF de cada Strategy A y B por separado dentro del sistema
- PF en cada ventana de 180d (4 ventanas) → mínimo 1.0 en todas
- MaxDD combinado
- Correlación de los equity curves de A y B (queremos correlación negativa)
- % del tiempo en régimen trending / choppy / transición

**Criterios de éxito del sistema combinado:**
- PF > 1.2 sobre 730d con fees
- PF > 1.0 en **cada** ventana de 180d (esto valida la robustez inter-régimen)
- MaxDD < 15%
- El PF combinado es mayor que el de Strategy A sola y Strategy B sola (efecto diversificación)

**Criterio de fracaso:**
- El sistema combinado no supera a Strategy A sola → la mean reversion cancela ganancias
  En ese caso: revisar el clasificador (threshold de ADX) o la zona de transición

---

### FASE 4 — Walk-forward validation
**Experimento:** EXP021  
**Archivo:** `backtest/backtest_exp021.py`  
**Estado:** ✅ APROBADO — sistema combinado BTC+ETH pasa las 4 ventanas bajo criterio combinado

**Objetivo:**
Verificar que el sistema no está overfit al período de 730d. El edge debe existir en
cada sub-período por separado, sin re-optimizar parámetros.

**Metodología:**
- Dividir los 730d en 4 ventanas iguales de ~182d cada una:
  - Ventana 1: 2024-04-27 → 2024-10-25
  - Ventana 2: 2024-10-25 → 2025-04-24
  - Ventana 3: 2025-04-24 → 2025-10-21
  - Ventana 4: 2025-10-21 → 2026-04-19
- En cada ventana: usar los **mismos parámetros** del EXP020 (sin re-optimizar)
- Reportar PF, return, MaxDD, trade count por ventana

**Criterio de éxito:**
- PF > 1.0 en las 4 ventanas
- MaxDD < 20% en cualquier ventana individual
- Trade count ≥ 20 en cada ventana (suficientes señales)

**Criterio de fracaso:**
- 1 o más ventanas con PF < 1.0 → identificar qué régimen falla y en cuál ventana
  → puede indicar que el parámetro ADX threshold necesita ajuste fino
  → NO re-optimizar para pasar la ventana que falla; entender el porqué

---

### FASE 5 — Deploy del sistema v2
**Archivo:** `deploy/deploy_004.md`  
**Estado:** 🟡 EN CURSO — código implementado, pendiente PR a master

**Cambios en el código live:**

**`core/indicators_v2.py`** — añadir:
- `adx(df, period=14) → Series`: cálculo del ADX de Wilder
- `bollinger_bands(df, period=20, std=2.0) → (upper, mid, lower)`: BB para Strategy B

**`core/strategy_pullback.py`** — modificar:
- `is_trending_regime(row) → bool`: ADX > 25 en 1h (nueva función de gate)
- Las funciones existentes no cambian; solo se añade el gate antes de llamarlas

**`core/strategy_mean_reversion.py`** (nuevo archivo):
- `is_ranging_regime(row) → bool`: ADX < 20 en 1h
- `is_mr_long_signal(row) → bool`: BB inferior + RSI < 35 + vela de reversión
- `is_mr_short_signal(row) → bool`: BB superior + RSI > 65 + vela de reversión
- `calculate_mr_sl_tp(row, direction) → (sl, tp)`: SL = swing high/low + TP = BB mid

**`paper_monitor.py`** — modificar:
- `scan_asset()`: añadir routing por régimen
  - Si `is_trending_regime(row)` → Strategy A (pullback)
  - Si `is_ranging_regime(row)` → Strategy B (mean reversion)
  - Si ninguno → skip (zona de transición)

**Criterio para trigger el deploy:**
Todos los criterios de EXP018-021 deben haber pasado.
Crear `deploy/deploy_004_FECHA.md` con el registro completo.

---

## Árbol de decisión

```
EXP018 pasa?
  SÍ → EXP019
  NO → EXP018 variante ATR_ratio → si pasa: EXP019
                                  → si falla: replantear clasificador

EXP019 pasa?
  SÍ → EXP020
  NO → EXP019-B (señales más extremas) → si pasa: EXP020
                                        → si falla: considerar funding rate strategy

EXP020 pasa?
  SÍ → EXP021
  NO → revisar ADX thresholds o zona de transición → re-run EXP020

EXP021 pasa?
  SÍ → Deploy v2 (deploy_004)
  NO → identificar ventana que falla → EXP022 con ajuste específico
```

---

## Parámetros fijos (NO cambiar entre experimentos)

| Parámetro        | Valor  | Motivo                                      |
|-----------------|--------|---------------------------------------------|
| Risk per trade  | 1%     | Consistencia con backtest histórico         |
| R:R mínimo      | 2:1    | Cubre fees + expectancy positiva            |
| Fee por lado    | 0.05%  | Taker Binance USDM Futures VIP0             |
| Circuit breaker | 2 loss | Igual que sistema actual                    |
| Max posiciones  | 1 por asset | Sin cambio                             |

---

## Archivos de referencia

| Archivo | Descripción |
|---------|-------------|
| `backtest/backtest_exp017.py` | Último backtest válido (BTC 730d, EXP017-B) |
| `backtest/backtest_exp016.py` | Último backtest ETH válido (EXP016A) |
| `core/strategy_pullback.py`  | Lógica Strategy A (entrada pullback) |
| `core/indicators_v2.py`      | EMA, slope, Efficiency Ratio — añadir ADX y BB aquí |
| `core/backtest_v2.py`        | Framework base de backtest |
| `data/*_730d.csv`            | Datos 730d BTC y ETH para todos los EXP de v2 |

---

## Notas importantes

1. **Todos los experimentos de v2 usan 730d de datos** (no 180d). El IS de 180d demostró
   ser insuficiente para detectar edge vs ruido.

2. **Todos los experimentos incluyen fees** (0.05%/lado, round-trip 0.10%). Sin excepción.

3. **No optimizar parámetros para que un período específico funcione.** Si un threshold
   de ADX (ej. 22 vs 25) solo mejora un período a costa de otro, es overfitting.

4. **Documentar siempre** en `experiments/exp_session_YYYY_MM_DD_*.md` antes de cerrar
   la sesión, aunque el experimento no haya terminado.

5. **Branch v2-regime-agnostic** es la rama de trabajo. No mergear a master hasta que
   EXP021 pase (walk-forward completo).
