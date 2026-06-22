#!/bin/bash

# Setup script for Mellea Skills Compiler Node.js Wrapper
# This script installs dependencies and starts the CLI

set -e
clear
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                                                      ║"
echo "║       🔧 Mellea Skills Compiler                      ║"
echo "║          Interactive UI Setup                        ║"
echo "║                                                      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# Check Node.js version
echo "📋 Checking Node.js version..."
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed"
    echo "   Please install Node.js >= 18.0.0"
    echo "   Visit: https://nodejs.org/"
    exit 1
fi

NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Node.js version is too old: $(node --version)"
    echo "   Please upgrade to Node.js >= 18.0.0"
    exit 1
fi

echo "✅ Node.js version: $(node --version)"
echo ""

# Check if Python CLI is installed
echo "📋 Checking Python CLI..."
if ! command -v mellea-skills &> /dev/null; then
    echo "⚠️  Python CLI not found in PATH"
    echo "   Installing Python package..."

    if [ -f "pyproject.toml" ]; then
        if command -v pdm &> /dev/null; then
            pdm install
        elif command -v pip &> /dev/null; then
            pip install -e .
        else
            echo "❌ Neither pdm nor pip found"
            echo "   Please install Python package manually"
            exit 1
        fi
    else
        echo "❌ pyproject.toml not found"
        echo "   Please install Python package manually"
        exit 1
    fi
fi

if command -v mellea-skills &> /dev/null; then
    echo "✅ Python CLI: $(which mellea-skills)"
else
    echo "❌ Python CLI installation failed"
    exit 1
fi
echo ""

# Install Node.js dependencies
echo "📦 Installing Node.js dependencies..."
npm install --no-fund --no-audit
echo "✅ Node.js dependencies installed"
echo ""

# Make scripts executable
echo "🔧 Setting executable permissions..."
chmod +x ui/interactive-cli.js
echo "✅ Permissions set"
echo ""

# Test installation
echo "🧪 Testing installation..."
if node ui/interactive-cli.js --version &> /dev/null; then
    VERSION=$(node ui/interactive-cli.js --version)
    echo "✅ CLI works: v$VERSION"
else
    echo "❌ CLI test failed"
    exit 1
fi
echo ""

# Success message
echo "╔══════════════════════════════════════════════════════╗"
echo "║                                                      ║"
echo "║              🎉 Setup Complete!                      ║"
echo "║                                                      ║"
echo "╚══════════════════════════════════════════════════════╝"

node ui/interactive-cli.js
