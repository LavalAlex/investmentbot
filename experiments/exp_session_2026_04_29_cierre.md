# Sesión 2026-04-29 — Cierre y próximos pasos

---

## Lo que se hizo hoy

### Task 006 — COMBINED (DYN-B + TIME-B) ✅ APROBADO

DYN-B (sizing dinámico) y TIME-B (filtro horario) son ortogonales: sus efectos se
acumulan. Backtest 730d con fees:

| | BTC PF | ETH PF | BTC MaxDD | ETH MaxDD | BTC Sharpe |
|--|--------|--------|-----------|-----------|------------|
| BASE (EXP019) | 1.344 | 1.318 | 7.01% | 13.38% | 1.23 |
| COMBINED | **1.787** | **1.482** | **6.69%** | **8.17%** | **1.99** |

Walk-forward: 4/4 ventanas ✅. W3 Recovery 2025 (ventana crítica): 1.034 → 1.397.

### Task 007 — ETH-SHORT-C ✅ APROBADO

Diagnóstico empírico: ETH shorts con vol < 0.8× tienen PF 0.977 (trampas de liquidez).
Variante ganadora: vol ≥ 1.0× mean(50 velas). ETH PF 1.482 → 1.568, MaxDD 8.17% → 7.05%.

### Deploy-004 — Implementado y mergeado ✅

Tres filtros añadidos a `paper_monitor.py`:
- TIME-B: skip 00–07 UTC y 21–24 UTC
- DYN-B: sizing 0.6–1.2× por ATR ratio (1h)
- ETH-SHORT-C: ETH shorts requieren vol ≥ 1.0× mean50 (15m)

Cambios de infraestructura en `core/strategy_pullback.py`:
- `prepare_1h()`: añade `atr14`, `atr_ratio`
- `prepare_15m()`: añade `vol_mean50`
- `align_1h_to_15m()`: expone `atr_ratio` en el df alineado

PR mergeado a master. Sistema live en Cloud Run europe-west1.

---

## Sistema live actual (post deploy-004)

| Asset | PF backtest | MaxDD | Sharpe | Filtros |
|-------|-------------|-------|--------|---------|
| BTC/USDT | 1.787 (730d) | 6.69% | 1.99 | SLOPE_CAP + TIME-B + DYN-B |
| ETH/USDT | 1.568 (730d) | 7.05% | — | SLOPE_CAP + TIME-B + DYN-B + ETH-SHORT-C |

---

## Decisión estratégica: próxima fase

No seguir optimizando el backtest — el sistema tiene 7 filtros activos y tiene
PF > 1.7 en ambos assets. El riesgo de overfitting supera el beneficio marginal
de más filtros.

**Siguiente fase:** conectar a Binance real ($100–500) + notificaciones WhatsApp.

### Sobre notificaciones: WhatsApp vía Twilio, módulo reutilizable

Decisión de arquitectura: `core/notifier.py` (módulo, no API REST).
- Una API REST añade infraestructura innecesaria para uso interno
- El módulo es igualmente reutilizable en otros proyectos: solo se importa
- Si en el futuro se necesita como servicio externo, wrappear en FastAPI es trivial

### Sobre Binance real: hay que verificar los mínimos primero

Con $100 y 1% risk = $1 por trade. Los futuros de BTC tienen qty mínima de 0.001 BTC
(~$85 de notional). Task 009 verifica los límites exactos antes de construir el motor.

---

## Próximas tasks (Fase 3)

| # | Task | Prioridad | Estado |
|---|------|-----------|--------|
| 008 | WhatsApp notifier (Twilio) — `core/notifier.py` | 1 | ⬜ PENDIENTE |
| 009 | Análisis mínimos Binance — capital mínimo y modalidad | 2 | ⬜ PENDIENTE |
| 010 | `core/live_engine.py` — motor de órdenes reales | 3 | ⬜ PENDIENTE |
| 011 | Flag `--live` en paper_monitor.py | 4 | ⬜ PENDIENTE |

**Orden:** 008 primero (independiente, no bloquea nada) → 009 → 010 → 011.

**Criterio de go-live:** 008 + 009 + 010 completas + 48h en Binance testnet sin errores.

---

## Para empezar la próxima sesión

1. Crear cuenta Twilio y activar WhatsApp Sandbox
2. Añadir a `.env`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `TWILIO_WHATSAPP_TO`
3. `pip install twilio` y añadir a `requirements.txt`
4. Crear `core/notifier.py` según spec de task_008
5. Integrar en `paper_monitor.py`

---

## Archivos creados hoy

```
backtest/
  backtest_task006.py              ✅ COMBINED
  backtrack_task007.py             ✅ ETH-SHORT-C

core/
  strategy_pullback.py             MODIFICADO (atr_ratio, vol_mean50)

paper_monitor.py                   MODIFICADO (TIME-B, DYN-B, ETH-SHORT-C)

tasks/
  task_006_combined_dynb_timeb.md  → ✅ APROBADO
  task_007_volume_eth_shorts.md    → ✅ APROBADO
  task_008_whatsapp_notifier.md    ⬜ PENDIENTE
  task_009_binance_minimums.md     ⬜ PENDIENTE
  task_010_live_engine.md          ⬜ PENDIENTE
  task_011_live_mode.md            ⬜ PENDIENTE
  README.md                        ACTUALIZADO

experiments/
  exp_session_2026_04_29_tasks_006_007.md
  exp_session_2026_04_29_cierre.md  ← este archivo
```
