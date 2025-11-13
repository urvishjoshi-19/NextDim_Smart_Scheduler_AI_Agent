#!/bin/bash

# Smart Scheduler Voice Server Startup Script
# This script configures SSL certificates and starts the FastAPI server

cd "$(dirname "$0")"

echo "🚀 Starting Smart Scheduler Voice Server..."
echo ""

# Activate virtual environment
source venv/bin/activate

# Set SSL certificate paths for macOS compatibility
export SSL_CERT_FILE=$(python -m certifi)
export REQUESTS_CA_BUNDLE=$(python -m certifi)

echo "✅ SSL certificates configured"
echo "   Certificate path: $SSL_CERT_FILE"
echo ""

# Start the server
echo "🎙️  Starting server with voice integration..."
echo "   Server URL: http://localhost:8000"
echo ""
echo "Press CTRL+C to stop the server"
echo "----------------------------------------"

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

