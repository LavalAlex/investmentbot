# Task 006 — Sistema combinado DYN-B + TIME-B

**Prioridad:** 1  
**Estado:** ✅ APROBADO — COMBINED (DYN-B + TIME-B) es acumulativo en ambos assets  
**Archivo backtest:** `backtest/backtest_task006.py`  
**Depende de:** Task 002 (DYN-B ✅) + Task 004 (TIME-B ✅)

---

## Contexto

Task 002 (Dynamic Sizing DYN-B) y Task 004 (Time Filter TIME-B) pasaron individualmente.
Esta task verifica que el efecto es **acumulativo** cuando se combinan ambas mejoras.

Resultados individuales sobre 730d:

| Mejora | BTC PF | ETH PF | BTC MaxDD | ETH MaxDD |
|--------|--------|--------|-----------|-----------|
| BASE (EXP019) | 1.344 | 1.318 | 7.01% | 13.38% |
| + DYN-B solo | 1.411 | 1.378 | 6.54% | 13.52% |
| + TIME-B solo | 1.729 | 1.422 | 6.82% | 7.73% |
| + DYN-B + TIME-B | ??? | ??? | ??? | ??? |

El riesgo es que las dos mejoras se solapen en su efecto (las mismas barras malas
se eliminan o reducen con ambos filtros). El objetivo es confirmar que el PF combinado
es mayor que cualquiera de los dos por separado.

---

## Fundamento

DYN-B y TIME-B actúan sobre dimensiones distintas:
- **TIME-B** filtra entradas en horas de baja liquidez (elimina trades)
- **DYN-B** escala el tamaño de los trades que sí se toman (modifica el sizing)

No deberían solaparse — son ortogonales. Pero hay que verificarlo empíricamente.

---

## Diseño del experimento

### Variantes

| Variante | Filtros activos | Descripción |
|----------|----------------|-------------|
| BASE | SLOPE_CAP | EXP019 referencia |
| DYN-B | SLOPE_CAP + sizing 0.6–1.2× | Task 002 resultado |
| TIME-B | SLOPE_CAP + horas 07–21 UTC | Task 004 resultado |
| COMBINED | SLOPE_CAP + DYN-B + TIME-B | El sistema completo |

### Implementación

Combinar `backtest_task002.py` y `backtest_task004.py`:

```python
# En cada barra de entrada:

# 1. Time filter (TIME-B)
hour = row['open_time'].hour
if not (7 <= hour < 21):
    continue

# 2. Entry signal (igual que siempre)
# ... todos los filtros de pullback ...

# 3. Dynamic sizing (DYN-B)
atr_ratio = row.get('atr_ratio', 1.0)
scale = max(0.6, min(1.2, 1.0 / atr_ratio))
risk_usd = equity * 0.01 * scale
```

---

## Criterios de éxito (KEEP el sistema combinado)

- PF(COMBINED) > PF(TIME-B) en ambos assets → DYN-B añade valor sobre TIME-B
- PF(COMBINED) > PF(DYN-B) en ambos assets → TIME-B añade valor sobre DYN-B
- Walk-forward combinado BTC+ETH: PF ≥ 1.0 en las 4 ventanas
- MaxDD ≤ 8% en BTC, ≤ 12% en ETH

## Criterios de fracaso (usar solo TIME-B)

- PF(COMBINED) ≈ PF(TIME-B) → DYN-B no añade nada cuando TIME-B ya filtra las horas malas
  → Adoptar solo TIME-B como mejora única

## Criterio para ITERAR

- El COMBINED mejora BTC pero no ETH → aplicar DYN-B solo a BTC

---

## Output esperado

```
=== TASK006 — DYN-B + TIME-B ===
Variante   BTC_PF   ETH_PF  BTC_DD%  ETH_DD%  BTC_Ret%  ETH_Ret%
BASE        1.344    1.318    7.01    13.38     +26.0     +26.8
DYN-B       1.411    1.378    6.54    13.52     +31.9     +33.3
TIME-B      1.729    1.422    6.82     7.73     +35.0     +20.5
COMBINED    X.XXX    X.XXX    X.XX     X.XX     +XX.X     +XX.X

Walk-forward combinado BTC+ETH:
W1 Bull 2024       BASE:1.769  COMBINED:X.XXX
W2 ATH 2024-25     BASE:1.278  COMBINED:X.XXX
W3 Recovery 2025   BASE:1.034  COMBINED:X.XXX  ← ventana crítica
W4 Bear 2025-26    BASE:1.244  COMBINED:X.XXX
```

---

## Referencias

- `backtest/backtest_task002.py` → DYN-B implementation
- `backtest/backtest_task004.py` → TIME-B implementation
- `data/backtest_task002.json` → resultados DYN-B
- `data/backtest_task004.json` → resultados TIME-B
