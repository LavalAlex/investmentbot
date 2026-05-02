# Sesión 2026-05-02 — Live Engine (Tasks 008-011)

## Objetivo
Completar Fase 3: WhatsApp notifier + Live Engine + modo `--live` + deploy a producción.

## Estado al inicio
- Tasks 008 (WhatsApp) y 009 (análisis Binance) ya completadas en sesión anterior
- `core/live_engine.py` recién creado, sin commitear
- Rama `task-010-live-engine` activa

---

## Lo que se hizo

### Task 010 — LiveEngine (`core/live_engine.py`)
Clase con misma interfaz que `PaperEngine` pero con ejecución real en Binance Futures USDM:
- `open_position`: orden MARKET + STOP_MARKET (SL, reduceOnly) + TAKE_PROFIT_MARKET (TP, reduceOnly)
- `check_and_close`: detecta cierre por SL/TP via `fetch_positions` + `fetch_order`, cancela orden huérfana
- `equity`: saldo USDT real desde Binance (no simulado)
- `has_position`: fuente de verdad es Binance, fallback a JSON local
- `_floor_qty`: `math.floor(qty / qty_step) * qty_step` — nunca sobrepasar el riesgo calculado
- Manejo de errores: si entry falla → abort; si SL falla → notifica (posición sin protección)
- Integra notifier para open/close via WhatsApp

### Task 011 — Flag `--live` en `paper_monitor.py`
- `--live`: usa `LiveEngine` + `create_futures_exchange`
- `--testnet`: usa testnet.binancefuture.com (solo con `--live`)
- State files separados: `btc_live.json` / `eth_live.json` (no mezcla con paper)
- `create_futures_exchange(testnet=False)` agregado a `core/exchange.py`
- Symbol mapping: `'BTC/USDT'` → `'BTC/USDT:USDT'` (formato CCXT Futures)

### `api/main.py` — Modo live en producción
- `LIVE_TRADING=1` env var switchea entre `PaperEngine` y `LiveEngine`
- State files: `btc_live_state.json` / `eth_live_state.json` cuando live
- Ping de conectividad sigue usando spot (no requiere Futures para health check)

### `deploy.sh` — Deploy con live trading
- Agrega `LIVE_TRADING=1` como env var
- Secrets de Twilio en Secret Manager: `twilio-account-sid` + `twilio-auth-token`
- Env vars: `TWILIO_WHATSAPP_FROM` + `TWILIO_WHATSAPP_TO`

### Infraestructura Twilio en GCP
- Secrets creados en Secret Manager: `twilio-account-sid`, `twilio-auth-token`
- IAM: `investmentbot-sa` tiene `roles/secretmanager.secretAccessor` en ambos secrets

---

## Validación local
```bash
# Verificar saldo Futures
./check_testnet.sh
# → USDT: free=20.0  total=20.0

# Scan en modo live (sin señal, conexión OK)
python paper_monitor.py --live
# → Equity (real): 20.00 USD / Trades: 0
```

---

## Decisiones clave

| Decisión | Motivo |
|----------|--------|
| State files separados (`_live.json`) | No mezclar historial paper con trades reales |
| Solo ETH opera con $20 | BTC min notional ~$100, ETH ~$20. Con $20 equity, BTC siempre SKIP |
| Twilio como secrets, números como env vars | SID/Token son credenciales; números no son sensibles |
| IP unrestricted en Binance testnet | IPv6 del ISP rechazada por Binance; testnet no tiene riesgo real |
| No usar testnet | Keys de testnet requieren cuenta separada; se validó con cuenta real ($20 Futures) |

---

## Capacidad del sistema con $20 Futures

| Asset | Min notional | ¿Opera? | Motivo |
|-------|-------------|---------|--------|
| ETH/USDT | $20 | ✅ | qty=0.01 ETH @ ~$2000, notional=$20 |
| BTC/USDT | $100 | ❌ | qty=0.001 BTC @ $60k = $60 < min_cost |

Retorno esperado (ETH únicamente, 1% risk, PF=1.568 histórico): ~0.67%/mes sobre el capital.
Para llegar a 12% anual: subir risk a 1.5% (un parámetro, después de 2-3 meses de validación).

---

## Commits de esta sesión

```
359e8c8 live: wire LiveEngine into api/main.py + add Twilio secrets to deploy
49fd848 live: separate state files for paper vs live, add check_testnet.sh
ce27c5e Merge task-010-live-engine: LiveEngine + --live flag (Tasks 010+011)
f826848 task-010/011: LiveEngine + --live flag in paper_monitor
```

---

## Estado de tasks Fase 3

| Task | Estado |
|------|--------|
| 008 WhatsApp Notifier | ✅ COMPLETADO |
| 009 Análisis mínimos Binance | ✅ COMPLETADO |
| 010 Live Engine | ✅ COMPLETADO |
| 011 Modo `--live` | ✅ COMPLETADO |

---

## Próximos pasos

1. **Deploy a producción**: `./deploy.sh` (código listo, pendiente ejecución)
2. **Validación live 2-3 meses**: confirmar que el sistema se comporta igual que el backtest
3. **Si validación OK**: subir `RISK_PCT` de 0.01 → 0.015 para llegar a ~12% anual
4. **Transferir más USDT a Futures** si se quiere que BTC también opere (mínimo $50)
5. **V3** (largo plazo): si se quiere superar 12%, requiere nuevos experimentos
