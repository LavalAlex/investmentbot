# Task 010 — Motor de órdenes reales (`core/live_engine.py`)

**Prioridad:** 3
**Estado:** ⬜ PENDIENTE
**Archivo:** `core/live_engine.py`
**Depende de:** Task 009 (necesitamos saber si futuros o spot antes de diseñar)

---

## Objetivo

Crear `core/live_engine.py` como reemplazo de `PaperEngine` para ejecución real.
Misma interfaz que `PaperEngine` para que `paper_monitor.py` pueda switchear con
un flag `--live` sin reescribir la lógica de scan.

---

## Diferencias clave vs PaperEngine

| Aspecto | PaperEngine | LiveEngine |
|---------|-------------|------------|
| Apertura | registra en memoria | orden MARKET en Binance |
| SL/TP | comprueba cada vela | órdenes pendientes en Binance (OCO o SL+TP) |
| Estado | btc_state.json local | estado local + verificación en Binance |
| Circuit breaker | solo en código | igual, pero cancela órdenes pendientes |
| Equity | simulado | saldo real USDT de la cuenta |

---

## Diseño de la interfaz (igual que PaperEngine)

```python
class LiveEngine:
    def __init__(self, exchange, asset, state_file, leverage=1):
        ...

    def has_position(self, asset) -> bool:
        """Verifica en Binance si hay posición abierta, no solo en estado local."""

    def open_position(self, asset, direction, entry, sl, tp, qty, ts, risk_usd):
        """
        1. Redondear qty al step size de Binance
        2. Enviar orden MARKET
        3. Confirmar fill (precio real puede diferir del entry simulado)
        4. Colocar orden SL (stop-market) + orden TP (limit)
        5. Guardar estado en state_file
        """

    def check_and_close(self, asset, row):
        """
        Verificar si alguna orden pendiente (SL/TP) fue ejecutada en Binance.
        Si sí: registrar el trade cerrado, limpiar estado.
        El cierre real ya lo hizo Binance — aquí solo lo detectamos.
        """

    @property
    def equity(self) -> float:
        """Saldo USDT de la cuenta (llamada a Binance)."""
```

---

## Gestión de órdenes SL/TP en Binance

### Opción A — Futuros USDM

```
Entry: MARKET order
SL:    stop_market order (reduceOnly=True)
TP:    limit order (reduceOnly=True)
```

Las dos órdenes coexisten. Cuando una se ejecuta, hay que cancelar la otra.
Problema: Binance puede ejecutar ambas si hay un spike. Verificar con `fetch_orders()`.

### Opción B — Spot con OCO

```
Entry: MARKET order
SL+TP: OCO order (One-Cancels-Other) — Binance maneja la cancelación
```

Más seguro, pero solo para longs. ETH shorts no disponibles en spot básico.

---

## Manejo de errores críticos

```python
try:
    order = exchange.create_order(...)
except ccxt.InsufficientFunds:
    logger.error("LIVE: fondos insuficientes — trade cancelado")
    notify_whatsapp("⚠️ FONDOS INSUFICIENTES — trade no abierto")
    return
except ccxt.NetworkError:
    logger.error("LIVE: error de red — reintentando 1 vez")
    time.sleep(2)
    # retry once
except Exception as e:
    logger.error(f"LIVE: error inesperado: {e}")
    notify_whatsapp(f"⚠️ ERROR EN ORDEN: {e}")
    return
```

**Principio:** si la orden de entry falla, NO colocar SL/TP.
Si entry OK pero SL/TP falla: notificar URGENTE (posición sin protección).

---

## Qty rounding (crítico)

```python
def round_qty(exchange, symbol, qty):
    market = exchange.market(symbol)
    step   = market['precision']['amount']
    # Truncar (no redondear) para no sobrepasar el riesgo
    return exchange.amount_to_precision(symbol, qty, rounding_mode='TRUNCATE')
```

---

## Criterios de éxito

- Orden de entry se ejecuta y confirma fill en Binance
- SL y TP quedan como órdenes pendientes visibles en la cuenta
- Si la conexión cae y vuelve, el estado se recupera de Binance (no solo del JSON local)
- El circuit breaker cancela órdenes pendientes antes de pausar
- No hay posiciones zombie (abiertas en Binance pero no en el state local)

---

## Testing antes de go-live

1. Testnet de Binance Futures (`testnet.binancefuture.com`) — API separada
2. Correr `paper_monitor.py --live` con el testnet durante 48h
3. Verificar que los estados locales y de Binance están sincronizados
4. Simular un crash del proceso y verificar recuperación
