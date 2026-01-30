#!/bin/bash
# Setup script for GAPI

echo "🎮 GAPI Setup Script"
echo "===================="
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed."
    echo "Please install Python 3.6 or higher and try again."
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
pip3 install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "❌ Error: Failed to install dependencies."
    exit 1
fi

echo "✅ Dependencies installed successfully"
echo ""

# Create config file if it doesn't exist
if [ ! -f config.json ]; then
    echo "📝 Creating config.json from template..."
    cp config_template.json config.json
    echo "✅ Config file created"
    echo ""
    echo "⚠️  IMPORTANT: Please edit config.json and add your Steam credentials:"
    echo "   - Steam API Key: https://steamcommunity.com/dev/apikey"
    echo "   - Steam ID: https://steamid.io/"
else
    echo "ℹ️  config.json already exists, skipping creation"
fi

echo ""
echo "🎉 Setup complete! Run 'python3 gapi.py' to start."
