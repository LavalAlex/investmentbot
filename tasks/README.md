# Tasks — Mejoras al Sistema V2

**Sistema base:** Pullback continuation + SLOPE_CAP (EXP019) sobre BTC/USDT y ETH/USDT.  
**Resultados base (referencia para todas las comparaciones):**

| Asset | PF 730d | MaxDD | Trades | Win rate |
|-------|---------|-------|--------|----------|
| BTC   | 1.390   | 7.01% | 99     | 49.5%    |
| ETH   | 1.386   | 13.38%| 112    | 46.4%    |

Walk-forward combinado BTC+ETH: PF > 1.0 en las 4 ventanas de 182d.

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

| 006 | [Combinado DYN-B + TIME-B](task_006_combined_dynb_timeb.md) | 1 — Próxima sesión | ⬜ PENDIENTE | Alto |
| 007 | [Volume ETH shorts only](task_007_volume_eth_shorts.md) | 2 — Próxima sesión | ⬜ PENDIENTE | Medio |

**Orden de ejecución:** secuencial por prioridad. Cada task que pase se integra como nueva base
antes de testear la siguiente (mejoras acumulativas).

---

## Estados posibles

| Estado | Significado |
|--------|-------------|
| ⬜ PENDIENTE | No iniciada |
| 🟡 EN CURSO | Backtest corriendo o en análisis |
| ✅ KEEP | Mejora validada — integrar al sistema |
| ❌ REVERT | No mejora o empeora — descartar |
| 🔄 ITERAR | Resultados mixtos — probar variante |
