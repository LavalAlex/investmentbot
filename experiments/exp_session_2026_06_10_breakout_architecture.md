# Sesión 2026-06-10 — Validación completa y arquitectura del Breakout Diario

## Contexto de partida

La sesión anterior (2026-06-09) descubrió que el pullback no tiene edge robusto sobre 5 años
(PF=0.896) y encontró el Daily Breakout como estrategia ganadora. Esta sesión cierra la
validación y construye la arquitectura de producción.

---

## Experimentos realizados

### 1. ETH IS 5y con vol≥1.5× (backtest/backtest_breakout_eth5y.py)

Pendiente de la sesión anterior: ETH 5y only había sido testeado con vol≥1.0×.

**Resultado:**

| Config | T | WR | PF | MaxDD |
|--------|---|----|----|-------|
| ETH 10d vol≥1.5× | 38 | 47.4% | **1.711** | 5.1% ✅ |
| ETH 15d vol≥1.5× | 36 | 50.0% | **1.897** | 4.1% ✅ |
| ETH 20d vol≥1.5× | 34 | 44.1% | 1.500 | 5.1% ✅ |

**CONCLUSIÓN:** ETH tiene IS sólido con vol≥1.5×. La config 10d (validada en OOS) también
pasa IS. El filtro de volumen es el selector dominante del edge.

---

### 2. Test de slippage en entrada (backtest/backtest_breakout_slippage.py)

Pregunta: ¿hay slippage entre el cierre del día de señal y la entrada real?

**Resultado:** `next_open == baseline` en todos los casos (Δpf = 0.000).

**Por qué:** En crypto 24/7 no hay gap entre el close de la vela del día D y el open del
día D+1. Son el mismo precio — no hay sesión nocturna cerrada.

**CONCLUSIÓN:** No hay slippage de entrada en crypto diario. El backtest es realista.

El modelo `limit` (entrar al nivel de nd_high intraday) muestra PF 4-7× pero requiere
monitor intraday permanente — no aplica con la arquitectura actual.

---

### 3. Walk-forward 3 ventanas (backtest/backtest_breakout_wf.py)

Config fija: 10d vol≥1.5× ATR×1.5 RR=2 (sin re-optimizar por ventana).
5 años divididos en 3 segmentos de ~609 días.

**BTC — 3/3 ventanas:**

| Ventana | Período | T | PF |
|---------|---------|---|----|
| W1 | 2021-05 → 2023-01 | 10 | **1.937** ✅ |
| W2 | 2023-01 → 2024-09 | 19 | **1.736** ✅ |
| W3 | 2024-09 → 2026-05 | 13 | **1.615** ✅ |

**ETH — 3/3 ventanas:**

| Ventana | Período | T | PF |
|---------|---------|---|----|
| W1 | 2021-05 → 2023-01 | 10 | **2.879** ✅ |
| W2 | 2023-01 → 2024-09 | 14 | **1.065** ✅ (barely) |
| W3 | 2024-09 → 2026-05 | 13 | **1.640** ✅ |

**CONCLUSIÓN:** Edge consistente en las 6/6 ventanas. Punto débil: ETH W2 (PF=1.065) —
período fondo de bear + recovery con alta volatilidad sin dirección. Pasa el criterio pero
es el escenario más difícil para el breakout.

---

### 4. Alpha vs Buy & Hold (backtest/backtest_breakout_bnh.py)

Comparativa directa contra holdear el activo. Métrica clave: Calmar = retorno_anualizado / MaxDD.

| Asset/Período | Bk Return | BnH Return | Bk MaxDD | BnH MaxDD | Calmar Bk | Calmar BnH |
|---|---|---|---|---|---|---|
| BTC 5y | +18.1% | +82.3% | 4.0% | 76.6% | **0.835** | 0.165 |
| ETH 5y | +16.1% | -26.9% | 5.1% | 79.3% | **0.593** | -0.076 |
| BTC 730d | +4.7% | +28.5% | 3.0% | 49.5% | **0.751** | 0.265 |
| ETH 730d | +3.7% | -20.6% | 3.0% | 63.2% | **0.600** | -0.170 |

**CONCLUSIÓN:** El breakout gana en Calmar en todos los períodos (5x mejor en BTC 5y).
Pierde en retorno absoluto solo en BTC cuando el mercado tuvo un bull excepcional.
El sistema pasa el 73-78% del tiempo fuera del mercado.

