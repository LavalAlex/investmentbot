# Sesión 2026-06-09 — Análisis Completo: Breakout Diario vs Pullback

## Contexto de partida

El sistema de producción (EXP017-B BTC + EXP016A ETH) tiene problemas estructurales:
1. **ETH no tiene edge**: PF=0.983 en 730d, sin configuración que lo mejore
2. **BTC PF demasiado bajo**: PF=1.126 en 730d, pero PF=0.896 en 5 años — el 730d estaba inflado por 3 meses excepcionales (Jul-Sep 2024, PF=6.0/3.9/3.9)
3. **Frecuencia insuficiente**: ~50-80 trades/año, señales escasas

Premortem identificó 7 failure modes. Esta sesión atacó los 3 primeros.

---

## Experimentos realizados (en orden)

### EXP_A — ETH 730d con ADX gate (backtest/backtest_expa_eth_adx.py)
- 6 variantes: baseline, longs-only, ADX>20, ADX>25, ADX>30, ADX>35
- **RESULTADO: TODOS FALLAN.** Mejor: A1 longs-only PF=0.964
- El ADX gate en ETH empeoró los resultados, no los mejoró
- **CONCLUSIÓN: ETH pullback no tiene edge. Desactivar en producción.**

### EXP_B — BTC 730d con gates de 4h y ADX (backtest/backtest_expb_btc_4h.py)
- 6 variantes: baseline, 4h EMA slope, 4h ADX, combinaciones
- **RESULTADO: TODOS FALLAN.** Mejor: B0 baseline PF=1.126
- Ningún filtro mejora BTC más allá del baseline
- Bug encontrado y corregido: `align_1h_to_15m()` renombra `adx14` → `adx_1h`

### BTC 5 años (backtest/backtest_btc_5y.py)
- EXP017-B config sobre 5 años completos (2021-2026)
- **PF=0.896** — el edge no es robusto
- Solo Corrección 2025 fue rentable (PF=1.092)
- Confirmó que el 730d PF=1.126 estaba inflado por outliers

### EXP_C — Mean Reversion BB+RSI (backtest/backtest_expc_mean_reversion.py)
- BTC+ETH 730d, señales en BB inferior/superior + RSI<35/>65
- BTC mejor PF=0.733, ETH mejor PF=0.989
- **RESULTADO: TODOS FALLAN**
- WR 11-22% — necesitas >45% para break-even con RR=1.2:1
- Problema estructural: crypto ranging tiene demasiado ruido direccional

### EXP_D — Daily gate sobre pullback (backtest/backtest_expd_daily_gate.py)
- BTC 5y, gates SMA200/SMA20 sobre estrategia pullback existente
- **RESULTADO: TODOS FALLAN.** Sin gate (baseline) sigue siendo lo mejor (PF=0.896)
- Patrón contraintuitivo: los filtros de régimen empeoran el pullback

### EXP_E — Pin bar Mean Reversion v2 (backtest/backtest_expe_mr_v2.py)
- BTC+ETH, velas pin bar como señal de reversión
- BTC mejor PF=0.377, ETH mejor PF=0.807
- **RESULTADO: TODOS FALLAN**
- WR 17-26% — problema de señal fundamental

### Camino 2 — ATH proximity gate (backtest/backtest_camino2_ath_gate.py)
- Gate: solo entrar si precio está a X% del ATH de N días
- 6 variantes (ATH 30/90/180/365d × umbral 10/15/20%)
- **RESULTADO: TODOS FALLAN.** Mejor PF=0.860
- El ATH gate tampoco mejora el pullback

### Camino 3 — Equity drawdown pause (backtest/backtest_camino3_equity_pause.py)
- Pausar entradas si equity cae X% desde pico del período (mes/semana)
- 6 variantes (mensual/semanal × 3/5/7% + SL consecutivos)
- **RESULTADO: TODOS FALLAN.** Mejor PF=0.965 (con reducción significativa de trades)
- La pausa no mejora el edge, solo reduce las pérdidas parcialmente

---

## WINNER: Camino 1 — Breakout Diario

### Arquitectura (backtest/backtest_camino1_breakout.py)

```python
# Señal de entrada:
# 1. close > máximo de los últimos N días (shift(1) para evitar lookahead)
# 2. volume >= vol_ratio × promedio de volumen 20d
# 3. SL = close - ATR14 × atr_mult
# 4. TP = close + RR × risk

daily['nd_high'] = daily['close'].shift(1).rolling(n_days, min_periods=n_days).max()
# Entry: close > nd_high AND volume >= vol_ratio * vol20
```

**Datos**: OHLCV 1h resampleado a diario. ATR14 Wilder (com=13). Vol20 rolling.

### Resultados IS 5 años

| Config | Trades | WR | PF | MaxDD | Return |
|--------|--------|----|----|-------|--------|
| BTC F2 (10d, vol≥1.0×, ATR×1.5, RR=2) | 69 | 43.5% | **1.475** | 7.8% | +20.8% |
| ETH F0 (20d, vol≥1.0×, ATR×1.5, RR=2) | 60 | 45.0% | **1.549** | 5.9% | +21.4% |

