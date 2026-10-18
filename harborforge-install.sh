#!/usr/bin/env sh
# Experimental Harborforge lab installer — does not replace Deckhand.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/skills/harborforge"
[ -f "$SRC/SKILL.md" ] || { echo "Missing skills/harborforge/SKILL.md" >&2; exit 1; }
# Refuse unintended overwrite. This skill is an experimental derivative.
for parent in "$HOME/.claude" "$HOME/.codex" "$HOME/.agents" "$HOME/.cursor" "$HOME/.hermes" "$HOME/.gemini" "$HOME/.config/opencode"; do
  [ -d "$parent" ] || continue
  case "$parent" in
    "$HOME/.config/opencode") dest="$parent/skills/harborforge" ;;
    *) dest="$parent/skills/harborforge" ;;
  esac
  if [ -e "$dest" ]; then
    echo "Skipped existing Harborforge install: $dest" >&2
    continue
  fi
  mkdir -p "$(dirname "$dest")"
  cp -R "$SRC" "$dest"
  echo "Installed Harborforge: $dest"
done
STATE="$HOME/.harborforge"
mkdir -p "$STATE/bin" "$STATE/skill"
if [ -e "$STATE/skill/harborforge" ]; then
  echo "Refusing to overwrite $STATE/skill/harborforge. Back it up and remove it before reinstalling." >&2
  exit 1
fi
cp -R "$SRC" "$STATE/skill/harborforge"
cat > "$STATE/bin/hf" <<'SHIM'
#!/usr/bin/env sh
export DECKHAND_HOME="${HARBORFORGE_HOME:-$HOME/.harborforge/state}"
exec python3 "$HOME/.harborforge/skill/harborforge/dh.py" "$@"
SHIM
chmod +x "$STATE/bin/hf"
echo "Harborforge lab ready. Add $STATE/bin to PATH and run: hf next"
echo "WARNING: Do not use Harborforge in an existing Deckhand project (both still use .deckhand project-state paths)."
