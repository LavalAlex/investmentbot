# Sesión 2026-05-02 — Diagnóstico post-deploy_004 + Herramientas de operación

## Contexto

Primera sesión de monitoreo tras deploy_004 (2026-04-29, commit `c0a7080`).
El sistema llevaba 3 días sin generar trades. Se investigó la causa, se validó
la configuración actual y se agregaron herramientas de operación al servidor.

---

## 1. Diagnóstico — 0 trades post-deploy_004

### Síntoma

`logs_remote/cloudrun_last7d.log` (bajado vía `fetch_logs.sh`) mostró:

```
[BTC/USDT] SKIP slope_cap ema50_slope=24.805% > 0.20%   ← doble *100 en log
[ETH/USDT] SKIP time_b hour=21UTC outside 07–21
[ETH/USDT] SKIP sl_dist=0.383% < 0.50% (SL filter)
[ETH/USDT] SKIP eth_short_vol vol_ratio=0.79 < 1.0
```

BTC sin un solo trade. ETH idem. La causa dominante: `SLOPE_CAP`.

### Causa raíz

BTC está en rally sostenido (76k → 96k+). El EMA50 en 1h tiene un slope de
**0.22–0.32%** por encima del umbral de 0.20%, bloqueando 100% de las señales BTC.

### Task008 — Validación de alternativas (backtest 730d con fees)

`backtest/backtest_task008.py` — una variable a la vez: SLOPE_CAP on/off/relajado.

| Variante | BTC PF | ETH PF | 4 ventanas | Decisión |
|----------|--------|--------|-----------|---------|
| **PROD (cap=0.20%)** | **1.787** | **1.568** | ✅✅✅✅ | **KEEP** |
| NO_CAP | 1.150 | 1.064 | ✅✅✅✅ | ❌ FAIL PF |
| CAP_050 | 1.223 | 1.167 | ✅✅✅✅ | ❌ ETH < 1.2 |
| CAP_100 | 1.156 | 1.020 | ✅✅✅✅ | ❌ FAIL PF |

**Conclusión: el SLOPE_CAP de 0.20% es correcto.** Relajarlo destruye el PF,
especialmente en ETH. El sistema está funcionando como fue diseñado — 71 trades
en 730d = 1 cada ~10 días. En un bull market con slope persistentemente alto,
el filtro se activa correctamente y el sistema espera.

**Los 0 trades no son un bug.** Son la consecuencia esperada en el régimen actual.

### Walk-forward Task008 para referencia

| Ventana | PROD | NO_CAP | CAP_050 |
|---------|------|--------|---------|
| W1 Bull 2024 | 2.245 ✅ | 1.032 ✅ | 1.259 ✅ |
| W2 ATH 2024-25 | 1.738 ✅ | 1.070 ✅ | 1.163 ✅ |
| W3 Recovery 2025 | 1.483 ✅ | 1.137 ✅ | 1.137 ✅ |
| W4 Bear 2025-26 | 1.275 ✅ | 1.148 ✅ | 1.169 ✅ |

---

## 2. Estado del paper trading (pre-diagnóstico)

**paper_state.json descargado de GCS:**

| Asset | Equity | Trades | W/L | PnL |
|-------|--------|--------|-----|-----|
| BTC | — | 4 | 1W/3L | -100.93 |
| ETH | 9 768.33 | 10 | 3W/7L | -109.75 |
| **Combined** | **9 789.32** | **14** | **4W/10L** | **-210.68 USD** |

Posición abierta en BTC (long, entry 78 608, open desde Apr 26 23:30 UTC).
Nota: los 14 trades corresponden al período **antes** del deploy_004, sin SLOPE_CAP.
El WR de 28.6% y PnL negativo son consistentes con el PF < 1.2 que el SLOPE_CAP elimina.

---

## 3. Bug corregido — log message de SLOPE_CAP

En `paper_monitor.py` línea 181, `slope_pct` ya está en % pero el log multiplicaba
por 100 de nuevo, mostrando valores como `24.8%` cuando el slope real era `0.248%`.

```python
# Antes (incorrecto)
f"ema50_slope={slope_pct*100:.3f}% > 0.20%"

# Después (correcto)
f"ema50_slope={slope_pct:.3f}% > 0.20%"
```

La comparación en el código (`abs(slope_pct) > 0.20`) siempre fue correcta —
solo el display estaba mal. No afecta el comportamiento del sistema.

---

## 4. Herramientas de operación agregadas

### fetch_logs.sh (nuevo)

Script shell para bajar logs desde GCS y Cloud Logging a local.

```bash
./fetch_logs.sh        # últimos 7 días
./fetch_logs.sh 14     # últimos 14 días
```

Descarga: state files (btc/eth/paper), logs de GCS → `logs_remote/`,
logs de Cloud Logging → `logs_remote/cloudrun_last7d.log`. Muestra estado del servicio
y últimas 5 líneas al final.

### reset_paper_logs.py (actualizado)

El script original solo reseteaba `paper_state.json` (formato viejo). Ahora maneja
el sistema actual: `btc_state.json` + `eth_state.json`, sube a GCS, borra logs
locales y de GCS.

```bash
python reset_paper_logs.py --dry-run   # ver qué haría
python reset_paper_logs.py             # reset real (pide confirmación)
```

### POST /reset (nuevo endpoint en API)

Endpoint para resetear el server en caliente sin restart de Cloud Run.

```bash
curl -X POST https://<cloud-run-url>/reset
```

**Qué hace (atómico bajo lock):**
1. Espera a que termine el scan en curso
2. Llama `engine.reset()` en BTC y ETH → equity=10 000, posiciones vacías, trades []
3. Persiste a disco y sube a GCS
4. Borra todos los logs locales y de GCS

**Cambios de código:**
- `core/paper_engine.py` → método `reset()` agregado
- `api/main.py` → `_engines` y `_engines_lock` a nivel de módulo; monitor loop usa el lock; endpoint `POST /reset`

---

## 5. Deploy

Todos los cambios mergeados a `master` y subidos a Cloud Run europe-west1
con `./deploy.sh` (sin cambios al deploy script).

**Archivos modificados en esta sesión:**
```
paper_monitor.py              ← fix log slope_cap
core/paper_engine.py          ← método reset()
api/main.py                   ← POST /reset + _engines_lock
reset_paper_logs.py           ← soporte btc/eth state + GCS
fetch_logs.sh                 ← nuevo
backtest/backtest_task008.py  ← nuevo (diagnóstico SLOPE_CAP)
data/backtest_task008.json    ← resultados Task008
```

---

## 6. Próximos pasos

- **Seguir con V2:** el hecho de que el sistema tenga 0 trades en bull market fuerte
  motiva directamente **EXP018** (ADX filter como clasificador de régimen). En régimen
  tendencial con slope alto, Strategy A (pullback) debería tener reglas propias, no
  simplemente bloquearse.
- El SLOPE_CAP es un filtro de transición hacia V2, no un estado final.
- Próximo experimento: `backtest/backtest_exp018.py` — ver `experiments/v2_roadmap.md`.
