#!/bin/bash

# Smart Scheduler AI Agent - Backend Setup Script

echo "🚀 Setting up Smart Scheduler AI Agent Backend"
echo "================================================"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check Python version
echo -e "\n${YELLOW}Checking Python version...${NC}"
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Create virtual environment
echo -e "\n${YELLOW}Creating virtual environment...${NC}"
python3 -m venv venv

# Activate virtual environment
echo -e "\n${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate

# Upgrade pip
echo -e "\n${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip

# Install dependencies
echo -e "\n${YELLOW}Installing dependencies...${NC}"
pip install -r requirements.txt

# Check for .env file
if [ ! -f .env ]; then
    echo -e "\n${RED}⚠️  .env file not found!${NC}"
    echo "Creating .env from .env.example..."
    
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${YELLOW}Please update the .env file with your actual credentials:${NC}"
        echo "  - GOOGLE_CLIENT_ID"
        echo "  - GOOGLE_CLIENT_SECRET"
        echo "  - (API keys are already set)"
    else
        echo -e "${RED}ERROR: .env.example not found${NC}"
        exit 1
    fi
else
    echo -e "\n${GREEN}✓ .env file found${NC}"
fi

# Check for OAuth credentials
if [ ! -f client_secret.json ]; then
    echo -e "\n${RED}⚠️  client_secret.json not found!${NC}"
    echo -e "${YELLOW}You need to:${NC}"
    echo "1. Go to Google Cloud Console: https://console.cloud.google.com/apis/credentials"
    echo "2. Create OAuth 2.0 Client ID"
    echo "3. Download JSON and save as 'client_secret.json' in this directory"
fi

# Create tokens directory
echo -e "\n${YELLOW}Creating tokens directory...${NC}"
mkdir -p tokens

echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}✓ Backend setup complete!${NC}"
echo -e "${GREEN}================================================${NC}"

echo -e "\n${YELLOW}Next steps:${NC}"
echo "1. Update .env with your Google OAuth credentials"
echo "2. Download client_secret.json from Google Cloud Console"
echo "3. Run: python -m app.main"

echo -e "\n${YELLOW}To activate the virtual environment later:${NC}"
echo "source venv/bin/activate"