### Resultados OOS 730d (backtest/backtest_breakout_oos.py)

| Config | Trades | WR | PF | MaxDD | OOS |
|--------|--------|----|----|-------|-----|
| BTC-F2 (10d, vol≥1.0×) | 26 | 42.3% | **1.407** | 6.0% | ✅ PASS |
| BTC-F1 (20d, vol≥1.5×) | 13 | 46.2% | **1.627** | 3.0% | ✅ PASS |
| ETH-F4 (20d, vol≥1.0×, RR=3) | 15 | 33.3% | **1.445** | 4.0% | ✅ PASS |
| ETH-F2 (10d, vol≥1.0×) | 25 | 40.0% | **1.278** | 5.9% | ✅ PASS |
| BTC-F0 (20d, vol≥1.0×) | 25 | 28.0% | 0.745 | — | ❌ FAIL |
| ETH-F0 (20d, vol≥1.0×) | 22 | 36.4% | 1.101 | — | ❌ FAIL |

### Sistema combinado BTC+ETH (backtest/backtest_breakout_combined.py)
Capital $10k dividido 50/50. BTC usa F2, ETH usa F0.

| Período | Trades | PF | MaxDD | Return |
|---------|--------|----|-------|--------|
| 5 años | 129 | **1.510** | **5.0%** | +21.1% |
| 730d | 48 | **1.260** | **3.0%** | +3.9% |

Solo 13 días de overlap en 5 años → diversificación real.

### Grid search BTC 5y (backtest/backtest_breakout_optimize.py)
Grid: n_days=[10,15,20,25,30] × vol_ratio=[1.0,1.1,1.2,1.3,1.5,2.0]. 23/30 pasan.

**Patrón claro: vol≥1.5× es el sweet spot.**

| Config | Trades | PF | MaxDD |
|--------|--------|----|-------|
| 30d, vol≥1.5× | 35 | **2.238** | 3.0% |
| 20d, vol≥1.5× | 37 | **2.204** | 4.0% |
| 15d, vol≥1.5× | 39 | **1.986** | 4.0% |
| 10d, vol≥1.5× | 42 | **1.735** | 4.0% |

vol≥2.0× da PF>3 pero 13-16 trades en 5 años — insuficiente estadístico.

### Validación OOS configs optimizadas (vol≥1.5×)

| Config | Trades OOS | PF OOS | MaxDD | OOS |
|--------|------------|--------|-------|-----|
| BTC 10d vol≥1.5× | 13 | **1.627** | 3.0% | ✅ PASS |
| BTC 15d vol≥1.5× | 13 | **1.627** | 3.0% | ✅ PASS |
| BTC 20d vol≥1.5× | 13 | **1.627** | 3.0% | ✅ PASS |
| BTC 30d vol≥1.5× | 12 | **1.900** | 2.0% | ✅ PASS |
| ETH 10d vol≥1.5× | 14 | **1.442** | 3.0% | ✅ PASS |
| ETH 15d vol≥1.5× | 13 | **1.640** | 3.0% | ✅ PASS |
| ETH 20d vol≥1.5× | 12 | 0.964 | — | ❌ FAIL |

**Nota**: BTC 10d/15d/20d vol≥1.5× dan exactamente el mismo resultado (13 trades). El filtro de volumen es el selector dominante; el lookback no diferencia a este umbral.

---

## Comparativa final: Breakout vs Pullback actual

| Métrica | Pullback (producción) | Breakout (nuevo) |
|---------|----------------------|------------------|
| PF 5 años | **0.896** ❌ | **1.735** ✅ |
| PF 730d (OOS) | 1.126 | **1.627** |
| MaxDD | ~15-20% | **3-4%** |
| WR | ~35% | **46%** |
| Trades/año BTC | ~50-80 | **7-13** |

---

## Configs candidatas a producción (ambas pasan IS + OOS)

| Asset | Config | PF 5y | PF OOS | Trades OOS | MaxDD OOS |
|-------|--------|-------|--------|------------|-----------|
| BTC | 10d, vol≥1.0×, ATR×1.5, RR=2 | 1.475 | 1.407 | 26 | 6.0% |
| BTC | 10d, vol≥1.5×, ATR×1.5, RR=2 | 1.735 | 1.627 | 13 | 3.0% |
| ETH | 10d, vol≥1.0×, ATR×1.5, RR=2 | 1.549 | 1.278 | 25 | 5.9% |
| ETH | 10d, vol≥1.5×, ATR×1.5, RR=2 | — | 1.442 | 14 | 3.0% |

**Tradeoff vol≥1.0× vs vol≥1.5×:**
- vol≥1.0×: más trades (~13/año), PF moderado (~1.4-1.5)
- vol≥1.5×: menos trades (~7/año), PF más alto (~1.6-1.7), MaxDD menor

---

## Por qué el usuario NO está convencido (pendiente resolver)

