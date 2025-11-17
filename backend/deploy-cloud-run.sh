#!/bin/bash

# Smart Scheduler AI - Cloud Run Deployment Script
# This script deploys the backend to Google Cloud Run

set -e  # Exit on error

echo "========================================="
echo "   Smart Scheduler AI - Cloud Run Deploy"
echo "========================================="
echo ""

# Configuration
PROJECT_ID="uwmodel"
SERVICE_NAME="smart-scheduler-ai"
REGION="us-central1"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Step 1: Verify you're logged in
echo "✓ Verifying Google Cloud authentication..."
gcloud auth list --filter=status:ACTIVE --format="value(account)" || {
    echo "❌ Not logged in. Run: gcloud auth login"
    exit 1
}

# Step 2: Set project
echo "✓ Setting project to ${PROJECT_ID}..."
gcloud config set project ${PROJECT_ID}

# Step 3: Enable required APIs
echo "✓ Enabling required Google Cloud APIs..."
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable containerregistry.googleapis.com

# Step 4: Build the Docker image with Cloud Build
echo ""
echo "========================================="
echo "📦 Building Docker image..."
echo "========================================="
gcloud builds submit --tag ${IMAGE_NAME} .

# Step 5: Deploy to Cloud Run
echo ""
echo "========================================="
echo "🚀 Deploying to Cloud Run..."
echo "========================================="

# Read environment variables from .env file
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    exit 1
fi

# Deploy with environment variables from .env
# Exclude: GOOGLE_APPLICATION_CREDENTIALS, ENVIRONMENT, FRONTEND_URL, PORT, HOST (Cloud Run sets these)
ENV_VARS=$(cat .env | grep -v '^#' | grep -v '^$' | grep -v 'GOOGLE_APPLICATION_CREDENTIALS' | grep -v 'ENVIRONMENT' | grep -v 'FRONTEND_URL' | grep -v '^PORT' | grep -v '^HOST' | tr '\n' ',' | sed 's/,$//')

gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME} \
    --platform managed \
    --region ${REGION} \
    --allow-unauthenticated \
    --port 8000 \
    --memory 1Gi \
    --cpu 1 \
    --timeout 300 \
    --max-instances 10 \
    --set-env-vars="${ENV_VARS},ENVIRONMENT=production,FRONTEND_URL=https://nextdimensionai.vercel.app" \
    --quiet

# Step 6: Get the service URL
echo ""
echo "========================================="
echo "✅ Deployment Complete!"
echo "========================================="
echo ""

SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region ${REGION} \
    --format='value(status.url)')

echo "🌐 Your API is now live at:"
echo "   ${SERVICE_URL}"
echo ""
echo "📝 IMPORTANT NEXT STEPS:"
echo ""
echo "1. Test your deployment:"
echo "   curl ${SERVICE_URL}/health"
echo ""
echo "2. Update OAuth Redirect URIs in Google Cloud Console:"
echo "   → Go to: https://console.cloud.google.com/apis/credentials"
echo "   → Click your OAuth 2.0 Client ID"
echo "   → Add these Authorized redirect URIs:"
echo "      ${SERVICE_URL}/auth/callback"
echo "      http://localhost:8000/auth/callback (keep for local dev)"
echo ""
echo "3. Update your frontend to use the new backend URL:"
echo "   → In frontend/components/VoiceAssistant.tsx"
echo "   → Change WebSocket URL to: ${SERVICE_URL}/ws/voice/{user_id}"
echo ""
echo "4. Test OAuth login:"
echo "   ${SERVICE_URL}/auth/login"
echo ""
echo "========================================="
echo ""

