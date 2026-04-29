# Task 008 — WhatsApp Notifier (Twilio)

**Prioridad:** 1 (próxima sesión)
**Estado:** ⬜ PENDIENTE
**Archivo:** `core/notifier.py`
**Depende de:** nada (independiente)

---

## Objetivo

Crear un módulo de notificaciones por WhatsApp que avise cuando se abre o cierra
un trade en el paper monitor (y futuro live). El módulo debe ser reutilizable en
otros proyectos — interfaz limpia, sin dependencias del trading bot.

**Decisión de arquitectura:** módulo `core/notifier.py`, NO una API REST.
Razón: una API añade infraestructura (FastAPI, deploy, auth) innecesaria. Un módulo
Python limpio es igualmente reutilizable — se copia o se importa. Si en el futuro
se necesita como servicio, wrappear el módulo en FastAPI es trivial.

---

## Setup Twilio

1. Crear cuenta en twilio.com (free trial incluye $15 de crédito)
2. Activar WhatsApp Sandbox en Twilio Console → Messaging → Try it out → WhatsApp
3. El número de sandbox es `+1 415 523 8886` — el usuario envía "join <código>" para activarlo
4. Guardar en `.env`:
   ```
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
   TWILIO_WHATSAPP_TO=whatsapp:+34XXXXXXXXX   # número del usuario con código país
   ```

---

## Implementación — `core/notifier.py`

```python
"""
Notification module — WhatsApp via Twilio.
Reusable: no trading-bot dependencies, pure send interface.
"""

import os
from twilio.rest import Client

def send_whatsapp(message: str) -> bool:
    """Send a WhatsApp message. Returns True if sent, False on error."""
    ...

def notify_trade_open(asset, direction, entry, sl, tp, risk_usd, scale) -> bool:
    """Pre-formatted message for trade open."""
    ...

def notify_trade_close(asset, direction, entry, exit_price, reason, pnl, equity) -> bool:
    """Pre-formatted message for trade close."""
    ...
```

### Formato de mensajes

**Trade abierto:**
```
🟢 TRADE ABIERTO
BTC/USDT • LONG
Entrada: $84,250
SL: $83,500  TP: $85,750
Riesgo: $8.50 (scale 0.85×)
```

**Trade cerrado — TP:**
```
✅ TP ALCANZADO
BTC/USDT • LONG
Entrada: $84,250 → Salida: $85,750
PnL: +$16.80
Equity: $1,016.80
```

**Trade cerrado — SL:**
```
🔴 SL TOCADO
BTC/USDT • LONG
Entrada: $84,250 → Salida: $83,500
PnL: -$8.50
Equity: $991.50
```

---

## Integración en `paper_monitor.py`

Añadir después de `log_open()`:
```python
from core.notifier import notify_trade_open, notify_trade_close
notify_trade_open(asset, direction, entry, sl, tp, risk_usd, dyn_scale)
```

Añadir después de `log_close()`:
```python
notify_trade_close(asset, direction, trade['entry'], trade['exit'],
                   trade['reason'], trade['pnl'], engine.equity)
```

Hacer las notificaciones **no bloqueantes**: si Twilio falla, solo loggear el error —
no interrumpir el scan.

---

## Dependencias

```bash
pip install twilio
```

Añadir a `requirements.txt`.

---

## Test

```python
# Test manual antes de integrar:
python -c "from core.notifier import send_whatsapp; send_whatsapp('test desde investmentbot')"
```

---

## Criterios de éxito

- Mensaje llega al WhatsApp en < 5 segundos
- Si Twilio falla (red, credenciales), el monitor sigue corriendo sin crash
- El módulo funciona importado desde fuera del repo (sin dependencias del bot)

---

## Notas para reutilización en otros proyectos

El módulo solo necesita las 4 variables de entorno de Twilio. Para usarlo en otro
proyecto: copiar `core/notifier.py` + añadir las vars al `.env`. La función
`send_whatsapp(message: str)` es el único entry point que otros proyectos necesitan.
