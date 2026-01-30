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

# Check if pip is available
if ! python3 -m pip --version &> /dev/null; then
    echo "❌ Error: pip is not installed for Python 3."
    echo "Please install pip and try again."
    exit 1
fi

echo "✅ pip found: $(python3 -m pip --version)"
echo ""

# Recommend using virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  RECOMMENDATION: Consider using a virtual environment"
    echo "   python3 -m venv venv"
    echo "   source venv/bin/activate  # On Linux/Mac"
    echo "   venv\\Scripts\\activate     # On Windows"
    echo ""
    read -p "Continue with system-wide installation? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
fi

# Install dependencies
echo "📦 Installing dependencies..."
python3 -m pip install -r requirements.txt

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
