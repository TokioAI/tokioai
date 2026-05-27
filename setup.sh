#!/bin/bash
# TokioAI CLI — One-command setup
# Works on Ubuntu 20.04+, Debian, macOS, WSL
# For Windows: use setup.bat instead

echo ""
echo "═══════════════════════════════════════════════"
echo "  ████████╗ ██████╗ ██╗  ██╗██╗ ██████╗"
echo "  ╚══██╔══╝██╔═══██╗██║ ██╔╝██║██╔═══██╗"
echo "     ██║   ██║   ██║█████╔╝ ██║██║   ██║"
echo "     ██║   ██║   ██║██╔═██╗ ██║██║   ██║"
echo "     ██║   ╚██████╔╝██║  ██╗██║╚██████╔╝"
echo "     ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝"
echo "  Autonomous AI Agent — Setup v4.1"
echo "═══════════════════════════════════════════════"
echo ""

# ──────── Check Python 3.10+ ────────
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found. Install it first:"
    echo "   Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "   macOS: brew install python3"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo "❌ Python 3.10+ required (found $PY_VERSION)"
    exit 1
fi

echo "✓ Python $PY_VERSION"

# ──────── Ensure python3-venv is available ────────
if ! python3 -m venv --help &>/dev/null 2>&1; then
    echo "→ python3-venv not found, installing..."
    if command -v apt &>/dev/null; then
        sudo apt update -qq && sudo apt install -y python3-venv python3-pip
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3-venv python3-pip
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm python
    fi

    if ! python3 -m venv --help &>/dev/null 2>&1; then
        echo "❌ Failed to install python3-venv."
        echo "   Install manually: sudo apt install python3-venv python3-pip"
        exit 1
    fi
    echo "✓ python3-venv installed"
fi

# ──────── Create venv ────────
if [ -d ".venv" ]; then
    echo "→ Removing old virtual environment..."
    rm -rf .venv
fi

echo "→ Creating virtual environment..."
python3 -m venv .venv

if [ ! -f ".venv/bin/activate" ]; then
    echo "❌ Failed to create virtual environment."
    echo "   Try: sudo apt install python3-venv python3-pip"
    exit 1
fi

# ──────── Activate ────────
source .venv/bin/activate
echo "✓ Virtual environment activated"

# ──────── Upgrade pip + setuptools ────────
echo "→ Upgrading pip and setuptools..."
pip install --upgrade pip setuptools wheel --quiet
echo "✓ pip $(pip --version | awk '{print $2}')"

# ──────── Install TokioAI CLI ────────
echo "→ Installing TokioAI CLI..."

if pip install -e ".[all]" --quiet 2>/dev/null; then
    echo "✓ All providers installed (Claude, OpenAI, Gemini, SSH)"
else
    echo "→ Some optional deps failed, trying base + individual providers..."
    pip install -e . --quiet
    pip install anthropic --quiet 2>/dev/null && echo "  ✓ Anthropic (Claude)" || echo "  ⚠ Anthropic failed (optional)"
    pip install "anthropic[vertex]" --quiet 2>/dev/null && echo "  ✓ Anthropic Vertex" || echo "  ⚠ Anthropic Vertex failed (optional)"
    pip install openai --quiet 2>/dev/null && echo "  ✓ OpenAI" || echo "  ⚠ OpenAI failed (optional)"
    pip install google-genai --quiet 2>/dev/null && echo "  ✓ Gemini" || echo "  ⚠ Gemini failed (optional)"
    pip install paramiko --quiet 2>/dev/null && echo "  ✓ SSH (paramiko)" || echo "  ⚠ paramiko failed (optional)"
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "  ✅ TokioAI CLI v4.1 installed!"
echo "═══════════════════════════════════════════════"
echo ""

# ──────── Config check ────────
if [ -f "$HOME/.tokioai/.env" ]; then
    echo "✓ Config found: ~/.tokioai/.env"
    echo ""
    echo "  To start:    source .venv/bin/activate && tokioai"
    echo "  To reconfig: tokioai --setup"
else
    echo "→ First time? Let's configure your AI provider..."
    echo ""
    python3 -m tokioai_cli --setup
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "  Quick start:"
echo ""
echo "    source .venv/bin/activate"
echo "    tokioai                      # interactive"
echo "    tokio                        # same thing"
echo "    tokioai -m gemini31          # use Gemini 3.1"
echo "    tokioai -p                   # persistent mode"
echo "    tokioai --setup              # reconfigure"
echo "═══════════════════════════════════════════════"
