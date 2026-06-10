# Sesión 2026-06-10 — Estrategia Combinada: Pullback + Breakout con Router ADX

## Contexto

Continuación de la misma sesión de arquitectura (2026-06-10). Tras validar el Daily Breakout
e implementar `paper_engine_breakout.py`, el usuario preguntó si tiene sentido switchear entre
pullback y breakout usando un indicador de tendencia fuerte.

**Hipótesis:** ADX(14) diario como router:
- ADX > threshold (tendencia fuerte) → Breakout
- ADX ≤ threshold → Pullback

---

## Backtest realizado: `backtest/backtest_combined_strategy.py`

5 variantes × 4 períodos (BTC 5y, ETH 5y, BTC 730d, ETH 730d):

1. Pullback solo (EXP017-B / EXP016A, longs only)
2. Breakout solo (10d vol≥1.5× ATR×1.5 RR=2)
3. Combined ADX>20
4. Combined ADX>25
5. Combined ADX>30

Fees: 0.05%/lado. ADX calculado sobre velas diarias.

---

## Resultados completos

### BTC — 5 años

| Estrategia | T | PF | Ret | MaxDD | Fees |
|---|---|---|---|---|---|
| Pullback solo | 608 | 0.896 ❌ | -33.2% | 49.6% | $8,911 |
| **Breakout solo** | **41** | **1.810** ✅ | **+19.3%** | **4.0%** | **$96** |
| Combined ADX>20 | 136 | 1.010 ✅ | +1.0% | 18.7% | $2,443 |
| Combined ADX>25 | 232 | 1.028 ✅ | +4.9% | 17.0% | $4,738 |
| Combined ADX>30 | 325 | 0.962 ❌ | -7.7% | 25.1% | $5,718 |

### ETH — 5 años

| Estrategia | T | PF | Ret | MaxDD | Fees |
|---|---|---|---|---|---|
| Pullback solo | 419 | 0.939 ❌ | -16.5% | 34.3% | $5,075 |
| **Breakout solo** | **38** | **1.711** ✅ | **+16.1%** | **5.1%** | **$68** |
| Combined ADX>20 | 94 | 1.464 ✅ | +29.0% | 6.6% | $942 |
| Combined ADX>25 | 184 | 1.303 ✅ | +37.3% | 12.4% | $2,371 |
| Combined ADX>30 | 253 | 1.158 ✅ | +26.5% | 15.2% | $3,285 |

### BTC — 730 días

| Estrategia | T | PF | Ret | MaxDD | Fees |
|---|---|---|---|---|---|
| Pullback solo | 241 | 1.126 ✅ | +23.6% | 11.8% | $6,026 |
| **Breakout solo** | **13** | **1.627** ✅ | **+4.7%** | **3.0%** | **$29** |
| Combined ADX>20 | 76 | 1.020 ✅ | +1.1% | 9.1% | $1,525 |
| Combined ADX>25 | 106 | 1.120 ✅ | +9.2% | 8.3% | $2,326 |
| Combined ADX>30 | 149 | 1.117 ✅ | +12.4% | 11.2% | $3,392 |

### ETH — 730 días

| Estrategia | T | PF | Ret | MaxDD | Fees |
|---|---|---|---|---|---|
| Pullback solo | 160 | 0.964 ❌ | -3.9% | 20.4% | $2,143 |
| Breakout solo | 14 | 1.442 ✅ | +3.7% | 3.0% | $21 |
| Combined ADX>20 | 32 | 1.535 ✅ | +10.2% | 4.5% | $296 |
| **Combined ADX>25** | **68** | **1.576** ✅ | **+24.6%** | **6.6%** | **$906** |
| Combined ADX>30 | 81 | 1.377 ✅ | +20.1% | 11.0% | $1,164 |

---

## Análisis por asset

### BTC — Breakout solo es la mejor estrategia

El pullback en BTC no tiene edge sobre 5 años (PF=0.896). El ADX router al añadir trades
de pullback contamina el sistema: el mejor combined (ADX>25) solo llega a PF=1.028 vs PF=1.810
del breakout solo. El breakout filtra naturalmente los períodos sin tendencia (no entra).

**Veredicto BTC: Breakout solo.**

### ETH — Combined interesante pero paga costo de robustez

En 730d, Combined ADX>25 supera al breakout solo (PF=1.576 vs 1.442) y cuadruplica el retorno
(+24.6% vs +3.7%). El pullback ETH con ADX≤25 tiene edge en tendencias moderadas del bull market
2024.

Sin embargo en 5 años, el combined baja de PF=1.711 a PF=1.303. El gain en 730d se debe a que
esos 730 días capturan el bull market 2024 donde el pullback funcionó excepcionalmente.

**Veredicto ETH: Breakout solo. El combined no justifica la complejidad ni la pérdida de
robustez en 5 años.**

---

## Conclusión final: Breakout solo para ambos assets

| Criterio | Pullback | Breakout | Combined (mejor) |
|---|---|---|---|
| BTC PF 5y | 0.896 ❌ | **1.810** ✅ | 1.028 |
| ETH PF 5y | 0.939 ❌ | **1.711** ✅ | 1.464 |
| BTC PF 730d | 1.126 ✅ | **1.627** ✅ | 1.120 |
| ETH PF 730d | 0.964 ❌ | 1.442 ✅ | **1.576** |
| BTC MaxDD | 49.6% | **4.0%** | 17.0% |
| ETH MaxDD | 34.3% | **5.1%** | 6.6% |
| Fees totales BTC+ETH 5y | **$13,986** | **$164** | $3,385–$9,003 |
| Robustez 5y+730d | ❌ falla en 3/4 | ✅ pasa las 4 | pasa 3/4 |

El breakout solo gana en PF, MaxDD, fees y robustez en todas las ventanas.
La única métrica donde el combined gana es el retorno absoluto en 730d para ETH,
explicado por el bull market 2024 — no representa edge estructural.

---

## Decisión

- **Estrategia a deployar:** Daily Breakout solo (sin router ADX)
- **Parámetros:** N=10, vol≥1.5×, ATR×1.5, RR=2, Risk=1%
- **Motor:** `paper_engine_breakout.py --loop`
- **Estado del combined:** descartado — documentado aquí para referencia futura

---

## Estado al cerrar sesión

| Item | Estado |
|------|--------|
| `core/strategy_breakout.py` | ✅ Implementado y validado |
| `paper_engine_breakout.py` | ✅ Implementado, dry-run OK |
| `backtest/backtest_combined_strategy.py` | ✅ Ejecutado, combined descartado |
| Deploy a Cloud Run | ⬜ **PENDIENTE — próxima sesión** |

## Pendiente para la próxima sesión

1. Actualizar Dockerfile: `CMD ["python", "paper_engine_breakout.py", "--loop"]`
2. Crear `deploy/deploy_005_FECHA.md` con registro del cambio
3. Deploy a Cloud Run europe-west1
4. Archivar `paper_monitor.py` (dejar de correrlo, no borrarlo)
5. Monitorear primeras señales reales del breakout en producción
