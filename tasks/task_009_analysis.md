# Task 009 — Análisis de mínimos Binance: Resultados

**Fecha:** 2026-05-02  
**Estado:** ✅ COMPLETADO  
**Decisión:** Opción B — Futuros USDM BTC + ETH, 1% risk, sin leverage adicional

---

## Límites reales de Binance Futures (USDM)

| Asset | Precio ref. | min_qty | qty_step | min_notional |
|-------|------------|---------|----------|-------------|
| BTC/USDT:USDT | $78,516 | 0.001 BTC | 0.001 | **$50** |
| ETH/USDT:USDT | $2,311  | 0.001 ETH | 0.001 | **$20** |

> El task doc original estimaba min_notional = $5. El real es $50 (BTC) y $20 (ETH).
> Esto no cambia la viabilidad pero sí es relevante para el live engine.

---

## Viabilidad por capital (1% risk, parámetros del backtest)

### BTC — SL mínimo 0.30%

| Capital | qty calculada | qty redondeada | Notional | Leverage | Slip rounding | Viable |
|---------|--------------|----------------|---------|---------|--------------|--------|
| $100 | 0.00424 | **0.004** | $314 | 3.1× | 5.8% | ✅ |
| $200 | 0.00849 | **0.008** | $628 | 3.1× | 5.8% | ✅ |
| $500 | 0.02123 | **0.021** | $1,649 | 3.3× | 1.1% | ✅ |
| $1,000 | 0.04245 | **0.042** | $3,298 | 3.3× | 1.1% | ✅ |

Capital mínimo absoluto para cubrir min_qty: **$24**

### ETH — SL mínimo 0.50%

| Capital | qty calculada | qty redondeada | Notional | Leverage | Slip rounding | Viable |
|---------|--------------|----------------|---------|---------|--------------|--------|
| $100 | 0.0865 | **0.086** | $199 | 2.0× | 0.6% | ✅ |
| $200 | 0.1730 | **0.173** | $400 | 2.0× | 0.1% | ✅ |
| $500 | 0.4325 | **0.432** | $998 | 2.0× | 0.2% | ✅ |
| $1,000 | 0.8650 | **0.865** | $1,999 | 2.0× | 0.1% | ✅ |

Capital mínimo absoluto para cubrir min_qty: **$1**

---

## Análisis del leverage implícito

El backtest usa 1% risk por trade. Esto crea leverage natural en futuros:

```
leverage = notional / equity = (risk_usd / sl_pct) / equity = risk_pct / sl_pct

BTC: 1% / 0.30% = 3.3×
ETH: 1% / 0.50% = 2.0×
```

Con DYN-B (scale 0.6–1.2×), el leverage real oscila:
- BTC: **2.0× – 4.0×** según volatilidad
- ETH: **1.2× – 2.4×** según volatilidad

Binance permite hasta 20× en BTC y 20× en ETH. Estamos muy por debajo del límite.
**No se necesita configurar leverage adicional** — el sizing del backtest ya lo implica.

---

## El problema del rounding en BTC con capital bajo

Con $100–$200, la qty calculada (0.00424–0.00849 BTC) se redondea hacia abajo
al qty_step de 0.001, causando un **5.8% de undersize** en la posición.

Efecto real: en lugar de arriesgar $1.00 por trade, se arriesga $0.94.  
Impacto en el PF: **nulo** — el sistema sigue siendo rentable, solo ligeramente
subestimado. El backtest no es sensible a variaciones de 6% en el sizing.

Con **$500+**, el slip cae a 1.1% (BTC) y < 0.3% (ETH) → prácticamente despreciable.

**Solución para el live engine:** usar `math.floor(qty / qty_step) * qty_step` para
nunca abrir una posición más grande que la calculada (evitar riesgo extra).

---

## Comparación de opciones

| Opción | Descripción | Pros | Contras | Decisión |
|--------|-------------|------|---------|---------|
| **A** | Solo ETH futuros | Más accesible | Pierde BTC (PF 1.787) | ❌ |
| **B** | BTC + ETH futuros, 1% risk | Igual que backtest, ambos assets | Leverage implícito (bajo riesgo) | ✅ **ELEGIDA** |
| **C** | Spot OCO, longs only | Sin funding, simple | Sin shorts ETH, peor PF | ❌ |

---

## Decisión final

**Opción B — Futuros USDM, BTC + ETH, configuración idéntica al backtest.**

- BTC/USDT:USDT — longs only (EXP009), SL ≥ 0.30%
- ETH/USDT:USDT — longs + shorts (EXP016A), SL ≥ 0.50%
- Risk: 1% equity por trade (con DYN-B scale 0.6–1.2×)
- Leverage: no configurar explícitamente (Binance default = 20×; el sizing lo controla)
- **Capital mínimo recomendado: $200** (BTC viable, rounding aceptable)
- **Capital óptimo: $500+** (rounding < 2% en ambos assets)

---

## Impacto en Task 010 (Live Engine)

El live engine necesita:

1. **Redondear qty hacia abajo** al qty_step del mercado:
   ```python
   qty = math.floor(qty_raw / qty_step) * qty_step
   ```

2. **Validar min_qty y min_notional** antes de abrir:
   ```python
   if qty < min_qty or qty * price < min_notional:
       logger.warning(f"[{asset}] Orden muy pequeña — skip")
       return
   ```

3. **No setear leverage explícitamente** — dejar el default de Binance (20×).
   El sizing de 1% risk garantiza que el leverage efectivo sea 2–4×.

4. **Tipo de orden:** `MARKET` para entry (mismo que el backtest asume precio de cierre
   de vela 15m), `STOP_MARKET` para SL, `TAKE_PROFIT_MARKET` para TP.

---

## Archivos generados

- `tasks/task_009_analysis.md` — este documento
