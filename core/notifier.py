"""
WhatsApp notifier via Twilio.

Reutilizable: sin dependencias del trading bot.
Solo necesita 4 variables de entorno:

    TWILIO_ACCOUNT_SID   = ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    TWILIO_AUTH_TOKEN    = xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    TWILIO_WHATSAPP_FROM = whatsapp:+14155238886
    TWILIO_WHATSAPP_TO   = whatsapp:+XXXXXXXXXXX

Si alguna variable falta, todas las funciones son no-op (no crashean).

Setup Twilio (una sola vez):
    1. twilio.com → free trial ($15 crédito)
    2. Console → Messaging → Try it out → WhatsApp Sandbox
    3. Enviar "join <código>" al +1 415 523 8886 desde el número destino
"""

import logging
import os

_logger = logging.getLogger('notifier')


def _client():
    """Return a Twilio client, or None if credentials are missing."""
    sid   = os.getenv('TWILIO_ACCOUNT_SID', '')
    token = os.getenv('TWILIO_AUTH_TOKEN', '')
    if not sid or not token:
        return None
    try:
        from twilio.rest import Client
        return Client(sid, token)
    except Exception as e:
        _logger.warning(f'[notifier] Twilio init failed: {e}')
        return None


def send_whatsapp(message: str) -> bool:
    """
    Send a WhatsApp message via Twilio.
    Returns True if sent, False on any error (never raises).
    """
    from_  = os.getenv('TWILIO_WHATSAPP_FROM', '')
    to_    = os.getenv('TWILIO_WHATSAPP_TO', '')
    client = _client()

    if not client or not from_ or not to_:
        _logger.debug('[notifier] Twilio not configured — skipping notification')
        return False

    try:
        client.messages.create(body=message, from_=from_, to=to_)
        return True
    except Exception as e:
        _logger.warning(f'[notifier] send_whatsapp failed: {e}')
        return False


def notify_trade_open(
    asset: str,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    risk_usd: float,
    scale: float = 1.0,
) -> bool:
    emoji = '🟢' if direction == 'long' else '🔴'
    side  = 'LONG' if direction == 'long' else 'SHORT'
    msg = (
        f"{emoji} TRADE ABIERTO\n"
        f"{asset} • {side}\n"
        f"Entrada: ${entry:,.2f}\n"
        f"SL: ${sl:,.2f}  TP: ${tp:,.2f}\n"
        f"Riesgo: ${risk_usd:.2f} (scale {scale:.2f}×)"
    )
    return send_whatsapp(msg)


def notify_trade_opened_live(
    asset: str,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    risk_usd: float,
    sl_ok: bool,
    tp_ok: bool,
    sl_error: str = '',
    tp_error: str = '',
    software_sltp: bool = False,
) -> bool:
    emoji = '🟢' if direction == 'long' else '🔴'
    side  = 'LONG' if direction == 'long' else 'SHORT'
    if software_sltp:
        sl_line = f"SL: ⚙️ ${sl:,.2f} (software)"
        tp_line = f"TP: ⚙️ ${tp:,.2f} (software)"
    else:
        sl_line = f"SL: ✅ ${sl:,.2f}" if sl_ok else f"SL: ❌ FALLÓ — {sl_error[:60]}"
        tp_line = f"TP: ✅ ${tp:,.2f}" if tp_ok else f"TP: ❌ FALLÓ — {tp_error[:60]}"
    msg = (
        f"{emoji} TRADE ABIERTO\n"
        f"{asset} • {side}\n"
        f"Entrada: ${entry:,.2f}\n"
        f"{sl_line}\n"
        f"{tp_line}\n"
        f"Riesgo: ${risk_usd:.2f}"
    )
    return send_whatsapp(msg)


def notify_daily_status(engines: dict) -> bool:
    # All engines share the same Binance account — fetch equity once
    first_engine = next(iter(engines.values()), None)
    account_equity = first_engine.equity if first_engine else 0.0

    lines = [f'📊 ESTADO DIARIO — InvestmentBot\nEquity: ${account_equity:,.2f}']

    for asset, engine in engines.items():
        pos    = engine.get_position(asset)
        trades = engine.state.get('trades', [])
        last3  = trades[-3:] if trades else []

        lines.append(f'\n─ {asset} ─')
        if pos:
            side = 'LONG' if pos['direction'] == 'long' else 'SHORT'
            lines.append(f'Posición: {side} @ ${pos["entry"]:,.2f}')
            lines.append(f'SL: ${pos["sl"]:,.2f}  TP: ${pos["tp"]:,.2f}')
        else:
            lines.append('Posición: ninguna')

        if last3:
            lines.append('Últimos trades:')
            for t in reversed(last3):
                sign = '+' if t['pnl'] >= 0 else ''
                lines.append(f'  {t["reason"]} {sign}${t["pnl"]:.2f}')

    return send_whatsapp('\n'.join(lines))


def notify_trade_close(
    asset: str,
    direction: str,
    entry: float,
    exit_price: float,
    reason: str,
    pnl: float,
    equity: float,
) -> bool:
    icons = {'TP': '✅', 'SL': '🔴', 'BE': '🟡'}
    labels = {'TP': 'TP ALCANZADO', 'SL': 'SL TOCADO', 'BE': 'BREAK-EVEN'}
    icon  = icons.get(reason, '⚪')
    label = labels.get(reason, reason)
    side  = 'LONG' if direction == 'long' else 'SHORT'
    sign  = '+' if pnl >= 0 else ''
    msg = (
        f"{icon} {label}\n"
        f"{asset} • {side}\n"
        f"Entrada: ${entry:,.2f} → Salida: ${exit_price:,.2f}\n"
        f"PnL: {sign}${pnl:.2f}\n"
        f"Equity: ${equity:,.2f}"
    )
    return send_whatsapp(msg)
