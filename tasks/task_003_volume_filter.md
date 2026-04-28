# Task 003 — Volume Filter en vela de entrada

**Prioridad:** 3  
**Estado:** ⬜ PENDIENTE  
**Archivo backtest:** `backtest/backtest_task003.py`  
**Depende de:** sistema base EXP019 + resultados de Task 001 y 002

---

## Fundamento

Toda la lógica actual del sistema es de precio puro — ningún indicador usa volumen.
Esto es una limitación significativa porque el volumen es la única forma de confirmar
que detrás de un movimiento de precio hay convicción institucional y no solo ruido.

En el contexto específico del pullback continuation:

**Pullback de calidad (bajo volumen):** el precio retrocede a la EMA20 con volumen
decreciente. Esto indica que los vendedores (en un uptrend) están agotando su presión
y los compradores están absorbiendo. Es la señal correcta.

**Pullback de baja calidad (alto volumen):** el precio retrocede con volumen creciente.
Esto indica que hay presión vendedora activa, no solo toma de ganancias normal. El precio
puede continuar cayendo más allá de la EMA20. El SL queda expuesto.

La vela de entrada (trigger en 15m) también debe tener volumen confirmatorio:
si la reversión ocurre con volumen por encima del promedio, hay convicción en el rebote.

---

## Tesis

> Añadir confirmación de volumen en la vela de trigger 15m reduce el número de trades
> pero mejora el win rate porque filtra reversiones falsas. El trade count reducido
> se compensa con mayor expectancy por trade. El PF neto mejora.

Hipótesis secundaria: el filtro ayudará más en ETH (longs+shorts) que en BTC (longs only)
porque ETH tiene más trades en regímenes choppy donde el volumen es más ruidoso.

---

## Diseño del experimento

### Definición de "volumen confirma"

```python
# Volume ratio: volumen de la vela de trigger / media de las últimas N velas
vol_ratio = volume_candle / rolling_mean(volume, VOL_LOOKBACK)

# El volumen confirma si es superior al threshold
vol_confirms = vol_ratio >= VOL_MIN_RATIO
```

### Variantes a testear

| Variante | VOL_MIN_RATIO | VOL_LOOKBACK | Descripción |
|----------|--------------|--------------|-------------|
| BASE | — | — | Sin filtro de volumen (referencia) |
| VOL-A | 1.0× | 20 velas | Volumen ≥ promedio últimas 20 velas 15m |
| VOL-B | 1.2× | 20 velas | Volumen ≥ 120% del promedio — más exigente |
| VOL-C | 1.5× | 20 velas | Volumen ≥ 150% — señales de alta convicción solo |
| VOL-D | 1.0× | 50 velas | Lookback más largo — más estable |

Adicionalmente, testear el filtro inverso sobre el pullback (no solo la vela de trigger):
- El pullback hacia la EMA20 debe ocurrir con volumen decreciente (< 0.8× promedio)

### Datos necesarios

Los CSVs actuales (`data/*_15m_last_730d.csv`) deben incluir columna `volume`.
Verificar antes de implementar:
```python
df = pd.read_csv('data/BTCUSDT_15m_last_730d.csv')
assert 'volume' in df.columns, "columna volume no disponible"
```

---

## Criterios de éxito (KEEP)

- Win rate mejora ≥ 3pp sobre BASE (de ~48% → ≥51%)
- PF mejora ≥ 0.05 sobre BASE
- Trade count no cae por debajo de 70 (mínimo estadístico con este filtro)
- Walk-forward: PF combinado ≥ 1.0 en las 4 ventanas

## Criterios de fracaso (REVERT)

- Win rate no mejora con ninguna variante → el volumen en 15m no discrimina señales
- Trade count cae por debajo de 60 sin mejora proporcional en PF → filtro demasiado restrictivo
- PF baja (el filtro está eliminando buenos trades junto con los malos)

## Criterio para ITERAR

- Win rate mejora pero PF no → el filtro está eliminando trades con SL pequeño que son buenos
  → Considerar aplicar el filtro solo a ETH shorts (los más problemáticos históricamente)

---

## Output esperado del script

```
=== BTC TASK003 — Volume Filter ===
Variante  Trades  WR%   PF     Return  MaxDD  Vol_ratio_avg
BASE        99   49.5%  1.390  +28.4%  7.01%  —
VOL-A       85   52.1%  1.450  +27.8%  6.20%  1.31×
VOL-B       72   54.3%  1.490  +25.2%  5.80%  1.48×
VOL-C       51   56.0%  1.420  +18.1%  5.10%  1.72×  ← pocos trades
VOL-D       87   51.8%  1.430  +27.1%  6.40%  1.28×

Trades filtrados por volumen bajo: 14/99 (14.1%)
PF de los trades filtrados: 0.82  ← confirma que el filtro elimina los malos
```

---

## Notas de implementación

- El volumen debe normalizarse por activo (BTC y ETH tienen volúmenes nominales muy distintos).
- No usar volumen en USDT, usar volumen en unidades base (BTC o ETH) para comparabilidad.
- El rolling mean de volumen debe calcularse solo sobre las N velas previas (sin look-ahead).
- El volumen de Binance Futures es volumen de contratos, no spot — consistente entre los dos assets.

---

## Referencias

- EXP019 BASE: BTC PF 1.390 WR 49.5% / ETH PF 1.386 WR 46.4%
- `core/strategy_pullback.py` → `prepare_15m()` — lugar donde añadir vol_ratio
