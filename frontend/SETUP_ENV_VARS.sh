#!/bin/bash

# Quick script to set Vercel environment variables

echo "🔧 Setting up environment variables for Vercel..."
echo ""

# Set API URL
echo "Setting NEXT_PUBLIC_API_URL..."
vercel env add NEXT_PUBLIC_API_URL production <<EOF
https://smart-scheduler-ai-lhorvsygpa-uc.a.run.app
EOF

echo ""

# Set WebSocket URL  
echo "Setting NEXT_PUBLIC_WS_URL..."
vercel env add NEXT_PUBLIC_WS_URL production <<EOF
wss://smart-scheduler-ai-lhorvsygpa-uc.a.run.app
EOF

echo ""
echo "✅ Environment variables set!"
echo ""
echo "Now redeploying to production with new variables..."
vercel --prod

echo ""
echo "✅ All done! Your app is now fully configured."

