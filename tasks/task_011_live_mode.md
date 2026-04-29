# Task 011 — Modo live en paper_monitor.py (`--live` flag)

**Prioridad:** 4
**Estado:** ⬜ PENDIENTE
**Archivo:** `paper_monitor.py` (modificación)
**Depende de:** Task 008 (notificaciones) + Task 010 (LiveEngine)

---

## Objetivo

Añadir un flag `--live` a `paper_monitor.py` que use `LiveEngine` en lugar de
`PaperEngine`, sin modificar la lógica de señales. El código de scan no debe saber
si está en modo paper o live.

---

## Cambio en `main()`

```python
parser.add_argument('--live', action='store_true',
                    help='Execute real orders on Binance (USE WITH CAUTION)')

if args.live:
    from core.live_engine import LiveEngine
    engines = {
        asset: LiveEngine(
            exchange=exchange,
            asset=asset,
            state_file=cfg['state_file'],
            leverage=1,
        )
        for asset, cfg in ASSETS_CONFIG.items()
    }
    print("⚠️  MODO LIVE ACTIVO — órdenes reales en Binance")
else:
    engines = {
        asset: PaperEngine(state_file=cfg['state_file'])
        for asset, cfg in ASSETS_CONFIG.items()
    }
```

---

## Safeguards adicionales en modo live

```python
# Al iniciar modo live: confirmar manualmente
if args.live:
    equity = engines['BTC/USDT'].equity
    confirm = input(f"Equity real: ${equity:.2f}. Confirmar modo live [s/N]: ")
    if confirm.lower() != 's':
        print("Abortado.")
        sys.exit(0)
```

---

## Logs separados para live

```python
log_prefix = 'live' if args.live else 'paper'
# btc_live_YYYYMMDD.log vs btc_paper_YYYYMMDD.log
log_file = f'logs/{cfg["log_prefix"]}_{log_prefix}_{log_date}.log'
```

---

## Estado separado para live

```python
'state_file': 'btc_live_state.json' if args.live else 'btc_state.json'
```

Paper y live pueden correr en paralelo en el mismo servidor, con estados y logs
totalmente separados. El paper sigue corriendo como referencia.

---

## Criterios de go-live

Antes de activar `--live` en producción:
- [ ] Task 008 ✅ (notificaciones WhatsApp funcionando)
- [ ] Task 009 ✅ (capital mínimo y modalidad confirmados)
- [ ] Task 010 ✅ (LiveEngine testeado en Binance testnet 48h)
- [ ] Saldo real en Binance cargado
- [ ] API key con permisos de trading (no solo lectura)

---

## Rollback plan

Si algo va mal en live:
1. Matar el proceso (`Ctrl+C` o `kill`)
2. Las órdenes SL/TP quedan activas en Binance — el exchange las gestiona
3. Cancelar manualmente en la UI de Binance si es necesario
4. Nunca borrar `btc_live_state.json` sin verificar primero la posición en Binance
