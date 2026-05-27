#!/bin/bash
# Setup script for GAPI

echo "🎮 GAPI Setup Script"
echo "===================="
echo ""

# Check if Python 3.8+ is installed
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed."
    echo "Please install Python 3.8 or higher from https://www.python.org/downloads/"
    exit 1
fi

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]; }; then
    echo "❌ Error: Python 3.8+ is required (found Python $PYTHON_VERSION)."
    echo "Please install Python 3.8 or higher from https://www.python.org/downloads/"
    exit 1
fi

echo "✅ Python $PYTHON_VERSION found"
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
    echo "⚠️  RECOMMENDATION: Use a virtual environment to keep dependencies isolated."
    echo ""
    echo "   python3 -m venv venv"
    echo "   source venv/bin/activate        # Linux / macOS"
    echo "   venv\\Scripts\\activate.bat       # Windows (CMD)"
    echo "   venv\\Scripts\\Activate.ps1       # Windows (PowerShell)"
    echo ""
    read -p "Continue with system-wide installation? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "Tip: Create and activate a venv first, then re-run setup.sh."
        exit 0
    fi
fi

# Choose install variant
echo ""
echo "📦 Install variant:"
echo "   1) Core + optional features  (recommended — requirements.txt)"
echo "   2) Full — includes GOG Galaxy (requirements-full.txt)"
echo ""
read -p "Choose [1/2, default=1]: " -n 1 -r INSTALL_CHOICE
echo ""

if [[ "$INSTALL_CHOICE" == "2" ]]; then
    REQUIREMENTS_FILE="requirements-full.txt"
else
    REQUIREMENTS_FILE="requirements.txt"
fi

echo "📦 Installing from $REQUIREMENTS_FILE ..."
PIP_INSTALL_ARGS=(-r "$REQUIREMENTS_FILE")
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  System-wide install requested; using --break-system-packages for PEP 668 environments."
    PIP_INSTALL_ARGS=(--break-system-packages "${PIP_INSTALL_ARGS[@]}")
fi

python3 -m pip install "${PIP_INSTALL_ARGS[@]}"

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
    echo "⚠️  IMPORTANT: Edit config.json and add your credentials:"
    echo "   • Steam API Key : https://steamcommunity.com/dev/apikey"
    echo "   • Steam ID (64-bit): https://steamid.io/"
    echo "   • Discord Bot Token (optional): https://discord.com/developers/applications"
else
    echo "ℹ️  config.json already exists — skipping creation"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "🎉  Setup complete!"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  Try the demo (no credentials required):"
echo "    python3 scripts/demo.py"
echo ""
echo "  Start the Web GUI:"
echo "    python3 gapi_gui.py"
echo "    Open http://127.0.0.1:5000 → Register → add Steam ID"
echo ""
echo "  Start the CLI:"
echo "    python3 gapi.py"
echo ""
echo "  Full installation guide: README.md → Installation section"
echo ""
echo "  Optional systemd install (Linux):"
echo "    sudo install -m 644 systemd/gapi.service /etc/systemd/system/gapi.service"
echo "    sudo install -m 644 systemd/gapi-watch.service /etc/systemd/system/gapi-watch.service"
echo "    sudo install -m 644 systemd/gapi-watch.path /etc/systemd/system/gapi-watch.path"
echo "    sudo systemctl daemon-reload && sudo systemctl enable --now gapi.service gapi-watch.path"
echo "════════════════════════════════════════════════════════"
