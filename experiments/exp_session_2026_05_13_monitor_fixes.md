# Sesión 2026-05-13 — Diagnóstico prod + fix monitor Binance + heartbeat 12h

## Contexto

Sesión de mantenimiento: el usuario reportó 2 días sin movimientos en producción y el
endpoint `/wsp` no enviando mensajes. Se investigó el estado del servicio, se identificaron
dos bugs y se deployaron los fixes.

---

## 1. Diagnóstico: 2 días sin scans (11–13 mayo)

### Causa raíz — `Data fetch failed` en modo paper local

`paper_monitor.py` y `api/main.py` usaban `create_exchange()` (con `apiKey` + `secret`)
para instanciar el exchange de Binance. CCXT firmaba las requests a endpoints públicos de
OHLCV (`/api/v3/klines`), y Binance las rechazaba con error `-1022`:
`"Signature for this request is not valid."` → `Data fetch failed` en cada scan.

**Por qué afectó al local pero no a prod**: producción corre en modo LIVE (`LIVE_TRADING=1`)
y usa `create_futures_exchange()` con Ed25519 private key — ese exchange funciona
correctamente. El bug solo se manifestaba en modo paper (local o si prod bajara a paper).

### Confirmación: sin señales perdidas

Replay completo de candles 15m del 11 al 13 de mayo (ventana 07–21 UTC):

| Asset | Señales | Razón principal de descarte |
|-------|---------|----------------------------|
| BTC/USDT | 0 | 110 candles: trend bajista (longs\_only), 32: trend débil |
| ETH/USDT | 0 | 82 candles: trend débil, 74: pullback de mala calidad |

El servicio no habría entrado ningún trade aunque hubiera estado funcionando.

---

## 2. Diagnóstico: `/wsp` no enviaba mensajes

### Causa raíz — Sandbox de Twilio expirado

Twilio WhatsApp Sandbox requiere que el **usuario** envíe "join \<code\>" al número
`+1 415 523 8886` desde su WhatsApp. Si no hay mensajes entrantes del usuario en 72h,
la sesión expira. El endpoint devuelve `{"sent": true}` (HTTP 200) incluso cuando el
mensaje no se entrega — falla silenciosa, igual que en el incidente del 2026-05-10.

Las credenciales Twilio en Cloud Run están correctamente configuradas (secrets en GCP
Secret Manager, env vars en el servicio). El problema es puramente de sandbox expiration.

**Solución a largo plazo recomendada**: Evolution API (ya construida en
`feature/evolution-api-integration`, pendiente de VPS para deploy).

---

## 3. Fixes implementados

### `core/exchange.py` — nueva función `create_public_exchange()`

```python
def create_public_exchange() -> ccxt.binance:
    """No-auth exchange para market data público. Evita signature errors en endpoints públicos."""
    return ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
```

### `paper_monitor.py`

```python
# Antes
exchange = create_exchange()

# Después
exchange = create_public_exchange()
```

### `api/main.py` — dos cambios

**Fix monitor exchange (paper mode)**:
```python
# Antes
exchange = create_futures_exchange() if LIVE_MODE else create_exchange()
ok, msg  = ping_exchange(create_exchange())

# Después
exchange = create_futures_exchange() if LIVE_MODE else create_public_exchange()
ok, msg  = ping_exchange(create_public_exchange())
```

**Heartbeat 24h → 12h**:
```python
# Antes
if time.time() - last_heartbeat >= 86400:

# Después
if time.time() - last_heartbeat >= 43200:
```

Reduce la ventana de sandbox expiration: si el bot manda mensajes cada 12h y el usuario
responde al menos uno en 72h, el sandbox se mantiene activo.

---

## 4. Estado de producción post-sesión

- **Monitor**: corriendo, scans activos, último scan verificado 19:48 UTC
- **Binance**: conectado, BTC ~$79,770
- **Equity real**: $139.07 USD (balance Binance Futures — sin cambios)
- **Posiciones abiertas**: ninguna (BTC y ETH)
- **Heartbeat**: ahora cada 12h (primer envío en startup)
- **Sandbox Twilio**: el usuario debe renovar manualmente enviando join code

---

## 5. Pendientes

- [ ] Renovar sandbox Twilio: enviar `join <code>` desde WhatsApp a `+1 415 523 8886`
- [ ] Evaluar deploy Evolution API a VPS (~$5-6/mes) para eliminar el problema de sandbox
- [ ] Arrancar EXP018 (clasificador ADX, rama v2) — próximo experimento del roadmap
