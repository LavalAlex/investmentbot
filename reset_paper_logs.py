"""
Reset del entorno de paper trading a estado inicial limpio.

Acciones:
  1. Escribe btc_state.json y eth_state.json frescos (equity=10 000, sin posiciones)
  2. Sube los state files a GCS para que Cloud Run los levante correctos
  3. Elimina los logs locales (logs/btc_*.log, logs/eth_*.log, logs/logs_paper_*.log)
  4. Elimina los logs de GCS (prefijo logs/)

Requisito: correr con el monitor DETENIDO (no durante un scan activo).

Uso:
    python reset_paper_logs.py           # reset completo
    python reset_paper_logs.py --dry-run # muestra qué haría sin ejecutar
"""

import argparse
import json
import os
import sys
from pathlib import Path

INITIAL_EQUITY = 10_000.0

STATE_FILES = ['btc_state.json', 'eth_state.json']
LOGS_DIR    = Path('logs')

FRESH_STATE = {
    'equity':                INITIAL_EQUITY,
    'positions':             {},
    'trades':                [],
    'cb_consecutive_losses': 0,
    'cb_until':              None,
    'last_trade_close_ts':   None,
}

LOG_PREFIXES = ('btc_', 'eth_', 'logs_paper_')


def _gcs_bucket():
    bucket_name = os.getenv('GCS_BUCKET', '')
    if not bucket_name:
        return None, None
    try:
        from google.cloud import storage
        client = storage.Client()
        return client.bucket(bucket_name), bucket_name
    except Exception as e:
        print(f"  [GCS] No se pudo conectar al bucket: {e}")
        return None, None


def reset(dry_run: bool) -> None:
    tag = '[DRY-RUN] ' if dry_run else ''

    # ── 1. State files locales ─────────────────────────────────────────────────
    print("\n[1/3] State files locales")
    for fname in STATE_FILES:
        path = Path(fname)
        if dry_run:
            print(f"  {tag}escribiría: {fname}  (equity={INITIAL_EQUITY:.0f})")
        else:
            with open(path, 'w') as f:
                json.dump(FRESH_STATE, f, indent=2)
            print(f"  reset   : {fname}  (equity={INITIAL_EQUITY:.0f})")

    # ── 2. State files → GCS ───────────────────────────────────────────────────
    print("\n[2/3] Subiendo state files a GCS")
    bucket, bucket_name = _gcs_bucket()
    if bucket is None:
        print("  SKIP: GCS_BUCKET no configurado — sube manualmente si es necesario")
    else:
        for fname in STATE_FILES:
            if dry_run:
                print(f"  {tag}subiría: gs://{bucket_name}/{fname}")
            else:
                try:
                    bucket.blob(fname).upload_from_filename(fname)
                    print(f"  subido  : gs://{bucket_name}/{fname}")
                except Exception as e:
                    print(f"  ERROR   : {fname} → {e}")

        # Eliminar logs de GCS
        if dry_run:
            print(f"  {tag}eliminaría blobs con prefijo: gs://{bucket_name}/logs/")
        else:
            try:
                blobs = list(bucket.list_blobs(prefix='logs/'))
                for blob in blobs:
                    blob.delete()
                    print(f"  borrado : gs://{bucket_name}/{blob.name}")
                if not blobs:
                    print("  (no había logs en GCS)")
            except Exception as e:
                print(f"  ERROR   : al borrar logs de GCS → {e}")

    # ── 3. Logs locales ────────────────────────────────────────────────────────
    print("\n[3/3] Logs locales")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    removed = 0
    for fname in sorted(LOGS_DIR.iterdir()):
        if fname.is_file() and any(fname.name.startswith(p) for p in LOG_PREFIXES):
            if dry_run:
                print(f"  {tag}borraría: {fname}")
            else:
                fname.unlink()
                print(f"  borrado : {fname}")
            removed += 1
    if removed == 0:
        print("  (no había logs locales)")

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Reset completado.")
    if not dry_run:
        print("  Inicia el monitor con: python paper_monitor.py --loop")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Reset paper trading al estado inicial')
    parser.add_argument('--dry-run', action='store_true',
                        help='Muestra qué haría sin ejecutar ningún cambio')
    args = parser.parse_args()

    if not args.dry_run:
        confirm = input(
            "\n⚠  Esto borrará trades, logs y reseteará equity a 10 000 USD.\n"
            "   ¿Continuar? [s/N] "
        ).strip().lower()
        if confirm != 's':
            print("Cancelado.")
            sys.exit(0)

    reset(dry_run=args.dry_run)
