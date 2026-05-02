#!/bin/bash
set -e

PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
REGION=europe-west1
SERVICE_NAME=investmentbot
GCS_BUCKET="investmentbot-state-${PROJECT_ID}"
DEST_DIR="./logs_remote"
DAYS=${1:-7}

mkdir -p "$DEST_DIR"

echo "=============================="
echo "Project : $PROJECT_ID"
echo "Bucket  : gs://$GCS_BUCKET"
echo "Dest    : $DEST_DIR"
echo "=============================="

# --- 1. State files (btc/eth) ---
echo ""
echo "[1/3] Descargando state files..."
gsutil -m cp \
  "gs://${GCS_BUCKET}/btc_state.json" \
  "gs://${GCS_BUCKET}/eth_state.json" \
  "gs://${GCS_BUCKET}/paper_state.json" \
  . 2>/dev/null && echo "  OK: state files" || echo "  WARN: algún state file no existe en GCS"

# --- 2. Logs desde GCS ---
echo ""
echo "[2/3] Descargando logs desde GCS..."
gsutil -m cp "gs://${GCS_BUCKET}/logs/logs_paper_*.log" "$DEST_DIR/" 2>/dev/null \
  && echo "  OK: logs de GCS" \
  || echo "  WARN: no hay logs en gs://${GCS_BUCKET}/logs/"

# --- 3. Logs recientes desde Cloud Logging ---
echo ""
echo "[3/3] Exportando Cloud Logging (últimos ${DAYS}d)..."
START_TIME=$(date -u -d "${DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
          || date -u -v-${DAYS}d +%Y-%m-%dT%H:%M:%SZ)  # macOS fallback

gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE_NAME}" \
  --project="$PROJECT_ID" \
  --freshness="${DAYS}d" \
  --format="value(timestamp,textPayload)" \
  --order=asc \
  > "${DEST_DIR}/cloudrun_last${DAYS}d.log"

LINES=$(wc -l < "${DEST_DIR}/cloudrun_last${DAYS}d.log")
echo "  OK: ${LINES} líneas → ${DEST_DIR}/cloudrun_last${DAYS}d.log"

# --- Resumen rápido ---
echo ""
echo "=============================="
echo "Estado del servicio:"
gcloud run services describe "$SERVICE_NAME" \
  --region="$REGION" \
  --format="table(status.conditions[0].type, status.conditions[0].status, status.conditions[0].lastTransitionTime)" \
  2>/dev/null || echo "  WARN: no se pudo obtener estado del servicio"

echo ""
echo "Últimas 5 líneas de log:"
tail -5 "${DEST_DIR}/cloudrun_last${DAYS}d.log" 2>/dev/null || echo "  (vacío)"
echo "=============================="
