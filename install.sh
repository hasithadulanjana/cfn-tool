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
        echo "   brew install graphviz  (or: sudo port install graphviz)"
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
    else
        echo "⚠️  Install uv manually: https://docs.astral.sh/uv/getting-started/installation/"
    fi
fi

echo ""

# ---------------------------------------------------------------------------
# Resolve a working Python + pip.
# Prefer `python3 -m pip` over the pip3 shim — the shim can crash on broken
# libexpat linkage (e.g. Python 3.14 + old macOS libexpat) while the module
# invocation works fine.
# ---------------------------------------------------------------------------
# Prefer uv — it manages its own Python and avoids Homebrew PEP 668 restrictions
if command -v uv &>/dev/null; then
    echo "✅ Using uv for installation"
    uv tool install "$SCRIPT_DIR" --python 3.12
    UV_TOOL_BIN="$(uv tool dir)/bin"
    # uv tool install puts the binary in its own bin dir
    if command -v cfn &>/dev/null; then
        echo "✅ cfn-tool installed successfully"
        exit 0
    fi
    # Add uv tool bin to PATH if needed
    BIN_PATH="$(uv tool dir 2>/dev/null)"
    # Resolve the actual bin path
    if [ -f "$HOME/.local/bin/cfn" ]; then
        BIN_PATH="$HOME/.local/bin"
    elif [ -f "$UV_TOOL_BIN/cfn" ]; then
        BIN_PATH="$UV_TOOL_BIN"
    fi
    if [ -n "$BIN_PATH" ] && [ -f "$BIN_PATH/cfn" ]; then
        export PATH="$PATH:$BIN_PATH"
        if [ -f "$HOME/.zshrc" ]; then SHELL_RC="$HOME/.zshrc"
        elif [ -f "$HOME/.bashrc" ]; then SHELL_RC="$HOME/.bashrc"
        else SHELL_RC="$HOME/.zshrc"; fi
        EXPORT_LINE="export PATH=\"\$PATH:$BIN_PATH\""
        if ! grep -qF "$BIN_PATH" "$SHELL_RC" 2>/dev/null; then
            echo "" >> "$SHELL_RC"
            echo "# cfn-tool CLI" >> "$SHELL_RC"
            echo "$EXPORT_LINE" >> "$SHELL_RC"
            echo "✅ Added $BIN_PATH to PATH in $SHELL_RC"
        else
            echo "✅ PATH already configured in $SHELL_RC"
        fi
        cfn completions zsh 2>/dev/null && echo "✅ Shell completions installed" || true
        echo ""
        echo "🎉 Done! To start using cfn:"
        echo "   source $SHELL_RC"
        echo "   cfn --help"
        exit 0
    fi
    echo "❌ uv tool install ran but cfn binary not found. Try: uv tool install $SCRIPT_DIR"
    exit 1
fi

# Fallback: find a working Python pip
PYTHON_CMD=""
PIP_CMD=""

for py in python3 python3.14 python3.13 python3.12 python3.11; do
    if command -v "$py" &>/dev/null; then
        if "$py" -c "import pip._internal.commands.install" &>/dev/null 2>&1; then
            PYTHON_CMD="$py"
            PIP_CMD="$py -m pip"
            echo "✅ Using $py (invoked as: $PIP_CMD)"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "❌ No working Python + pip found, and uv is not available."
    echo "   Install uv: brew install uv  (then re-run this script)"
    exit 1
fi

$PIP_CMD install --user "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Resolve install locations
# ---------------------------------------------------------------------------
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
    echo "⚠️  cfn binary not found in expected locations:"
    echo "   user:   $USER_BIN"
    echo "   global: $GLOBAL_BIN"
    echo "   Try running manually: $PIP_CMD install --user ."
    exit 1
fi

# ---------------------------------------------------------------------------
# PATH setup
# ---------------------------------------------------------------------------
if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ]; then
    SHELL_RC="$HOME/.zshrc"
else
    SHELL_RC="$HOME/.bashrc"
fi

EXPORT_LINE="export PATH=\"\$PATH:$BIN_PATH\""
if grep -qF "$BIN_PATH" "$SHELL_RC" 2>/dev/null; then
    echo "✅ PATH already configured in $SHELL_RC"
else
    echo "" >> "$SHELL_RC"
    echo "# cfn-tool CLI" >> "$SHELL_RC"
    echo "$EXPORT_LINE" >> "$SHELL_RC"
    echo "✅ Added $BIN_PATH to PATH in $SHELL_RC"
fi

# ---------------------------------------------------------------------------
# Shell completions
# ---------------------------------------------------------------------------
echo ""
echo "🔧 Setting up shell completions..."

COMP_SHELL="bash"
if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ]; then
    COMP_SHELL="zsh"
fi

export PATH="$PATH:$BIN_PATH"
cfn completions "$COMP_SHELL" 2>/dev/null \
    && echo "✅ Shell completions installed for $COMP_SHELL" \
    || echo "⚠️  Completions skipped — run 'cfn completions $COMP_SHELL' manually after sourcing your shell"

echo ""
echo "🎉 Done! To start using cfn:"
echo "   source $SHELL_RC"
echo "   cfn --help"