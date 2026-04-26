# Experiment Session Summary — 2026-04-26

## Objetivo
Diagnosticar las pérdidas del sistema en paper trading (semana del 19–26 de Abril 2026)
y determinar si requieren un ajuste al código de producción.

## Contexto: Estado del Sistema en Live Paper Trading

El sistema (EXP002+007+009) lleva activo desde el 18 de Abril 2026.
Equity inicial: 10,000 USD. Equity al 26 de Abril: **9,694 USD (-3.06%)**.

### Trades ejecutados (log completo)

| # | Fecha UTC | Par | Dir | Razón | Net USD | Equity |
|---|-----------|-----|-----|-------|---------|--------|
| 1 | 19-Apr 16:00 | ETH/USDT | SHORT | TP | +200 | 10,200 |
| 2 | 19-Apr 17:45 | ETH/USDT | SHORT | TP | +204 | 10,404 |
| 3 | 21-Apr 00:45 | BTC/USDT | LONG  | SL | -104 | 10,300 |
| 4 | 21-Apr 06:30 | BTC/USDT | LONG  | TP | +206 | 10,506 |
| 5 | 21-Apr 19:30 | ETH/USDT | SHORT | SL | -105 | 10,401 |
| 6 | 23-Apr 00:15 | BTC/USDT | LONG  | SL | -104 | 10,297 |
| 7 | 23-Apr 21:00 | ETH/USDT | SHORT | SL | -103 | 10,194 |
| 8 | 23-Apr 21:45 | ETH/USDT | SHORT | SL | -102 | 10,092 |
| 9 | 23-Apr 23:00 | ETH/USDT | SHORT | SL | -101 | 9,991  |
| 10| 24-Apr 01:00 | ETH/USDT | SHORT | SL | -100 | 9,891  |
| 11| 24-Apr 02:15 | ETH/USDT | SHORT | SL | -99  | 9,792  |
| 12| 24-Apr 02:45 | ETH/USDT | SHORT | SL | -98  | 9,694  |

**Win rate semana:** 3/12 = 25% | **Profit factor:** 0.666

### Patrón identificado

El problema principal son los **6 SLs consecutivos en ETH/USDT** (trades 7–12).
Durante Apr 23–24, ETH cotizó en un rango estrecho de ~45 USD (2285–2333).
El sistema disparó 6 shorts cuyo SL natural estaba en 2330–2333, exactamente el
techo del rango. El mercado tocó ese techo repetidamente sin confirmar el downtrend.

---

## Experimentos Realizados

### EXP011 — SL mínimo basado en ATR14 (15m) — **REVERT**

**Hipótesis:** El SL basado en `candle_high` es demasiado pequeño (0.19%–0.44%).
Expandirlo a `max(candle_extreme, 1.0×ATR14)` daría más espacio al precio.

**Resultado:**

| Métrica | BTC base | BTC EXP011 | ETH base | ETH EXP011 |
|---------|----------|------------|----------|------------|
| Trades | 99 | 138 | 207 | 245 |
| PF | 1.297 | 1.051 | 1.375 | 1.276 |
| Max DD | 7.78% | 9.97% | 10.76% | 17.56% |

**Razón del REVERT:** El ATR expandió el SL en el 100% de trades BTC y 78.8% de ETH.
El TP (2× el riesgo) también se aleja, y el precio no llega con suficiente frecuencia.
Win rate cae, DD sube. El SL pequeño no es el problema — es la calidad de la señal.

---

### EXP012 — Filtro EMA20/EMA50 spread (≥ 0.5%) en todas las entradas — **CONDITIONAL → REVERT**

**Hipótesis:** Cuando EMA20 y EMA50 están muy próximas (< 0.5% de separación), el
mercado está en rango. El filtro `|EMA20-EMA50|/EMA50 ≥ 0.5%` debería bloquearlo.

**Hallazgo clave:** Durante Apr 23–24, el spread de ETH era 0.38–0.44% — por debajo
del umbral. El filtro habría bloqueado los **6/6 shorts perdedores** y los **7/7
trades perdedores evitables** de la semana.

**Resultado:**

| Métrica | BTC base | BTC EXP012 | ETH base | ETH EXP012 |
|---------|----------|------------|----------|------------|
| Trades | 99 | 7 | 207 | 130 |
| PF | 1.297 | 0.322 | 1.375 | 1.482 |

**Razón del REVERT:** Para BTC, el filtro es catastrófico a cualquier umbral probado
(0.1%–0.5%): solo quedan 7–14 trades. Los longs de BTC ocurren precisamente cuando
el spread es pequeño (inicio de uptrend, EMA20 aún cerca de EMA50).
Para ETH mejora el PF (1.375→1.482) pero con solo 63% de trades.

