#!/bin/bash

PROJECT_ID=$(gcloud config get-value project)
REGION=us-central1
REPO=investmentbot
IMAGE=investmentbot

gcloud builds submit \
  --tag $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:latest

gcloud run deploy $IMAGE \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE:latest \
  --region $REGION \
  --allow-unauthenticated