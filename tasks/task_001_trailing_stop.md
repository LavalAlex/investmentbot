# Task 001 — Trailing Stop en lugar de TP fijo

**Prioridad:** 1 (mayor impacto esperado)  
**Estado:** ❌ REVERT  
**Archivo backtest:** `backtest/backtest_task001.py`  
**Depende de:** sistema base EXP019 (SLOPE_CAP activo)

---

## Fundamento

El sistema actual cierra todas las posiciones ganadoras exactamente en TP = entry ± 2×riesgo (RR 2:1 fijo).
Este mecanismo es correcto para capturar el edge mínimo de manera consistente, pero deja valor
sobre la mesa en trades donde el precio continúa muy por encima del TP.

El pullback continuation tiene edge precisamente en mercados tendenciales — que son los mismos
mercados donde el precio, una vez reanuda la tendencia, tiende a moverse más de 2:1 antes
de el próximo pullback. El TP fijo corta prematuramente los trades más rentables.

Evidencia empírica en el sistema: en EXP021, las ventanas W1 Bull 2024 y W4 Bear 2025-26
muestran win rates del 52% — muy por encima del 40% típico. Eso sugiere que el precio llega
cómodamente al TP en esas ventanas, lo que a su vez implica que continúa más allá.

---

## Tesis

> Reemplazar el TP fijo 2:1 por un trailing stop dinámico aumenta el profit factor y el
> retorno total, a costa de reducir ligeramente el win rate. El efecto neto es positivo
> porque los trades que "corren" en tendencias fuertes compensan los que cierran con
> ganancia menor al 2:1.

El trailing stop se activa solo después de que el precio alcanza un umbral mínimo de ganancia
(breakeven o +1:1), evitando que un trade ganador revierta a pérdida.

---

## Diseño del experimento

### Variantes a testear

| Variante | Lógica | Descripción |
|----------|--------|-------------|
| BASE | TP fijo 2:1 | Referencia EXP019 |
| TRAIL-A | Trailing 1.5×ATR(14) desde +1:1 | Trailing ajustado — se activa cuando el trade gana 1:1 |
| TRAIL-B | Trailing 2.0×ATR(14) desde +1:1 | Trailing más holgado — deja más espacio al precio |
| TRAIL-C | Trailing 1.5×ATR(14) desde BE | Se activa desde break-even — más agresivo |
| HYBRID  | TP fijo 2:1 O trailing 3×ATR (el que llegue primero) | Híbrido: captura el mínimo pero deja correr si hay momentum |

### Implementación

```python
# En cada barra, si hay posición abierta:
# 1. Activar trailing cuando precio supera umbral de activación
# 2. Una vez activo, actualizar trailing_sl = mejor_precio - N×ATR(14)
# 3. Cerrar cuando precio toca trailing_sl

if direction == 'long':
    if high >= activation_price and not trailing_active:
        trailing_active = True
        trailing_sl = high - trail_atr_mult * atr14
    if trailing_active:
        trailing_sl = max(trailing_sl, high - trail_atr_mult * atr14)
        if low <= trailing_sl:
            exit at trailing_sl, reason='TRAIL'
```

ATR(14) se calcula sobre el 15m (mismo timeframe de la entrada).

---

## Criterios de éxito (KEEP)

**Mínimo para KEEP (cualquiera de estas combinaciones):**
- PF mejora ≥ 5% sobre BASE en 730d para ambos assets, O
- Return total mejora ≥ 10% sobre BASE con MaxDD no peor

**Criterio de calidad adicional:**
- Walk-forward 4×182d: PF combinado BTC+ETH ≥ 1.0 en las 4 ventanas (igual que EXP021)
- Win rate no cae por debajo de 35% (si cae mucho, el trailing es demasiado agresivo)

## Criterios de fracaso (REVERT)

- PF igual o peor en ambos assets → el trailing corta trades antes de que maduren
- MaxDD empeora significativamente (> +5pp sobre BASE) → el trailing crea exposición excesiva
- Win rate cae por debajo de 30% → el precio revierte antes de activar el trailing

## Criterio para ITERAR

- Mejora en un asset pero no en el otro → ajustar el multiplicador ATR por asset
- PF mejora pero walk-forward falla una ventana → ajustar umbral de activación

---

## Output esperado del script

```
=== BTC TASK001 — Trailing Stop ===
Variante      Trades  WR%   PF     Return   MaxDD   Avg_exit_mult
BASE            99   49.5%  1.390  +28.4%   7.01%   2.00×
TRAIL-A         99   44.0%  1.520  +35.2%   8.10%   2.61×
TRAIL-B         99   46.0%  1.480  +33.1%   7.80%   2.44×
TRAIL-C         99   41.0%  1.410  +29.8%   9.20%   2.71×
HYBRID          99   48.0%  1.550  +37.4%   7.50%   2.35×

Trades que superaron el 2:1 original: 41/99 (41.4%)
Avg múltiplo en esos trades: 3.2×
```

---

## Notas de implementación

- El ATR del trailing debe calcularse en 15m (mismo frame de la entrada), no en 1h.
- El trailing_sl nunca se mueve en dirección contraria al trade (solo sube para longs, solo baja para shorts).
- Si el trailing está activo y el precio toca el SL original antes de activarse el trailing,
  cierra por SL normal — el trailing no cambia el SL de entrada.
- Compatibilidad con break-even stop existente: el trailing reemplaza el BE stop una vez activo.

---

## Referencias

- EXP019 base PF: BTC 1.390 / ETH 1.386
- EXP021 walk-forward combinado: W1 1.769, W2 1.284, W3 1.051, W4 1.265
