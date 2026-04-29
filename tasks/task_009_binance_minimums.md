# Task 009 — Análisis de mínimos Binance y setup de trading real

**Prioridad:** 2 (antes de Task 010)
**Estado:** ⬜ PENDIENTE
**Archivo:** `tasks/task_009_binance_analysis.md` (este doc + output del análisis)
**Depende de:** nada (investigación, no código)

---

## Objetivo

Antes de escribir un motor de órdenes reales, entender exactamente qué permite
Binance con el capital disponible ($100–$500). Evitar construir algo que no funcione
por restricciones de tamaño mínimo.

---

## Preguntas a responder

### 1. Futuros USDM (lo que usa el backtest)

| Asset | Precio aprox | Min qty | Min notional | Riesgo 1% con $100 | Qty resultante | ¿Viable? |
|-------|-------------|---------|--------------|---------------------|----------------|----------|
| BTCUSDT | ~$85,000 | 0.001 BTC | $5 | $1 | 0.0000118 BTC | ❌ muy bajo |
| ETHUSDT | ~$2,000 | 0.01 ETH | $5 | $1 | 0.0005 ETH | ❌ muy bajo |

→ Con $100 y 1% risk, **futuros no viables** salvo que se use 5–10% risk por trade
(fuera del backtest validado).

### 2. Futuros con capital mínimo real

¿Cuánto capital mínimo se necesita para que 1% risk = qty mínima?
- BTC futures min qty 0.001 BTC → necesita risk_usd = 0.001 × $85k × SL_pct
  Con SL 0.30%: risk_usd = $0.001 × 85,000 × 0.003 = $0.255 → capital mínimo $25.5
  PERO: min notional es $5, así que la posición mínima es $5 / $85k = 0.000059 BTC
  → el mínimo binance es el binding constraint, no el 1% risk

Revisar los filtros reales de Binance: `exchange.load_markets()['BTC/USDT:USDT']['limits']`

### 3. Alternativa: spot con OCO orders

En spot, una orden OCO (One-Cancels-Other) combina limit + stop-limit.
- Ventaja: sin funding rates, más simple
- Desventaja: no se puede hacer short en spot fácilmente (requiere margin)
- ¿El SL/TP del backtest es equivalente a una OCO en spot?

### 4. Palanca (leverage)

En futuros, usar 2×–3× leverage permite que $100 tenga el poder de $200–$300.
Riesgo: el drawdown también se amplifica × leverage.
Con DYN-B scale 0.6–1.2, el sizing ya tiene cierta variabilidad.

---

## Script de diagnóstico a correr

```python
# Correr con: python tasks/check_binance_limits.py
import ccxt, os
from dotenv import load_dotenv
load_dotenv()

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET'),
    'options': {'defaultType': 'future'},
})
exchange.load_markets()

for symbol in ['BTC/USDT:USDT', 'ETH/USDT:USDT']:
    m = exchange.markets[symbol]
    print(f"\n{symbol}")
    print(f"  min qty:      {m['limits']['amount']['min']}")
    print(f"  min notional: {m['limits']['cost']['min']}")
    print(f"  qty step:     {m['precision']['amount']}")
    print(f"  price step:   {m['precision']['price']}")
```

---

## Decisión esperada al final de esta task

Una de estas tres opciones:

**A)** Futuros ETH (precio más bajo, más accesible con $100–200)
→ Solo ETH en vivo, BTC cuando haya más capital

**B)** Futuros BTC + ETH con leverage 2×
→ Efectivamente $200 de poder con $100. Riesgo de DD amplificado.

**C)** Spot OCO para ambos, sin shorts en BTC (longs only — igual que el backtest de BTC)
→ Más simple, sin funding, pero sin short en ETH

La decisión guía el diseño de `core/live_engine.py` (Task 010).

---

## Criterio de cierre

Documento con: límites reales de Binance por asset, capital mínimo recomendado,
y decisión justificada sobre modalidad (futuros vs spot, assets, leverage).
