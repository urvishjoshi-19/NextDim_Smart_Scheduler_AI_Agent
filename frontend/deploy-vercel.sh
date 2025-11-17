#!/bin/bash

# Vercel Deployment Script for NextDimension AI Frontend
# This script automates the deployment process

set -e  # Exit on any error

echo "🚀 NextDimension AI - Vercel Deployment"
echo "========================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if vercel CLI is installed
if ! command -v vercel &> /dev/null; then
    echo -e "${YELLOW}⚠️  Vercel CLI not found. Installing...${NC}"
    npm install -g vercel
    echo -e "${GREEN}✅ Vercel CLI installed${NC}"
fi

echo -e "${BLUE}📍 Current directory: $(pwd)${NC}"
echo ""

# Check if we're in the frontend directory
if [[ ! -f "package.json" ]]; then
    echo -e "${YELLOW}⚠️  Not in frontend directory. Changing directory...${NC}"
    cd frontend
fi

echo -e "${GREEN}✅ In frontend directory${NC}"
echo ""

# Check if user is logged in to Vercel
echo -e "${BLUE}🔐 Checking Vercel authentication...${NC}"
if ! vercel whoami &> /dev/null; then
    echo -e "${YELLOW}⚠️  Not logged in to Vercel${NC}"
    echo -e "${BLUE}Opening browser for authentication...${NC}"
    vercel login
else
    echo -e "${GREEN}✅ Already logged in to Vercel$(NC)"
fi

echo ""
echo -e "${BLUE}📦 Building and deploying to Vercel...${NC}"
echo ""

# Deploy to preview first
echo -e "${YELLOW}Deploying to preview environment...${NC}"
vercel

echo ""
echo -e "${GREEN}✅ Preview deployment complete!${NC}"
echo ""
echo -e "${YELLOW}⚙️  Now we need to set environment variables for production${NC}"
echo ""

# Ask user if they want to set environment variables
read -p "Do you want to set environment variables now? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Setting NEXT_PUBLIC_API_URL...${NC}"
    echo "https://smart-scheduler-ai-lhorvsygpa-uc.a.run.app" | vercel env add NEXT_PUBLIC_API_URL production
    
    echo -e "${BLUE}Setting NEXT_PUBLIC_WS_URL...${NC}"
    echo "wss://smart-scheduler-ai-lhorvsygpa-uc.a.run.app" | vercel env add NEXT_PUBLIC_WS_URL production
    
    echo -e "${GREEN}✅ Environment variables set${NC}"
fi

echo ""
echo -e "${YELLOW}🚀 Deploying to production...${NC}"
read -p "Deploy to production now? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    vercel --prod
    
    echo ""
    echo -e "${GREEN}✅✅✅ DEPLOYMENT COMPLETE! ✅✅✅${NC}"
    echo ""
    echo -e "${BLUE}Your app is live! Check the URL above.${NC}"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "1. Open the production URL in your browser"
    echo "2. Test the voice assistant"
    echo "3. Share with friends!"
else
    echo -e "${YELLOW}Skipped production deployment. Run 'vercel --prod' when ready.${NC}"
fi

echo ""
echo -e "${GREEN}✨ All done!${NC}"

