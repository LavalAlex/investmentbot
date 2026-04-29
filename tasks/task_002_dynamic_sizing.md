# Task 002 — Dynamic Position Sizing por Volatilidad

**Prioridad:** 2  
**Estado:** ⬜ PENDIENTE  
**Archivo backtest:** `backtest/backtest_task002.py`  
**Depende de:** sistema base EXP019 + resultado de Task 001 (si KEEP)

---

## Fundamento

El sistema actual arriesga siempre el 1% del equity por trade, independientemente de las
condiciones del mercado. Esto es correcto como baseline, pero tiene una implicación
importante: en períodos de alta volatilidad, los SLs son más grandes en términos absolutos
(el ATR es mayor), lo que significa que el drawdown en esos períodos es mayor.

Inversamente, en períodos de baja volatilidad el sistema funciona correctamente pero con
posiciones que podrían ser proporcionalmente más grandes sin aumentar el riesgo real.

El concepto de **volatility targeting** es estándar en fondos cuantitativos:
la idea es mantener la volatilidad del equity curve constante, no el riesgo nominal.
Esto suaviza el equity curve sin cambiar la lógica de entrada.

El ATR ratio (ATR actual / ATR media histórica) es exactamente la señal que mide esto.
Ya lo calculamos en EXP019 (aunque decidimos no usarlo como filtro de entrada).
Aquí lo reutilizamos para escalar el tamaño de posición.

---

## Tesis

> Reducir el tamaño de posición cuando la volatilidad está por encima de su promedio
> histórico, y mantenerlo (o aumentarlo ligeramente) cuando está por debajo, produce
> el mismo PF pero con menor MaxDD y menor volatilidad del equity curve.
> El retorno absoluto puede bajar ligeramente, pero el retorno ajustado por riesgo mejora.

El objetivo no es maximizar el retorno total — es maximizar el Sharpe ratio
(retorno / desviación estándar del equity).

---

## Diseño del experimento

### Fórmula de sizing

```python
ATR_RATIO = ATR(14) / rolling_mean(ATR(14), 50)   # ya calculado en EXP019

# Factor de escala: inverso del ATR ratio, con límites
scale = clamp(1.0 / ATR_RATIO, min=0.5, max=1.5)

# Position size final
risk_usd = equity * RISK_PCT * scale
qty = risk_usd / risk_price
```

Ejemplos:
- ATR_ratio = 2.0 (doble de lo normal) → scale = 0.5 → arriesga 0.5% del equity
- ATR_ratio = 1.0 (normal) → scale = 1.0 → arriesga 1.0% del equity
- ATR_ratio = 0.7 (bajo) → scale = 1.43 → arriesga 1.43% del equity (capped en 1.5%)

### Variantes a testear

| Variante | Scale min | Scale max | Descripción |
|----------|-----------|-----------|-------------|
| BASE | 1.0 | 1.0 | Sizing fijo 1% (referencia) |
| DYN-A | 0.5 | 1.5 | Rango amplio — agresivo |
| DYN-B | 0.6 | 1.2 | Rango moderado — conservador |
| DYN-C | 0.5 | 1.0 | Solo reduce, nunca aumenta |

DYN-C es la variante más conservadora: solo protege en alta volatilidad, no aumenta
en baja. Es la que tiene menos riesgo de introducir overfitting.

---

## Métricas clave a comparar

Además de PF y MaxDD, calcular:

```
Sharpe ratio = (Return anualizado - 0%) / Std(retornos mensuales)
Calmar ratio = Return anualizado / MaxDD
```

Si el PF es igual pero el Sharpe y Calmar mejoran, la task es exitosa.

---

## Criterios de éxito (KEEP)

- MaxDD se reduce ≥ 2pp sobre BASE sin que el PF baje más de 0.05, O
- Sharpe ratio mejora ≥ 15% sobre BASE
- Walk-forward: PF combinado sigue ≥ 1.0 en las 4 ventanas

## Criterios de fracaso (REVERT)

- PF baja más de 0.10 (el sizing dinámico daña demasiado los trades buenos)
- MaxDD no mejora (la volatilidad no es el driver del drawdown — el edge lo es)

## Criterio para ITERAR

- Mejora en MaxDD pero reduce demasiado el return → ajustar los límites min/max del scale

---

## Output esperado del script

```
=== BTC TASK002 — Dynamic Sizing ===
Variante  Trades  PF     Return   MaxDD   Sharpe  Calmar
BASE        99   1.390  +28.4%   7.01%   1.42    4.05
DYN-A       99   1.365  +24.1%   4.80%   1.71    5.02   ← menor return, mejor Sharpe
DYN-B       99   1.375  +26.2%   5.50%   1.58    4.76
DYN-C       99   1.382  +27.0%   5.90%   1.51    4.58
```

---

## Notas de implementación

- ATR_ratio se calcula sobre 1h (consistente con EXP019).
- El ATR_mean(50) requiere ~50 horas de warmup antes de tener valores estables.
- El scale se aplica al risk_usd, no directamente a qty — así el riesgo nominal
  en dólares cambia pero la lógica SL/TP no cambia.
- Loguear el scale aplicado en cada trade para diagnóstico.

---

## Referencias

- ATR ratio ya calculado en `backtest/backtest_exp019.py` → función `add_volatility_filters()`
- EXP019 BASE: BTC PF 1.390 MaxDD 7.01% / ETH PF 1.386 MaxDD 13.38%
