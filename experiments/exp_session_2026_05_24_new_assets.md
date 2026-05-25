# Sesión 2026-05-24 — Nuevos Activos: SOL / BNB / XRP

## Rama
`feat/new-assets`

## Objetivo
Evaluar si SOL, BNB y XRP pueden incorporarse al sistema con el stack de producción actual
(EXP002 pullback + SLOPE_CAP + TIME-B + DYN-B + vol_filter_shorts).

## Stack aplicado
- EXP002: pullback continuation (EMA20/50 slope, Kaufman ER)
- EXP016A/017-B: SL mínimo calibrado por activo
- EXP019 SLOPE_CAP: skip si ema50_slope > 0.20%
- Task004 TIME-B: solo 07–21 UTC
- Task002 DYN-B: sizing inverso a ATR ratio
- Task007: vol_filter en shorts (vol >= 1.0× mean50)
- Sin filtro 4h (solo BTC)

## Datos
- SOL: 730d disponibles (ya existían)
- BNB: descargados 730d (2024-05-15 → 2026-05-25)
- XRP: descargados 730d (2024-05-25 → 2026-05-25)

## Hallazgo crítico: filtro absoluto `candle_range < 1.0 USD`

`is_candle_quality()` en `strategy_pullback.py` usa una condición absoluta en dólares:
```python
if candle_range < 1.0:
    return False
```

Esto es incompatible con activos de precio bajo:

| Activo | Rango precio | % candles < $1 rango |
|--------|-------------|----------------------|
| BTC    | ~20k–110k   | ~0%                  |
| ETH    | ~1,500–4,000| ~0%                  |
| BNB    | ~410–1,370  | 14.9%                |
| SOL    | ~71–295     | **66.0%**            |
| XRP    | ~0.39–3.65  | **100.0%**           |

## Resultados del backtest (730d, fees incluidas)

| Activo       | Variante      | Trades | PF    | WR    | MaxDD  | WF 4×182d |
|--------------|---------------|--------|-------|-------|--------|-----------|
| BTC (ref)    | longs only    | 71     | 1.787 | 54.9% | 6.69%  | —         |
| ETH (ref)    | L+S           | 69     | 1.568 | 47.8% | 7.05%  | —         |
| SOL          | LONGS_ONLY    | 29     | 0.738 | 31.0% | 10.43% | 1/4 ❌    |
| SOL          | LONGS_SHORTS  | 59     | 0.537 | 23.7% | 28.44% | —         |
| BNB          | LONGS_ONLY    | 44     | 0.876 | 36.4% | 9.00%  | 2/4 ❌    |
| BNB          | LONGS_SHORTS  | 93     | 0.872 | 36.6% | 12.27% | —         |
| XRP          | LONGS_ONLY    | 0      | 0.000 | —     | —      | 0/4 ❌    |
| XRP          | LONGS_SHORTS  | 0      | 0.000 | —     | —      | —         |

## Diagnóstico por activo

### XRP — RECHAZADO (incompatibilidad estructural)
100% de las velas 15m tienen rango < $1 USD → 0 trades. La estrategia es incapaz de
generar señales. Para soportar XRP sería necesario refactorizar todos los filtros
de rango a base porcentual, lo cual es un rework mayor sin garantía de edge.

### SOL — RECHAZADO (sin edge)
66% de las velas filtradas por el floor de $1. Con los pocos trades que pasan:
- PF=0.738 → pérdida neta a largo plazo
- WR=31% → no tiene edge en la dirección del trade
- Solo 1/4 ventanas WF positivas

### BNB — RECHAZADO (sin edge)
El filtro de $1 no es el problema (14.9%). La estrategia simplemente no tiene edge en BNB:
- PF=0.876 → pérdida neta
- 2/4 ventanas WF (W1 Bear y W4 Bear fallan)

## Comparación con EXP005 (2022, antes de mejoras actuales)
EXP005 histórico ya había rechazado SOL (PF=0.852) y BNB (PF=1.081).
Con el stack mejorado los resultados son similares o peores → confirma que
el pullback continuation no encuentra edge en estos activos.

## Decisión
**RECHAZAR los tres activos. NO incorporar SOL/BNB/XRP.**

El sistema se mantiene como BTC+ETH. La diversificación actual cubre suficientemente
los diferentes regímenes (validado en EXP021 walk-forward 4×182d).

## Qué quedaría pendiente si se quisiera retomar
1. Refactorizar `is_candle_quality()` a filtro porcentual para soportar activos < $100
2. Re-evaluar XRP solo una vez resuelto lo anterior
3. Considerar BNB con estrategia diferente (no pullback continuation)
4. La estrategia de pullback no es regime-agnostic para altcoins de baja cap

## Archivos
- `backtest/backtest_new_assets.py` — backtest completo, todas las variantes
- `data/BNBUSDT_1h_last_740d.csv`, `data/BNBUSDT_15m_last_730d.csv` — datos BNB 730d
- `data/XRPUSDT_1h_last_740d.csv`, `data/XRPUSDT_15m_last_730d.csv` — datos XRP 730d
- `data/backtest_new_assets.json` — métricas en JSON
