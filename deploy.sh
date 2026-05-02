#!/bin/bash
set -e

# ========= CONFIG =========
PROJECT_ID=$(gcloud config get-value project)
REGION=europe-west1
SERVICE_NAME=investmentbot
REPOSITORY=investmentbot
IMAGE_NAME=investmentbot
IMAGE_URI="us-central1-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$IMAGE_NAME:latest"
SERVICE_ACCOUNT="investmentbot-sa@$PROJECT_ID.iam.gserviceaccount.com"
# GCS bucket for persisting paper_state.json and logs across restarts.
# Create once: gsutil mb -l europe-west1 gs://$GCS_BUCKET
# Grant access: gsutil iam ch serviceAccount:$SERVICE_ACCOUNT:roles/storage.objectAdmin gs://$GCS_BUCKET
GCS_BUCKET="investmentbot-state-$PROJECT_ID"

echo "=============================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Service: $SERVICE_NAME"
echo "Image: $IMAGE_URI"
echo "=============================="

# ========= BUILD =========
echo "🚀 Building Docker image..."
gcloud builds submit --tag "$IMAGE_URI"

# ========= DEPLOY =========
echo "☁️ Deploying to Cloud Run (Europe)..."
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE_URI" \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account="$SERVICE_ACCOUNT" \
  --set-secrets BINANCE_API_KEY=binance-api-key:latest,TWILIO_ACCOUNT_SID=twilio-account-sid:latest,TWILIO_AUTH_TOKEN=twilio-auth-token:latest,/app/binance_private.pem=binance-private-key:latest \
  --set-env-vars GCS_BUCKET="$GCS_BUCKET",LIVE_TRADING=1,TWILIO_WHATSAPP_FROM="whatsapp:+14155238886",TWILIO_WHATSAPP_TO="whatsapp:+5493412293382" \
  --memory=512Mi \
  --cpu=1 \
  --timeout=300 \
  --concurrency=1 \
  --min-instances=1 \
  --max-instances=1

# ========= OUTPUT =========
URL=$(gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --format='value(status.url)')

echo "=============================="
echo "✅ Deploy terminado"
echo "🌐 URL: $URL"
echo "=============================="