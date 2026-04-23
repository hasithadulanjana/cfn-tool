#!/bin/bash
# cfn-tool installer for macOS

set -e

echo "🔧 Installing cfn-tool..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Install system dependencies
echo ""
echo "📦 Checking system dependencies..."

# Graphviz (required for diagram generation)
if command -v dot &>/dev/null; then
    echo "✅ Graphviz already installed"
else
    echo "📥 Installing Graphviz (needed for cfn diagram)..."
    if command -v brew &>/dev/null; then
        brew install graphviz
        echo "✅ Graphviz installed via Homebrew"
    else
        echo "⚠️  Homebrew not found. Install Graphviz manually:"
        echo "   brew install graphviz"
        echo "   (or: sudo port install graphviz)"
    fi
fi

# uvx (required for MCP server connections — live pricing, diagrams)
if command -v uvx &>/dev/null; then
    echo "✅ uvx already installed"
else
    echo "📥 Installing uv (needed for MCP server connections)..."
    if command -v brew &>/dev/null; then
        brew install uv
        echo "✅ uv installed via Homebrew"
    elif command -v pip3 &>/dev/null; then
        pip3 install uv
        echo "✅ uv installed via pip"
    else
        echo "⚠️  Install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
    fi
fi

echo ""
if pip3 --version >/dev/null 2>&1; then
    PIP_CMD="pip3"
    PYTHON_CMD="python3"
elif command -v pip3.13 &>/dev/null; then
    PIP_CMD="pip3.13"
    PYTHON_CMD="python3.13"
elif command -v pip3.12 &>/dev/null; then
    PIP_CMD="pip3.12"
    PYTHON_CMD="python3.12"
else
    echo "⚠️  No working pip3 found. Please fix your python installation."
    exit 1
fi

$PIP_CMD install "$SCRIPT_DIR"

# Get Python user bin path
USER_BIN="$($PYTHON_CMD -m site --user-base)/bin"
GLOBAL_BIN="$($PYTHON_CMD -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"

# Check if cfn is already reachable
if command -v cfn &>/dev/null; then
    echo "✅ cfn-tool installed and available on PATH."
    echo "   Run: cfn --help"
    exit 0
fi

# Determine which bin dir has the cfn binary
BIN_PATH=""
if [ -f "$USER_BIN/cfn" ]; then
    BIN_PATH="$USER_BIN"
elif [ -f "$GLOBAL_BIN/cfn" ]; then
    BIN_PATH="$GLOBAL_BIN"
fi

if [ -z "$BIN_PATH" ]; then
    echo "⚠️  cfn binary not found. You may need to run: pip3 install --user ."
    exit 1
fi

# Detect shell config file
if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ]; then
    SHELL_RC="$HOME/.zshrc"
else
    SHELL_RC="$HOME/.bashrc"
fi

# Add to PATH if not already there
EXPORT_LINE="export PATH=\"\$PATH:$BIN_PATH\""

if grep -qF "$BIN_PATH" "$SHELL_RC" 2>/dev/null; then
    echo "✅ PATH already configured in $SHELL_RC"
else
    echo "" >> "$SHELL_RC"
    echo "# cfn-tool CLI" >> "$SHELL_RC"
    echo "$EXPORT_LINE" >> "$SHELL_RC"
    echo "✅ Added $BIN_PATH to PATH in $SHELL_RC"
fi

echo ""
echo "🔧 Setting up shell completions..."

# Detect shell type for completions
if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ]; then
    COMP_SHELL="zsh"
else
    COMP_SHELL="bash"
fi

# Source the rc so cfn is on PATH, then install completions
export PATH="$PATH:$BIN_PATH"
cfn completions "$COMP_SHELL" 2>/dev/null && echo "✅ Shell completions installed for $COMP_SHELL" || echo "⚠️  Completions setup skipped (run 'cfn completions $COMP_SHELL' manually)"

echo ""
echo "🎉 Done! Run this to start using cfn now:"
echo "   source $SHELL_RC"
echo "   cfn --help"