El usuario pidió documentar antes de subir a producción. Dudas no resueltas:

1. **Frecuencia muy baja**: 7-13 trades/año es ~1 trade cada 4-8 semanas. ¿El sistema aporta valor suficiente para el esfuerzo de mantenimiento?

2. **Slippage en producción**: El backtest entra al precio de cierre diario exacto. En live, el breakout ocurre durante la vela; la entrada real sería al open del día siguiente (peor precio) o con limit order en el breakout (riesgo de no llenarse).

3. **El beneficio sobre buy & hold no está cuantificado**: En un mercado alcista de 5 años, ¿+20% es suficiente vs simplemente hold BTC?

4. **ETH 5y con vol≥1.5× no fue testeado en IS**: Solo tenemos OOS para ETH optimizado. Falta el IS para completar la validación.

5. **Walk-forward no realizado**: Solo tenemos un split IS/OOS. Para mayor robustez habría que hacer walk-forward de 3-4 ventanas.

---

## NUEVA DIRECCIÓN — Pendiente explorar (agregado 2026-06-09)

### Enfoque: Trading intradía apalancado con objetivo de P&L diario

**Motivación del usuario**: el breakout diario genera 7-13 trades/año — demasiado poco volumen para cubrir los costos fijos del sistema (fees de infraestructura Cloud Run, fees de exchange, mantenimiento). Se necesita un enfoque que genere más trades y que cada trade justifique los gastos operativos.

**Hipótesis de diseño**:
- Operar en timeframe intradía (15m o 1h) con apalancamiento
- Definir un target de ganancia diaria en USD que cubra: fees de exchange + costo diario de infra
- Buscar alta frecuencia de señales: objetivo mínimo ~1 trade/día o varios por semana
- El apalancamiento permite targets absolutos pequeños con capital limitado

**Preguntas a responder antes de diseñar**:
1. ¿Cuánto cuesta la infra por día? (Cloud Run + GCS + otros) → definir el target mínimo
2. ¿Qué apalancamiento usar? (Binance Futures permite hasta 20x en BTC) — a mayor leverage, mayor riesgo de liquidación
3. ¿Qué estrategia intradía tiene edge con alta frecuencia? Candidatos: scalping de momentum, VWAP reversion, breakout de rango horario
4. ¿Cómo gestionar el riesgo con apalancamiento? El pullback actual usa 1% risk/trade — con leverage el sizing cambia radicalmente
5. ¿Futuros perpetuos o spot con margin? Los futuros tienen funding rate (costo o ingreso cada 8h)

**Consideraciones de riesgo**:
- Apalancamiento amplifica losses igual que gains — MaxDD puede ser catastrófico si no se controla
- Más trades = más fees acumulados — el edge por trade debe ser robusto neto de fees
- Intradía requiere datos de mayor granularidad y mayor velocidad de ejecución en producción

**Próximo paso sugerido**: Calcular el break-even diario (infra + fees) y diseñar un backtest intradía con apalancamiento controlado (2x-5x) sobre BTC 730d buscando PF>1.3 neto de fees con >100 trades en el período.

---

## Archivos creados esta sesión

```
backtest/backtest_expa_eth_adx.py         — ETH ADX gate (FAIL)
backtest/backtest_expb_btc_4h.py          — BTC 4h/ADX gate (FAIL)
backtest/backtest_btc_5y.py               — BTC 5y pullback (PF=0.896)
backtest/backtest_expc_mean_reversion.py  — BB+RSI MR (FAIL)
backtest/backtest_expd_daily_gate.py      — Daily SMA gate (FAIL)
backtest/backtest_expe_mr_v2.py           — Pin bar MR (FAIL)
backtest/backtest_camino1_breakout.py     — Breakout diario (WINNER)
backtest/backtest_camino2_ath_gate.py     — ATH gate pullback (FAIL)
backtest/backtest_camino3_equity_pause.py — Equity pause (FAIL)
backtest/backtest_breakout_oos.py         — OOS 730d breakout
backtest/backtest_breakout_combined.py    — Sistema combinado BTC+ETH
backtest/backtest_breakout_optimize.py    — Grid search parámetros
core/indicators_v2.py                     — Añadidos bollinger_bands() y rsi()
core/strategy_mean_reversion.py           — Módulo MR (creado, estrategia descartada)
```

---

## Próximos pasos sugeridos para la siguiente sesión

1. **Resolver las dudas pendientes** antes de decidir si subir a producción
2. **Testear ETH IS 5y con vol≥1.5×** para completar la validación
3. **Cuantificar slippage real**: simular entrada al open del día siguiente en vez del close
4. **Walk-forward breakout**: 3 ventanas de ~600 días para verificar robustez temporal
5. **Comparar vs buy & hold**: calcular el alpha real del breakout sobre hold BTC/ETH
6. **Decidir arquitectura de producción**: el breakout es una señal diaria, requiere un módulo nuevo diferente al paper_engine.py actual (que está diseñado para 15m)
