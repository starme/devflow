#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { printf "${GREEN}[INFO]${NC} %s\n" "$*"; }
warn()    { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
error()   { printf "${RED}[ERROR]${NC} %s\n" "$*" >&2; }
step()    { printf "${CYAN}[STEP]${NC} %s\n" "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 &>/dev/null; then
    error "python3 is required for DevFlow hooks but was not found in PATH."
    error "Please install Python 3.8+ and try again."
    exit 1
fi
info "python3 found: $(python3 --version 2>&1)"

CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

info "DevFlow plugin source: $SCRIPT_DIR"

# --- 1. Make hooks executable ---
info "Making hooks executable..."
chmod +x "$SCRIPT_DIR"/hooks/*.sh 2>/dev/null || true
chmod +x "$SCRIPT_DIR"/core/hooks/*.py 2>/dev/null || true

# --- 2. Set up global rules ---
# Only engineering.md goes to user-level rules.
# Language/framework rules stay in core/rules/ (platform-agnostic) and are
# loaded by agents at runtime — this lets plugin upgrades update rules automatically.
info "Setting up global rules..."
mkdir -p "$HOME/.claude/rules"

if [ -f "$SCRIPT_DIR/core/rules/engineering.md" ]; then
    if [ -f "$HOME/.claude/rules/engineering.md" ]; then
        warn "~/.claude/rules/engineering.md already exists, skipping (not overwriting)."
    else
        cp -n "$SCRIPT_DIR/core/rules/engineering.md" "$HOME/.claude/rules/engineering.md"
        info "Copied engineering.md to ~/.claude/rules/"
    fi
fi

# --- 3. Check Memorant ---
MEMORANT_FOUND=false
if [ -d "$CLAUDE_CONFIG_DIR/plugins" ]; then
    if find "$CLAUDE_CONFIG_DIR/plugins" -maxdepth 4 -type d -iname "*memorant*" 2>/dev/null | grep -q .; then
        MEMORANT_FOUND=true
    fi
fi

# --- 4. Print instructions ---
echo ""
info "DevFlow files prepared successfully!"
echo ""
echo "============================================================"
echo "  Complete installation in Claude Code (2 steps)"
echo "============================================================"
echo ""
step "1. Add the marketplace (copy and run this in Claude Code):"
echo ""
echo "   /plugin marketplace add $SCRIPT_DIR"
echo ""
step "2. Install the plugin:"
echo ""
echo "   /plugin install devflow@devflow-marketplace"
echo ""
echo "Then restart Claude Code and run /devflow init in any project."
echo ""
echo "============================================================"
echo ""
echo "Installation summary:"
echo "  - Plugin source: $SCRIPT_DIR"
echo "  - Core engine:   $SCRIPT_DIR/core/ (platform-agnostic)"
echo "    · orchestrator core/orchestrator/SKILL.md"
echo "    · hooks        core/hooks/ (redline-guard.py, audit-log.py)"
echo "    · rules        core/rules/ (language + framework rules)"
echo "    · templates    core/templates/ (manifest, redlines, scope)"
echo "  - Claude adapter:"
echo "    · commands     $SCRIPT_DIR/commands/"
echo "    · agents       $SCRIPT_DIR/agents/ (5 subagents)"
echo "    · lifecycle    hooks/devflow-hook.sh"
echo "  - Global rules:  ~/.claude/rules/engineering.md"
echo ""

if [ "$MEMORANT_FOUND" = false ]; then
    warn "Memorant not detected. It is optional but recommended for"
    warn "experience recall and distillation across projects."
    echo ""
fi
