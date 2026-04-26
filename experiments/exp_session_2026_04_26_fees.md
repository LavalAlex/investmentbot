# Experiment Session — 2026-04-26 (fees)

## Objetivo
Medir el impacto real de los fees de trading (Binance USDM Futures) sobre el sistema EXP009,
y encontrar parámetros que mantengan el edge después de comisiones.

## Contexto

Los fees nunca habían sido contemplados en ningún backtest ni en el paper engine.
El backtest base (EXP009) asumía cero fricción.

**Fees Binance USDM Futures VIP0:**
- Maker: 0.02% | Taker: 0.05%
- La estrategia usa market orders en entry y exit → **ambas son Taker**
- Round-trip: **0.10%** del nocional (sin BNB), 0.09% (con BNB)

---

## EXP015 — Backtest EXP009 con fees reales (0.05%/lado)

**Resultado: el sistema pierde dinero con fees.**

| Métrica | BTC sin fees | BTC con fees | ETH sin fees | ETH con fees |
|---------|-------------|-------------|-------------|-------------|
| PF | 1.297 | **0.777** | 1.375 | **0.951** |
| Return | +18.45% | **-15.83%** | +57.95% | **-7.28%** |
| Fee total 180d | — | $2,965 | — | $5,101 |
| Fee promedio/trade | — | $29.95 | — | $24.65 |

**Por qué pasa:** el edge bruto con R:R=2:1 y WR=40% es **0.20R por trade**.
El fee como múltiplo del riesgo es `0.10% / SL_dist_pct`. Con SL típico de 0.30%,
el fee = 0.33R → supera el edge.

**Threshold de SL mínimo viable** (con WR=40%, R:R=2:1):
```
0.20R > 0.10% / SL_pct × R  →  SL_pct > 0.50%
```
El sistema necesita SLs ≥ 0.50% para cubrir los fees. El mínimo vigente era 0.15%.

---

## EXP016 — Fee/edge fix: SL mínimo y/o R:R mayor

Se testearon tres variantes contra EXP015 (base con fees):

| Variante | MIN_SL | RR | BTC PF | BTC trades | ETH PF | ETH trades |
|---------|--------|-----|--------|------------|--------|------------|
| A: SL≥0.50%, RR=2:1 | 0.50% | 2:1 | 0.831 | 23 | **1.413** | 103 |
| B: SL≥0.15%, RR=3:1 | 0.15% | 3:1 | 0.691 | 91 | 0.939 | 189 |
| C: SL≥0.50%, RR=3:1 | 0.50% | 3:1 | **1.053** | 23 | 0.987 | 95 |

### Variante A — KEEP para ETH, pendiente para BTC

**ETH (Variante A):**
- PF: 0.951 → **1.413** ✓ (supera incluso el PF sin fees de EXP009)
- Return: -7.28% → **+30.11%** ✓
- MaxDD: 25.44% → **4.90%** ✓
- Trades: 207 → 103 (50% — estadísticamente válido)
- Long PF=1.257 | Short PF=1.563 — ambos lados rentables

**BTC (Variante A):**
- PF: 0.777 → 0.831 (mejora pero < 1.0)
- Solo 23 trades en 180 días — insuficiente para evaluar
- El problema: los longs de BTC en uptrend ocurren con SLs naturalmente pequeños
  (precio comprimido en el inicio del movimiento). El filtro SL≥0.50% elimina el 77%.

### Variante B → REVERT en ambos
RR=3:1 sin filtro SL reduce el WR (BTC 39%→26%, ETH 41%→31%) sin reducir fees
suficientemente. Peor que el base en todos los casos.

### Variante C — Marginal en ETH, solo OK en BTC
BTC cruza PF=1.0 (1.053) pero con solo 23 trades. ETH casi breakeven (0.987).
El RR=3:1 daña los longs de ETH (PF 0.699).

---

## Cambios aplicados a producción

### 1. paper_engine.py — fees incluidos en PnL
```python
FEE_PER_SIDE_PCT = 0.0005   # 0.05% taker
fee_usd  = (pos['entry'] + exit_price) * pos['qty'] * FEE_PER_SIDE_PCT
pnl      = gross_pnl - fee_usd
```
El trade record ahora incluye `gross_pnl` y `fee_usd` además de `pnl`.

### 2. paper_monitor.py — SL mínimo 0.50% para ETH (EXP016A)
```python
ETH_MIN_SL_DIST_PCT = 0.0050  # ETH necesita SL≥0.50% para cubrir fees
sl_min_pct = ETH_MIN_SL_DIST_PCT if asset == 'ETH/USDT' else MIN_SL_DIST_PCT
```
BTC mantiene el umbral de 0.15% (EXP007) hasta resolver el problema de bajo volumen.

### 3. logger_v2.py — log de cierre muestra fee
```
[CLOSE] SHORT | entry=2320.00 | exit=2333.00 | reason=SL | fee=2.45 USD | net=-102.45 USD | equity=9,791.55 USD
```

---

## Pendientes

1. **BTC con fees**: el sistema BTC actualmente pierde dinero. Opciones a investigar:
   - SL mínimo intermedio (ej. 0.30%) — menos trades descartados
   - Limit orders en entry (Maker 0.02%): round-trip baja a 0.07%, threshold baja a 0.35%
   - R:R asimétrico solo para BTC (ej. 3:1 con SL≥0.30%)

2. **Re-evaluar equity paper_state.json**: los trades históricos en `paper_state.json`
   no tienen fees descontados. El equity registrado está inflado vs el real.
   Cuando se tengan suficientes trades nuevos (post-fix), considerar un reset limpio.

3. **EXP012 revisit**: cuando haya datos Apr–Jun 2026 disponibles (≥365 días total),
   re-testear el filtro EMA spread ≥ 0.5% con fees incluidos en el backtest.