---

### 5. Comparativa honesta: Pullback actual vs Breakout (730d)

| | BTC Pullback | BTC Breakout | ETH Pullback | ETH Breakout |
|---|---|---|---|---|
| Return 730d | +23.6% | +4.7% | -3.9% | +3.7% |
| Trades | 241 | 13 | 160 | 14 |
| MaxDD | 11.8% | **3.0%** | 20.4% | **3.0%** |
| Fees 730d | **$6,025** | $29 | **$2,143** | $21 |
| PF | 1.126 | **1.627** | 0.964 | **1.442** |

**Conclusión clave:** El pullback ganó más en 730d solo porque esos 730 días incluyen el
bull market BTC de 2024. El retorno está concentrado en 3 meses (Jul-Sep 2024: PF=6/3.9/3.9).
Sobre 5 años completos el pullback pierde (PF=0.896). El breakout es más robusto y paga
160× menos en fees.

---

## Arquitectura implementada

### `core/strategy_breakout.py`

Módulo de señal con 4 funciones públicas:

```python
prepare_daily(df_1h)              # resamplea 1h → diario, añade ATR14/vol20/nd_high
is_breakout_signal(row)           # close > nd_high AND vol ≥ 1.5× vol20
calculate_position(row, equity)   # devuelve entry/SL/TP/qty/risk_usd
get_latest_completed_day(daily)   # helper para live engine
```

Parámetros fijos (validados, no cambiar sin experimento):
- `N_DAYS = 10`, `VOL_RATIO = 1.5`, `ATR_MULT = 1.5`, `RR = 2.0`, `RISK_PCT = 0.01`

### `paper_engine_breakout.py`

Motor standalone que reemplaza `paper_monitor.py`:

```
Ciclo horario:
  Si posición abierta:
    → Procesa todas las velas 1h cerradas desde la apertura en orden
    → Cierra al primer SL o TP alcanzado
  Si sin posición:
    → Fetch 1440 velas 1h (60 días) → resamplea a diario
    → Evalúa señal en la última vela diaria completa
    → Dedup via state['last_daily_check'] = "YYYY-MM-DD"
    → Si señal: abre posición, notifica WhatsApp

State files: btc_breakout_state.json / eth_breakout_state.json
Loop: --loop con SCAN_INTERVAL=3600s (1h)
```

Reutiliza: `PaperEngine`, `notify_trade_open/close`, `log_open/close`, GCS sync.

---

## Resumen de validación completa

| Test | BTC | ETH | Resultado |
|------|-----|-----|-----------|
| IS 5 años | PF=1.735 | PF=1.711 | ✅ |
| OOS 730d | PF=1.627 | PF=1.442 | ✅ |
| Walk-forward 3v | 3/3 | 3/3 | ✅ |
| Slippage | Δpf=0 | Δpf=0 | ✅ (no issue) |
| Alpha vs BnH | Calmar 5× | Calmar >> BnH | ✅ |

---

## Estado al cerrar sesión

| Item | Estado |
|------|--------|
| `core/strategy_breakout.py` | ✅ Implementado y testado |
| `paper_engine_breakout.py` | ✅ Implementado, dry-run OK |
| Deploy a Cloud Run | ⬜ PENDIENTE |

## Pendiente para la siguiente sesión

1. **Decisión de deploy**: ¿corte limpio (reemplazar pullback) o período de solapamiento?
2. **Actualizar Dockerfile / Cloud Run** para usar `paper_engine_breakout.py --loop`
3. **Archivar `paper_monitor.py`** (no borrarlo, solo dejar de correrlo)
4. **Monitorear** primeras señales reales del breakout en producción

## Archivos creados esta sesión

```
backtest/backtest_breakout_eth5y.py     — ETH IS 5y vol≥1.5× grid ✅
backtest/backtest_breakout_slippage.py  — test de slippage entrada ✅
backtest/backtest_breakout_wf.py        — walk-forward 3 ventanas ✅
backtest/backtest_breakout_bnh.py       — comparativa vs buy & hold ✅
core/strategy_breakout.py               — módulo de señal (producción) ✅
paper_engine_breakout.py                — motor paper trading diario ✅
```
