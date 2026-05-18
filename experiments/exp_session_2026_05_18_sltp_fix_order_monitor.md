# Sesión 2026-05-18 — Fix SL/TP live engine + Order Monitor

## Contexto

El usuario reportó que al entrar una posición live, llegaba un WhatsApp avisando que
no se habían podido colocar las órdenes de SL y TP en Binance. El bot abría posiciones
desprotegidas. Se investigó la causa raíz, se corrigió el código y se añadió un sistema
de monitoreo en tiempo real como doble seguridad.

---

## 1. Diagnóstico: por qué fallaban SL y TP

### Causa raíz — Migración de Binance (9 dic 2025)

Binance migró todos los conditional orders (STOP_MARKET, TAKE_PROFIT_MARKET, STOP,
TAKE_PROFIT, TRAILING_STOP_MARKET) al **Algo Service** el 9 de diciembre de 2025.

El código de `live_engine.py` usaba tres endpoints que ya no existen o tienen
parámetros incorrectos:

| Operación | Endpoint anterior (roto) | Error |
|-----------|--------------------------|-------|
| Colocar SL | `POST /fapi/v1/order/algo/market` | 404 — no existe |
| Colocar TP | `POST /fapi/v1/order/algo/takeProfit` | 404 — no existe |
| Cancelar orden | `DELETE /fapi/v1/order/algo` + `strategyId` | 404 — no existe |
| Cancelar todas | `GET /fapi/v1/order/algo/openOrders` | 404 — no existe |
| Fallback standard | `POST /fapi/v1/order` con STOP_MARKET | `-4120` — deprecated |

