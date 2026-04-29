# Task 005 — Tercer Activo (SOL o BNB)

**Prioridad:** 5  
**Estado:** ⬜ PENDIENTE  
**Archivo backtest:** `backtest/backtest_task005.py`  
**Depende de:** sistema base EXP019 + resultados de Tasks 001–004

---

## Fundamento

El sistema opera actualmente sobre BTC/USDT y ETH/USDT. Ambos son activos de alta
liquidez, con estrategia validada sobre 730d. La complementariedad de régimen entre
ambos (descubierta en EXP021) ya cubre los 4 principales regímenes de mercado.

Sin embargo, añadir un tercer activo con las siguientes propiedades podría mejorar
el sistema:

1. **Más oportunidades de trade:** más señales por período, especialmente en ventanas
   donde BTC y ETH están en régimen desfavorable simultáneamente.

2. **Descorrelación adicional:** SOL y BNB tienen correlación de ~0.75–0.85 con BTC
   en períodos normales, pero se desacoplan con más frecuencia que ETH (~0.85–0.92).
   Esa descorrelación parcial añade diversificación sin cambiar la estrategia.

3. **Mayor retorno total** (más trades = más expectancy acumulada) manteniendo riesgo
   por trade constante en 1%.

**Por qué no lo hicimos antes (EXP005):** EXP005 testó cross-asset con BNB, DOGE,
SOL y XRP. El resultado fue REVERT porque el PF de los nuevos activos era inferior
al de BTC/ETH, diluyendo el sistema. Sin embargo, en esa época no teníamos SLOPE_CAP.
El filtro podría cambiar el resultado para activos más volátiles.

---

## Tesis

> SOL/USDT o BNB/USDT, con los mismos parámetros del sistema (SLOPE_CAP + SL mínimo
> adaptado), genera PF > 1.2 sobre 730d con fees. El sistema combinado
> BTC+ETH+SOL mejora el PF combinado y el trade count sin empeorar el MaxDD.

**Hipótesis sobre SOL:** SOL tiene mayor volatilidad intradía que ETH pero sigue
la misma estructura técnica de tendencias/pullbacks. El SLOPE_CAP debería funcionar
igual. SL mínimo estimado: ≥0.50–0.60%.

**Hipótesis sobre BNB:** BNB tiene menor volatilidad que SOL, más similar a ETH.
Podría ser un mejor candidato para longs+shorts. SL mínimo estimado: ≥0.40%.

---

## Diseño del experimento

### Fase 1 — Validación individual del tercer activo

Antes de combinar, validar que el candidato tiene edge por sí solo:

```
Activo candidato:   SOL/USDT o BNB/USDT (testear ambos, elegir el mejor)
Datos requeridos:   *_15m_last_730d.csv + *_1h_last_740d.csv
Descarga:           python fetch_all.py --symbol SOL --2y
Parámetros:         SLOPE_CAP=0.20%, longs+shorts, RR=2:1
SL mínimo:          a determinar (empezar con 0.50%, igual que ETH)
```

Criterio de viabilidad individual:
- PF > 1.2 sobre 730d con fees
- Trades ≥ 80
- MaxDD < 20%

Si el candidato no pasa esto solo, no tiene sentido añadirlo al sistema.

### Fase 2 — Sistema combinado BTC+ETH+Candidato

Solo si pasa Fase 1:

```python
# Walk-forward 4×182d para el sistema de 3 activos
# Criterio: PF combinado (3 assets) > 1.0 en las 4 ventanas
# Comparar vs sistema de 2 activos (EXP021 baseline)
```

### Variantes

| Variante | Activos | Descripción |
|----------|---------|-------------|
| BASE | BTC + ETH | Sistema actual (referencia) |
| SOL | BTC + ETH + SOL | Añade Solana |
| BNB | BTC + ETH + BNB | Añade Binance Coin |
| BEST | BTC + ETH + mejor_de_SOL_BNB | El que pasa Fase 1 con mayor PF |

---

## Datos a descargar

```bash
# Descargar antes de correr el backtest
python fetch_all.py --symbol SOL --2y
python fetch_all.py --symbol BNB --2y

# Archivos esperados:
# data/SOLUSDT_15m_last_730d.csv
# data/SOLUSDT_1h_last_740d.csv
# data/BNBUSDT_15m_last_730d.csv
# data/BNBUSDT_1h_last_740d.csv
```

---

## Criterios de éxito (KEEP)

**Fase 1 (individual):**
- PF > 1.2 con fees sobre 730d
- MaxDD < 20%
- Trades ≥ 80

**Fase 2 (combinado):**
- PF combinado (3 assets) ≥ PF combinado EXP021 (2 assets)
- Walk-forward: PF combinado ≥ 1.0 en las 4 ventanas
- MaxDD del equity combinado no empeora más de 2pp

## Criterios de fracaso (REVERT)

- Fase 1: PF individual < 1.0 → el activo no tiene edge con esta estrategia
- Fase 2: El sistema de 3 activos tiene menor PF o mayor MaxDD que el de 2 activos
  → el tercer activo diluye el edge existente (igual que EXP005)

## Criterio para ITERAR

- PF individual entre 1.0–1.2 → ajustar SL mínimo (probar 0.60%, 0.70%)
- PF bueno pero alta correlación en el walk-forward → el activo no añade diversificación real

---

## Consideraciones operativas

- Añadir un tercer activo al sistema live requiere un tercer state file (`sol_state.json`)
  y un tercer logger — cambio menor en `paper_monitor.py`.
- La gestión de riesgo total del portafolio: con 3 activos a 1% cada uno, la exposición
  máxima simultánea es 3% del equity. Evaluar si esto es aceptable o si se debe reducir
  a 0.75% por trade en el sistema de 3 activos.
- Liquidez: SOL y BNB tienen suficiente liquidez en Binance Futures para el tamaño
  de posición que manejamos.

---

## Referencias

- EXP005: cross-asset con 4 activos adicionales → REVERT (sin SLOPE_CAP en esa época)
- EXP021 baseline: sistema BTC+ETH, PF combinado mínimo 1.051 (W3)
- `fetch_all.py` — script de descarga de datos históricos
