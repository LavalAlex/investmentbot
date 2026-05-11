# Sesión 2026-05-10 — Incident postmortem + fixes de producción

## Contexto

Sesión de emergencia: el usuario descubrió por azar que había una posición BTC LONG abierta
en Binance Futures desde las 13:00 ART (16:00 UTC) sin notificación ni protección (sin SL/TP).

---

## 1. Root Cause del Incidente

### Cadena de fallas

```
MARKET BUY BTC ✅
    → SL STOP_MARKET ❌  Error -4120 (Ed25519 key no soportada en /fapi/v1/order)
        → TP skipped (solo se intenta si SL OK)
            → notify_trade_open() llamado → Twilio retorna 200 pero sandbox expirado (72h sin uso)
                → Usuario sin notificación, posición sin protección
```

### Error Binance -4120
`STOP_MARKET` y `TAKE_PROFIT_MARKET` no están soportados en el endpoint estándar
`/fapi/v1/order` para cuentas con Ed25519 API keys. Requieren el endpoint de Algo Orders:
- SL: `POST /fapi/v1/order/algo/market`
- TP: `POST /fapi/v1/order/algo/takeProfit`
- Cancelar: `DELETE /fapi/v1/order/algo`
- Listar: `GET /fapi/v1/order/algo/openOrders`

CCXT 4.4.70 no implementa estos endpoints como métodos nombrados.
Se usa `self._exchange.request(path, api, method, params)` directamente.
Las respuestas devuelven `strategyId` (no `id`) para tracking/cancelación.

### Twilio sandbox expirado
El sandbox de WhatsApp expira cada 72h si no hay actividad.
`send_whatsapp()` retorna `True` (HTTP 200) incluso cuando el mensaje no se entrega — falla silenciosa.
Fix: heartbeat cada 24h para mantener el sandbox activo.

---

## 2. Fixes implementados

### Commits en esta sesión

| Commit | Descripción |
|--------|-------------|
| `3cd0949` | fix: algo orders, WhatsApp heartbeat, live API endpoints |
| `14be50b` | fix: skip load_markets() if exchange already initialized |
| `bc23aab` | fix: notify_daily_status equity; add POST /wsp endpoint |
| `9c207e8` | perf: pre-load heavy modules at process start |

---

### `core/live_engine.py`

**Problema**: SL/TP usaban STOP_MARKET/TAKE_PROFIT_MARKET → error -4120 con Ed25519.

**Fix — Nuevos métodos**:
```python
_place_sl_algo(side, qty, stop_price)  # POST /fapi/v1/order/algo/market
_place_tp_algo(side, qty, stop_price)  # POST /fapi/v1/order/algo/takeProfit
_cancel_algo_order(strategy_id)        # DELETE /fapi/v1/order/algo
```

**Fix — `open_position`**:
- Usa `_place_sl_algo` / `_place_tp_algo` en lugar de `create_order(STOP_MARKET)`
- Trackea `sl_ok`, `sl_error`, `tp_ok`, `tp_error`
- Solo intenta TP si SL fue OK
- Llama `notify_trade_opened_live()` con estado de cada orden

**Fix — `check_and_close`**:
- Usa `fetch_my_trades(limit=10)` para detectar cierre (no `fetch_order`)
- Determina SL vs TP comparando precio de salida contra midpoint `(sl + tp) / 2`
- Cancela la orden algo huérfana (la que no se disparó)

**Fix — `__init__`**:
```python
# Antes: siempre llamaba load_markets(), segunda llamada bloqueaba indefinidamente
self._exchange.load_markets()

# Después: skip si ya cargado (cuando dos engines comparten el mismo exchange)
if not self._exchange.markets:
    self._exchange.load_markets()
```

---

### `core/notifier.py`

**Nuevas funciones**:

`notify_trade_opened_live(asset, direction, entry, sl, tp, risk_usd, sl_ok, tp_ok, sl_error, tp_error)`
- Reemplaza `notify_trade_open` para el live engine
- Muestra ✅ o ❌ con detalle de error para SL y TP

`notify_daily_status(engines: dict)`
- Heartbeat diario de estado de cuenta
- **Fix equity**: todos los engines comparten la misma cuenta Binance →
  obtener equity UNA SOLA VEZ del primer engine (no sumar por engine, que duplicaba el valor)
- Muestra: equity, posición abierta (si hay), últimos 3 trades por asset

---

### `api/main.py`

**Fix `STATE_FILES`** — sufijo en orden incorrecto:
```python
# Antes (incorrecto): genera btc_live_state.json
Path(f'btc{_state_suffix}_state.json')

# Después (correcto): genera btc_state_live.json — coincide con LiveEngine
Path(f'btc_state{_state_suffix}.json')
```

**Fix endpoints `/status` y `/trades`**:
- Antes: leían del disco (`_load_state()`) → equity 10000, datos stale
- Después: leen de `engine.state` + `engine.equity` (Binance real-time) cuando engines disponibles

**Fix `/health`**:
- Trades y posiciones también desde `engine.state` (no disco)

**Heartbeat WhatsApp**:
```python
last_heartbeat: float = 0.0  # fuerza envío en startup
# En el loop:
if time.time() - last_heartbeat >= 86400:
    notify_daily_status(engines)
    last_heartbeat = time.time()
```

**Nuevo endpoint `POST /wsp`**:
- Dispara el mensaje de estado WhatsApp manualmente

**Fix startup delay (~7-10 min → ~1-2 min)**:
- Los imports pesados (ccxt, pandas, paper_monitor, etc.) se hacían dentro del thread
- Movidos al nivel de módulo de `api/main.py`
- El thread los encuentra en `sys.modules` → arranque casi instantáneo

---

## 3. Bugs secundarios encontrados

### Monitor colgado post-deploy
Con el fix de algo orders, el monitor arrancó pero se colgó en "Creating LiveEngines..."
porque `load_markets()` se llamaba dos veces con el mismo exchange (BTC + ETH engine),
y la segunda llamada bloqueaba indefinidamente. Fix: guard `if not self._exchange.markets`.

### `/health` mostraba `connected: null` con monitor corriendo
Los logs del SCAN que se veían eran de la revisión ANTERIOR solapándose con el nuevo deploy.
La nueva revisión estaba en medio de la inicialización (7 min de imports en el thread).

---

## 4. Estado de producción post-sesión

- **Revisión activa**: `investmentbot-00024-rqr`
- **Equity real**: $139.07 USD (balance Binance Futures)
- **Posiciones abiertas**: ninguna (la BTC LONG fue cerrada manualmente por el usuario)
- **Logs**: reseteados — semana nueva, datos limpios
- **Monitor**: corriendo, scans cada 30s, SL/TP via Algo Orders API

---

## 5. Pendientes

- [ ] Deployar commits `bc23aab` y `9c207e8` (notify equity fix + startup perf)
- [ ] Verificar que el próximo WSP de heartbeat muestre equity correcto ($139.07, no $278.14)
- [ ] Considerar mover `last_heartbeat = 0.0` para que NO envíe en startup (solo en producción estable)