**Insight:** El spread pequeño puede significar (a) rango lateral [malo] o (b) inicio
de tendencia [bueno para longs]. El filtro no discrimina entre ambos casos.

---

### EXP013 — Filtro EMA spread solo en señales SHORT — **REVERT**

**Hipótesis:** Aplicar el filtro de spread únicamente a shorts evita dañar los longs
de BTC (que son inmunes al problema) mientras filtra ETH shorts en rangos.

**Resultado:**

| Métrica | BTC base | BTC EXP013 | ETH base | ETH EXP013 |
|---------|----------|------------|----------|------------|
| Trades | 99 | 99 (=) | 207 | 197 |
| PF | 1.297 | 1.297 (=) | 1.375 | 1.349 |
| Max DD | 7.78% | 7.78% (=) | 10.76% | 11.63% |

**Razón del REVERT:** El filtro bloqueó 27 shorts en 180 días. No solo bloqueó shorts
malos — también bloqueó shorts buenos en períodos de spread transitoriamente comprimido.
El PF de ETH baja de 1.375 a 1.349 y el DD empeora levemente.

**Descomposición:** ETH longs PF=1.180, ETH shorts PF=1.558 (sin filtro).
El filtro daña el lado más fuerte del sistema (shorts).

---

### EXP014 — Filtro EMA200 dirección macro en ETH — **REVERT**

**Hipótesis:** Solo permitir ETH shorts cuando `close_1h < EMA200` (macro bajista)
y ETH longs cuando `close_1h > EMA200` (macro alcista). Alinea señal con régimen macro.

**Contexto previo:** EXP010 ya probó EMA200 + ATR regime (compuesto) y fue peor que
EXP009. EXP014 aisló solo el componente EMA200 puro.

**Cobertura sobre pérdidas live:** El EMA200 solo habría bloqueado 3 de 7 shorts
perdedores. ETH estaba oscilando alrededor de su EMA200 (~2328) durante el período,
no claramente por encima ni por debajo.

**Resultado:**

| Métrica | BTC base | BTC EXP014 | ETH base | ETH EXP014 |
|---------|----------|------------|----------|------------|
| Trades | 99 | 99 (=) | 207 | 155 |
| PF | 1.297 | 1.297 (=) | 1.375 | 1.141 |
| Return | +18.45% | +18.45% (=) | +57.95% | +15.47% |
| Max DD | 7.78% | 7.78% (=) | 10.76% | 12.43% |

**Razón del REVERT:** ETH estuvo la mayor parte de los 180 días por encima de su
EMA200 (período alcista). El filtro bloqueó 97 entradas — demasiadas, incluyendo los
shorts más rentables del período Nov 2025 y Feb 2026.

---

## Conclusión General

**No se realizó ningún cambio al código de producción.**

### Los 3 hallazgos clave de la investigación

**1. Las pérdidas de la semana son varianza estadística normal.**
El sistema tiene WR ≈ 40%. Una racha de 6 pérdidas consecutivas tiene probabilidad
~1.3% (0.6⁶). Esto ocurrirá ocasionalmente. El drawdown actual (-3.1%) está muy
por debajo del máximo histórico esperado (-10.76% en ETH).

**2. Ningún filtro simple mejora el sistema sin dañar el edge existente.**
Los 4 experimentos intentaron distintos ángulos (SL width, EMA spread, dirección macro)
y los 4 resultaron en REVERT. El sistema EXP009 ya está en un óptimo local para los
180 días de datos históricos. Agregar filtros para casos específicos de live trading
introduce sobreajuste.

**3. El filtro EMA spread (EXP012) es el único que muestra señal real.**
Para ETH, el spread < 0.5% detecta correctamente los 7 trades perdedores evitables
de la semana. Sin embargo, su impacto en el backtest de 180 días es neutro/negativo,
lo que sugiere que el evento de Apr 23-24 es raro en el histórico.
**Queda anotado como candidato a re-evaluar con más datos (≥365 días).**

### Mecanismos de protección ya activos

Los siguientes mecanismos del commit `043962f` ya contemplan rachas perdedoras:
- **Circuit breaker:** pausa entradas tras N pérdidas consecutivas
- **Break-even stop:** protege ganancias en posiciones abiertas
- **Cooldown:** previene re-entrada inmediata tras pérdidas

### Próximos pasos sugeridos (no urgentes)

1. Acumular más datos de paper trading (objetivo: 50–100 trades) para evaluar si
   el WR real converge al backtest (~40%).
2. Cuando se disponga de datos de Apr–Jun 2026 en CSV, re-testear el filtro EMA
   spread (EXP012 variant) con el período problemático incluido en la muestra.
3. Si el WR en live se mantiene por debajo de 30% durante 30+ trades, entonces
   sí investigar si hay un drift estructural entre backtest y live.