El error `-4120` ("Order type not supported for this endpoint. Please use the Algo Order
API endpoints instead.") era la respuesta de Binance para cualquier orden condicional
en el endpoint estándar.

### Verificación del nuevo endpoint

API de Algo Orders (post-migración dic 2025):

```
POST   /fapi/v1/algoOrder        → crear orden condicional (algoType=CONDITIONAL)
DELETE /fapi/v1/algoOrder        → cancelar una orden (por algoId)
DELETE /fapi/v1/algoOpenOrders   → cancelar todas las algo del símbolo
GET    /fapi/v1/openAlgoOrders   → listar órdenes algo abiertas
```

Cambios de campos:
- Parámetro de precio: `stopPrice` → `triggerPrice`
- ID de respuesta: `strategyId` → `algoId`
- Nuevo parámetro obligatorio: `algoType: "CONDITIONAL"`

---

## 2. Fixes implementados

### Fix 1 — `core/live_engine.py`: endpoints corregidos (commit `d367675`)

```python
# ANTES (_place_sl_algo)
resp = self._exchange.request(
    'order/algo/market', 'fapiPrivate', 'POST', {
        'symbol': ..., 'side': ..., 'quantity': ...,
        'stopPrice': str(stop_price),           # parámetro incorrecto
        'reduceOnly': 'true', 'workingType': ...,
    }
)
return resp['strategyId']                       # campo incorrecto

# DESPUÉS
resp = self._exchange.request(
    'algoOrder', 'fapiPrivate', 'POST', {
        'algoType':     'CONDITIONAL',          # nuevo campo obligatorio
        'symbol': ..., 'side': ...,
        'type':         'STOP_MARKET',          # tipo explícito
        'quantity': ...,
        'triggerPrice': str(stop_price),        # parámetro correcto
        'reduceOnly': 'true', 'workingType': ...,
    }
)
return resp['algoId']                           # campo correcto
```

Mismo fix aplicado a `_place_tp_algo` (type=`TAKE_PROFIT_MARKET`),
`_cancel_algo_order` (`algoId` en lugar de `strategyId`),
y `_cancel_open_orders` (`DELETE /fapi/v1/algoOpenOrders`).

### Fix 2 — `core/live_engine.py`: software SL/TP como backup (commit `48be512`)

Añadido como capa adicional de protección. En `check_and_close`, antes de esperar
a que Binance informe el cierre, se compara el `high/low` del candle recibido contra
los niveles SL y TP. Si se cruzan → se ejecuta un `MARKET close` (reduceOnly=True).

```python
# Primero: chequeo software por candle high/low
if direction == 'short':
    if bar_high >= sl_price: reason = 'SL'
    elif bar_low <= tp_price: reason = 'TP'

if reason:
    fill = self._close_market(asset, pos, reason, target)
else:
    # Fallback: detectar cierre externo en Binance
    if self.has_position(asset): return None
    ...
```

### Fix 3 — `core/notifier.py`: notificación actualizada (commit `48be512`)

Cuando ambas órdenes Binance fallan pero el software SL/TP está activo, el WhatsApp
muestra `⚙️ $2130.00 (software)` en lugar de `❌ FALLÓ`.

---

## 3. Order Monitor — doble seguridad en tiempo real (commit `6129e85`)

### Problema adicional

El `check_and_close` corre cada 30 segundos sobre velas cerradas. Si el precio cruza
SL o TP dentro de una vela en curso, el cierre se demora hasta la siguiente vela.

### Solución: `core/order_monitor.py`

Nuevo thread independiente que corre cada N segundos (default 5s) y:

1. Obtiene el precio actual vía `exchange.fetch_ticker()`
2. Compara contra SL y TP de cada posición abierta
3. Si el precio cruzó el nivel → llama `check_and_close` con un bar sintético
   (`high = low = precio_actual`) para ejecutar MARKET close y registrar el trade
4. Reporta si las órdenes algo de Binance siguen activas

### Integración en `api/main.py`

- Thread `order-monitor` arranca automáticamente cuando `LIVE_MODE=1`
- Intervalo configurable vía env var `ORDER_MONITOR_INTERVAL` (default 5s)
- Nuevo endpoint `GET /orders`

### Endpoint `GET /orders` — ejemplo de respuesta

```json
{
  "monitor_interval_s": 5,
  "live_mode": true,
  "orders": [{
    "asset": "ETH/USDT",
    "direction": "short",
    "entry": 2108.28,
    "current_price": 2109.03,
    "sl": 2118.68,
    "tp": 2087.06,
    "qty": 0.01,
    "binance_sl_active": true,
    "binance_tp_active": true,
    "dist_sl_pct": 0.458,
    "dist_tp_pct": 1.042,
    "pnl_usd": -0.0075
  }]
}
```

### Arquitectura de protección resultante

| Capa | Frecuencia | Mecanismo |
|------|-----------|-----------|
| Binance algo orders | Instantáneo | STOP_MARKET + TAKE_PROFIT_MARKET en Binance |
| Order monitor | Cada 5s | Ticker vs SL/TP → MARKET close si cruza |
| Scanner principal | Cada 30s | check_and_close sobre vela cerrada |

---

## 4. Test en producción

Se abrió una posición short real de 0.01 ETH para verificar el flujo completo:

- Entry: $2108.28
- SL: $2118.68 (algoId=4000001340070237, STOP_MARKET, status=NEW ✅)
- TP: $2087.06 (algoId=4000001340070305, TAKE_PROFIT_MARKET, status=NEW ✅)

Ambas órdenes confirmadas activas en Binance via `GET /fapi/v1/openAlgoOrders`.
Posición en curso al cierre de sesión.

---

## 5. Estado post-sesión

- **Producción**: deployado con los 3 commits de esta sesión
- **Posición activa**: ETH/USDT SHORT 0.01 @ $2108.28 con SL/TP activos en Binance
- **Order monitor**: activo en Cloud Run (LIVE_MODE=1, interval=5s)

## 6. Pendientes

- [ ] Confirmar cierre correcto de la posición de test cuando toque SL o TP
- [ ] Evaluar `ORDER_MONITOR_INTERVAL=10` si el overhead de fetch_ticker es alto
- [ ] Arrancar EXP018 (clasificador ADX, rama v2) — próximo experimento del roadmap
