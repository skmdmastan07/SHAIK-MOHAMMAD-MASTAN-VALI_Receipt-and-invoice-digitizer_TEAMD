#!/bin/bash

echo "========================================="
echo "  Receipt and Invoice Digitizer - Start  "
echo "========================================="
echo ""

# ── Check Python ──
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install it first."
    exit 1
fi
echo "✅ Python 3 found"

# ── Check pip ──
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 not found. Please install pip first."
    exit 1
fi
echo "✅ pip3 found"

# ── Check Ollama ──
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama is not installed."
    echo "   Please download it from: https://ollama.com/download"
    exit 1
fi
echo "✅ Ollama found"
echo ""

# ── Install Python dependencies ──
echo "📦 Installing dependencies..."
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies. Check requirements.txt"
    exit 1
fi
echo "✅ Dependencies installed"
echo ""

# ── Start Ollama in background ──
echo "🤖 Starting Ollama server..."
ollama serve &> /tmp/ollama.log &
OLLAMA_PID=$!
sleep 3

# Check Ollama actually started
if ! kill -0 $OLLAMA_PID 2>/dev/null; then
    echo "⚠️  Ollama may already be running (that's fine, continuing...)"
fi
echo "✅ Ollama server ready"

# ── Pull model if needed ──
echo "📥 Checking AI model..."
ollama pull llama3 2>/dev/null && echo "✅ Mode