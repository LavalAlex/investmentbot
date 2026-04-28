# Task 004 — Time-of-Day Filter

**Prioridad:** 4  
**Estado:** ⬜ PENDIENTE  
**Archivo backtest:** `backtest/backtest_task004.py`  
**Depende de:** sistema base EXP019 + resultados de Tasks 001, 002, 003

---

## Fundamento

Los mercados de futuros de crypto operan 24/7, pero la calidad de las señales no es
uniforme a lo largo del día. Hay patrones de liquidez y volatilidad bien documentados:

**Sesión asiática (00:00–07:00 UTC):**
- Menor volumen global
- Spreads más amplios en momentos de bajo volumen
- Mayor proporción de movimientos de "liquidez buscada" (stop hunts) antes de la apertura europea
- Los SLs colocados en niveles técnicos son más vulnerables porque se necesita menos capital
  para moverlos temporalmente

**Sesión europea (07:00–13:00 UTC):**
- Apertura de los mercados europeos — aumenta el volumen
- Los moves tienen más convicción porque hay más participantes
- Es cuando muchos patrones técnicos se "confirman" o "invalidan"

**Overlap Europe/US (13:00–17:00 UTC):**
- Máximo volumen del día
- Mayor liquidez → spreads más ajustados → SLs menos vulnerables al ruido
- Los movimientos tendenciales son más confiables

**Sesión US tarde / cierre (17:00–00:00 UTC):**
- Volumen decreciente
- Algunos movimientos bruscos al cierre de posiciones

Para una estrategia de pullback que coloca SLs en extremos de velas 15m, la sesión
asiática es la más peligrosa: un spike de bajo volumen puede tocar el SL y revertir.

---

## Tesis

> Filtrar entradas a las horas de mayor calidad de mercado (07:00–17:00 UTC) reduce
> los trades en sesión asiática de baja liquidez, mejorando el win rate porque se
> evitan los stop hunts nocturnos. El número de trades se reduce pero la calidad
> promedio mejora.

Hipótesis cuantitativa: la proporción de trades que terminan en SL es mayor en sesión
asiática (00:00–07:00 UTC) que en sesión europea/americana.

---

## Diseño del experimento

### Definición de ventanas horarias

Todas las horas en UTC (el timestamp de Binance es UTC).

```python
def get_session(hour_utc: int) -> str:
    if 0 <= hour_utc < 7:   return 'ASIA'
    if 7 <= hour_utc < 13:  return 'EUROPE'
    if 13 <= hour_utc < 17: return 'OVERLAP'
    return 'US_CLOSE'
```

### Variantes a testear

| Variante | Horas permitidas (UTC) | Descripción |
|----------|----------------------|-------------|
| BASE | 00:00–24:00 | Sin filtro (referencia) |
| TIME-A | 07:00–17:00 | Europe + Overlap — excliye Asia y US tarde |
| TIME-B | 07:00–21:00 | Añade US tarde — más trades |
| TIME-C | 13:00–17:00 | Solo overlap — muy restrictivo |
| TIME-D | Excluye 00:00–06:00 | Solo excluye Asia profunda |

### Análisis previo (diagnóstico)

Antes de testear variantes, calcular la distribución de trades por sesión en el BASE:

```
Sesión       Trades  WR%   PF
ASIA          XX     XX%   X.XX
EUROPE        XX     XX%   X.XX
OVERLAP       XX     XX%   X.XX
US_CLOSE      XX     XX%   X.XX
```

Si el PF de ASIA es similar al resto, el filtro no tiene base empírica → REVERT directo.

---

## Criterios de éxito (KEEP)

- PF mejora ≥ 0.05 sobre BASE con la mejor variante
- Win rate mejora ≥ 2pp
- Trade count no cae por debajo de 60 en 730d
- Walk-forward: PF combinado ≥ 1.0 en las 4 ventanas

## Criterios de fracaso (REVERT)

- El PF de sesión asiática en el diagnóstico es similar al resto → no hay efecto horario
  en los datos → filtro es innecesario
- Trade count cae por debajo de 50 sin mejora proporcional en PF

## Criterio para ITERAR

- Mejora solo en un asset → aplicar el filtro de forma diferenciada por asset

---

## Output esperado del script

```
=== BTC TASK004 — Time of Day Filter ===

Análisis por sesión (BASE):
Sesión       Trades  WR%   PF
ASIA (0-7)     18   38.9%  0.92   ← peor sesión
EUROPE (7-13)  25   52.0%  1.54
OVERLAP(13-17) 31   54.8%  1.61   ← mejor sesión
US_CLOSE(17-0) 25   44.0%  1.21

Variante  Trades  WR%   PF     Return  MaxDD
BASE        99   49.5%  1.390  +28.4%  7.01%
TIME-A      81   53.1%  1.510  +28.1%  5.80%  ← mismo return, mejor PF y DD
TIME-B      88   51.2%  1.460  +28.3%  6.10%
TIME-C      58   55.2%  1.550  +22.0%  4.90%  ← pocos trades
TIME-D      87   51.0%  1.430  +28.0%  6.40%
```

---

## Notas de implementación

- Usar `row['open_time'].hour` para obtener la hora UTC de cada vela 15m.
- El filtro aplica al momento de la entrada, no al cierre — si entramos a las 16:45
  y el TP se alcanza a las 01:00, el trade es válido (ya está en posición).
- Para el sistema live, este filtro es trivial de implementar: una línea en `scan_asset()`.

---

## Referencias

- EXP019 BASE: BTC PF 1.390 / ETH PF 1.386
- Binance Futures timestamps: UTC (verificado en datos históricos)
