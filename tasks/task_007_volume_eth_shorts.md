# Task 007 — Volume Filter solo en ETH shorts (iteración de Task 003)

**Prioridad:** 2  
**Estado:** ✅ APROBADO — ETH-SHORT-C (vol ≥ 1.0× mean50) es la variante seleccionada  
**Archivo backtest:** `backtest/backtest_task007.py`  
**Depende de:** Task 006 (sistema COMBINED como nueva base)

---

## Contexto

Task 003 (Volume Filter) mostró resultados asimétricos:

- **ETH:** VOL-D (lookback 50) mejora PF de 1.318 → 1.556 (+18%). Impresionante.
- **BTC:** VOL-B mejora PF de 1.344 → 1.439 (+7%).
- **Walk-forward:** W3 Recovery 2025 falla con cualquier variante de volumen.

El problema en W3: el filtro de volumen elimina demasiados trades buenos en ese período.
Analizando el desglose histórico, el lado más problemático de ETH son los **shorts** —
ETH shorts tienen históricamente peor win rate y más exposición a stop-hunts.

La hipótesis: el volumen como confirmación es especialmente útil en ETH shorts,
donde una vela bajista de bajo volumen es frecuentemente una trampa de liquidez antes
de un rebote alcista. Aplicar el filtro solo ahí minimiza el impacto en trades buenos.

---

## Fundamento

De los datos de Task 003 y el historial de experimentos:

- **ETH longs PF ≈ 1.18** (históricamente débil)
- **ETH shorts PF ≈ 1.56** (históricamente fuerte)
- Los 6 SLs consecutivos de la semana del 23-24 Apr 2026 en live trading fueron **todos shorts**
  en mercado ranging de bajo volumen (documentado en `exp_session_2026_04_26_paper_losses.md`)

Si el volumen bajo precede a un rebote (short trampa), filtrar shorts con volumen bajo
tiene causalidad clara. Filtrar longs con volumen bajo no tiene la misma lógica.

---

## Diseño del experimento

### Variantes

| Variante | Filtro aplicado | Asset | Direcciones |
|----------|----------------|-------|-------------|
| BASE | sin volumen | BTC+ETH | todas |
| ETH-SHORT-A | vol ≥ 1.0× mean(20) | ETH | solo shorts |
| ETH-SHORT-B | vol ≥ 1.2× mean(20) | ETH | solo shorts |
| ETH-SHORT-C | vol ≥ 1.0× mean(50) | ETH | solo shorts |
| ALL-SHORT-B | vol ≥ 1.2× mean(20) | BTC+ETH | todos los shorts |

### Implementación clave

```python
# Aplicar filtro de volumen SOLO a ETH shorts
if asset == 'ETH' and direction == 'short':
    vol_ratio = row['volume'] / row['vol_mean20']
    if vol_ratio < VOL_MIN_RATIO:
        continue  # skip short sin volumen
# Para longs y BTC: siempre entrar (sin filtro de volumen)
```

---

## Hipótesis cuantitativa

Si la hipótesis es correcta:
- Los trades de ETH SHORT filtrados por bajo volumen deberían tener PF < 1.0
- Los trades de ETH SHORT con volumen alto deberían tener PF > 1.5
- Los trades de ETH LONG no deberían verse afectados (el filtro no aplica)
- El walk-forward W3 Recovery 2025 debería mejorar (ese período tenía muchos ETH shorts malos)

---

## Criterios de éxito (KEEP)

- ETH PF mejora ≥ 0.05 sobre el sistema base de Task 006
- W3 Recovery 2025 combinado ≥ 1.05 (mejora sobre 1.034 del EXP019 BASE)
- Trade count ETH no cae por debajo de 90 (el filtro de shorts no elimina demasiados)
- Walk-forward: 4/4 ventanas ✅

## Criterios de fracaso (REVERT)

- ETH PF no mejora o empeora → el volumen en shorts de ETH no discrimina
- W3 sigue fallando → el problema de Recovery 2025 es estructural, no de volumen

## Criterio para ITERAR

- Mejora en ETH pero empeora W3 → probar con lookback más largo (100 velas)
- Mejora en ETH pero no significativa → combinar con TIME-B (¿los shorts nocturnos son los malos?)

---

## Análisis diagnóstico previo (correr primero)

Antes de las variantes, calcular el PF de ETH shorts por nivel de volumen:

```
ETH SHORTS por vol_ratio (BASE):
vol_ratio < 0.8:   trades=XX  PF=X.XXX  ← estos son los candidatos a filtrar
vol_ratio 0.8-1.2: trades=XX  PF=X.XXX
vol_ratio > 1.2:   trades=XX  PF=X.XXX  ← estos son los que queremos conservar
```

Si los de bajo volumen tienen PF < 1.0, la hipótesis tiene base empírica.

---

## Referencias

- `backtest/backtest_task003.py` → código base con vol_ratio ya calculado
- `exp_session_2026_04_26_paper_losses.md` → los 6 ETH shorts consecutivos en Asia
- Task 003 resultado: ETH VOL-D PF=1.556 sobre 730d pero walk-forward W3 falla
