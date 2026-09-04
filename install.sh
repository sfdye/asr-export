#!/usr/bin/env bash
# asr-export installer (macOS / Linux) — installs the `asr-export` command
#   bash install.sh
# Alternative: skip this and run the tool directly with  python3 asr-export.py
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
BIN="$HOME/.local/bin"; mkdir -p "$BIN"

echo "→ Installing asr-export to $BIN/asr-export"
if [ -f "$SELF_DIR/asr-export.py" ]; then cp "$SELF_DIR/asr-export.py" "$BIN/asr-export.py"
else echo "⚠️ Put asr-export.py next to this script and re-run"; exit 1; fi
chmod 0644 "$BIN/asr-export.py"

cat > "$BIN/asr-export" <<EOF
#!/usr/bin/env bash
# installed command: default download dir = ~/Documents/asr-export
# (source runs default to the script's own folder; both overridable with -o or ASR_EXPORT_DIR)
ASR_EXPORT_DIR="\${ASR_EXPORT_DIR:-\$HOME/Documents/asr-export}" exec python3 "$BIN/asr-export.py" "\$@"
EOF
chmod +x "$BIN/asr-export"

command -v python3 >/dev/null || echo "⚠️ python3 not found — please install Python 3"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    RC="$HOME/.profile"
    case "${SHELL:-}" in *zsh) RC="$HOME/.zshrc";; *bash) RC="$HOME/.bashrc";; esac
    LINE='export PATH="$HOME/.local/bin:$PATH"'
    grep -qF "$LINE" "$RC" 2>/dev/null || printf '\n# added by asr-export installer\n%s\n' "$LINE" >> "$RC"
    echo "ℹ️ Added ~/.local/bin to $RC — open a new terminal, or run:  source $RC";;
esac

echo "✅ Done!"
echo "   next:  asr-export login   (new devices need a one-time email OTP)"
echo "         asr-export download"
