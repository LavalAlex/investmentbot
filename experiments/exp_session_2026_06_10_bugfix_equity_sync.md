# Sesión 2026-06-10 — Bugfix post-deploy: equity sincronizado desde Binance

## Problema detectado

Después del deploy 005 (V3 Daily Breakout), los logs mostraban:

```
Equity       : 10000.00 USD
Return       : +0.00%
```

El equity mostraba el valor hardcodeado `INITIAL_CAPITAL = 10_000.0` de `core/paper_engine.py`
en lugar del balance real USDT de Binance.

---

## Causa raíz

Los state files (`btc_breakout_state.json` / `eth_breakout_state.json`) se inicializan con
`equity: 10000.0` cuando no existen en GCS. El motor de paper trading nunca sincronizaba
el equity con el balance real de Binance.

---

## Fix implementado

### `core/paper_engine.py`
- `_load()`: agrega `initial_equity` al state si no existe (backward-compatible con states existentes)
- `init_equity(amount)`: nuevo método — actualiza `equity` e `initial_equity` en el state solo si está en estado virginal (sin trades, sin posiciones abieras)
- `print_summary()`: usa `state['initial_equity']` en lugar de `INITIAL_CAPITAL` para calcular Return %
- `reset()`: incluye `initial_equity` en el estado reseteado

### `paper_engine_breakout.py`
- Import: `create_futures_exchange` (en lugar de `create_exchange` — en Cloud Run solo hay credenciales de Futures, no Spot)
- `_sync_equity_from_binance(engines, loggers)`: nueva función pública — en el startup, si no hay trades ni posiciones, fetchea el balance USDT libre de Binance Futures y llama `engine.init_equity()` en cada engine. Timeout de 10s para evitar bloqueos. Non-fatal: si falla, logea y continúa.

### `api/main.py`
- Import `_sync_equity_from_binance` desde `paper_engine_breakout`
- En `_run_monitor_inner()`, llama `_sync_equity_from_binance(engines, loggers)` inmediatamente después de crear los engines

---

## Deploy history

| Revisión | Qué cambió | Resultado |
|----------|-----------|-----------|
| `00035-v2g` | Fix initial (spot exchange) | ❌ spot exchange sin credenciales → thread bloqueado |
| `00036-tcw` | Fix correcto en api/main.py | ❌ mismo problema — spot exchange sigue colgando |
| `00037-ffd` | Cambio a futures exchange | ❌ futures sin timeout → seguía colgando |
| `00038-j4v` | Timeout 10s en fetch_balance | ✅ funcionó |

## Error cometido

La primera versión usaba `create_exchange()` (Binance Spot). Cloud Run solo tiene configurado
`BINANCE_API_KEY` + `binance_private.pem` (Ed25519 para Futures). El spot exchange intenta
autenticarse con `BINANCE_SECRET` que está vacío → la request queda zombie sin timeout.

La segunda versión usaba `create_futures_exchange()` correcto pero sin timeout → también
colgaba si el endpoint no respondía en tiempo.

La versión final agrega `auth_exchange.timeout = 10000` (10 segundos) antes del `fetch_balance()`.

---

## Resultado final

```
[MONITOR] Equity      : 143.94 USD
Equity       : 143.94 USD
Return       : +0.00%
```

Balance USDT libre en Binance Futures: **$143.94**. El sistema ahora trackea P&L sobre
el capital real, no sobre un valor ficticio.

---

## Archivos modificados

```
core/paper_engine.py         — init_equity(), initial_equity en state, print_summary fix
paper_engine_breakout.py     — _sync_equity_from_binance(), timeout, futures exchange
api/main.py                  — llamada a _sync_equity_from_binance() en startup
deploy/deploy_006_20260610.md — registro del deploy
```
