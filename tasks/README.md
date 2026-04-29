# Tasks — Mejoras al Sistema V2

**Sistema base actual (deploy-004, live desde 2026-04-29):**

| Asset | PF 730d | MaxDD | Trades | Win rate | Filtros activos |
|-------|---------|-------|--------|----------|-----------------|
| BTC   | 1.787   | 6.69% | 71     | 54.9%    | SLOPE_CAP + TIME-B + DYN-B |
| ETH   | 1.568   | 7.05% | 69     | 47.8%    | SLOPE_CAP + TIME-B + DYN-B + ETH-SHORT-C |

Walk-forward combinado BTC+ETH: PF > 1.0 en las 4 ventanas de 182d ✅

**Metodología para todas las tasks:**
1. Crear `backtest/backtest_taskNNN.py` basado en EXP019 (SLOPE_CAP activo)
2. Correr sobre 730d con fees (0.05%/lado), BTC y ETH
3. Comparar contra baseline EXP019
4. Si pasa criterios → walk-forward 4×182d (mismo que EXP021)
5. Decidir KEEP / REVERT / ITERAR

**Reglas que no cambian entre tasks:**
- Fees: 0.05%/lado (round-trip 0.10%)
- Risk: 1% equity por trade
- SL mínimo: BTC ≥0.30%, ETH ≥0.50%
- Datos: 730d completos
- SLOPE_CAP = 0.20% (siempre activo — base del sistema V2)

---

## Índice de Tasks

| # | Task | Prioridad | Estado | Impacto esperado |
|---|------|-----------|--------|-----------------|
| 001 | [Trailing Stop](task_001_trailing_stop.md) | 1 — Alta | ❌ REVERT | Alto |
| 002 | [Dynamic Position Sizing](task_002_dynamic_sizing.md) | 2 — Alta | ✅ KEEP (DYN-B) | Medio-Alto |
| 003 | [Volume Filter en entrada](task_003_volume_filter.md) | 3 — Media | 🔄 ITERAR | Medio |
| 004 | [Time-of-Day Filter](task_004_time_filter.md) | 4 — Media | ✅ KEEP (TIME-A/B) | Alto |
| 005 | [Tercer Activo](task_005_third_asset.md) | 5 — Baja | ❌ REVERT (SOL) | Medio |

| 006 | [Combinado DYN-B + TIME-B](task_006_combined_dynb_timeb.md) | — | ✅ KEEP (COMBINED) | Alto |
| 007 | [Volume ETH shorts only](task_007_volume_eth_shorts.md) | — | ✅ KEEP (ETH-SHORT-C) | Medio |

---

## Fase 3 — Live trading + Notificaciones

| # | Task | Prioridad | Estado | Descripción |
|---|------|-----------|--------|-------------|
| 008 | [WhatsApp Notifier](task_008_whatsapp_notifier.md) | 1 | ⬜ PENDIENTE | Twilio WhatsApp en trades open/close |
| 009 | [Análisis mínimos Binance](task_009_binance_minimums.md) | 2 | ⬜ PENDIENTE | Verificar viabilidad con $100–500 |
| 010 | [Live Engine](task_010_live_engine.md) | 3 | ⬜ PENDIENTE | `core/live_engine.py` — órdenes reales |
| 011 | [Modo live `--live`](task_011_live_mode.md) | 4 | ⬜ PENDIENTE | Flag en paper_monitor.py |

**Orden de ejecución Fase 3:** 008 (independiente, hacer primero) → 009 (investigación) → 010 → 011

**Criterio de go-live:** Tasks 008 + 009 + 010 completas + testnet 48h OK.

---

## Estados posibles

| Estado | Significado |
|--------|-------------|
| ⬜ PENDIENTE | No iniciada |
| 🟡 EN CURSO | Backtest corriendo o en análisis |
| ✅ KEEP | Mejora validada — integrar al sistema |
| ❌ REVERT | No mejora o empeora — descartar |
| 🔄 ITERAR | Resultados mixtos — probar variante |
