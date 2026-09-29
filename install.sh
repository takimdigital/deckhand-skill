#!/usr/bin/env sh
# Deckhand installer — copies (or links) skills/deckhand into every agent harness it finds,
# and puts a `dh` shim in ~/.deckhand/bin.  Usage:
#   ./install.sh                  # every detected harness
#   ./install.sh --link           # symlink instead of copy (git pull updates every harness)
#   ./install.sh --only claude,hermes
#   ./install.sh --claude-hook    # also: every Claude Code session in a deckhand project starts from its RESUME
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/skills/deckhand"
MODE=copy; ONLY=""; HOOK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --link) MODE=link ;;
    --only) ONLY="${2:?--only needs a harness name}"; shift ;;
    --claude-hook) HOOK=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "install.sh: unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac; shift
done

say() { printf '%s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { say "missing: $1 ($2)"; MISSING=1; }; }
MISSING=0
need python3 "Python 3.9+ runs the dh control plane"
need node "Node 18+ runs try-on and compose"
need git "git clones bases and versions projects"
[ "$MISSING" = 1 ] && say "(install what is missing, then re-run — nothing else is required)"

HERMES_EXTRA=""
[ -n "$HERMES_HOME" ] && HERMES_EXTRA="hermes:$HERMES_HOME/skills
"
for p in "$HOME"/.hermes/profiles/*/skills; do [ -d "$p" ] && HERMES_EXTRA="${HERMES_EXTRA}hermes:$p
"; done
HOMES="${HERMES_EXTRA}claude:$HOME/.claude/skills
codex:$HOME/.codex/skills
agents:$HOME/.agents/skills
cursor:$HOME/.cursor/skills
hermes:$HOME/.hermes/skills
hermes:$HOME/.local/share/hermes/skills
opencode:$HOME/.config/opencode/skills
gemini:$HOME/.gemini/skills"

installed=""
echo "$HOMES" | while IFS=: read -r name dir; do
  parent=$(dirname "$dir")
  if [ -n "$ONLY" ] && ! echo ",$ONLY," | grep -q ",$name,"; then continue; fi
  [ -d "$parent" ] || [ "$name" = "agents" ] || continue
  mkdir -p "$dir"
  dest="$dir/deckhand"
  # Hermes files skills under categories (skills/software-development/deckhand): update that copy, never add a second one
  nested=$(ls -d "$dir"/*/deckhand 2>/dev/null | while read -r d; do [ -f "$d/SKILL.md" ] && echo "$d"; done | head -1)
  [ -n "$nested" ] && [ ! -f "$dest/SKILL.md" ] && dest="$nested"
  rm -rf "$dest"
  if [ "$MODE" = link ]; then ln -s "$SRC" "$dest"; else cp -R "$SRC" "$dest"; fi
  say "✓ $name → $dest ($MODE)"
done

# a stable home for the shim (survives deleting the clone in copy mode)
mkdir -p "$HOME/.deckhand/bin" "$HOME/.deckhand/skill"
rm -rf "$HOME/.deckhand/skill/deckhand"
if [ "$MODE" = link ]; then ln -s "$SRC" "$HOME/.deckhand/skill/deckhand"; else cp -R "$SRC" "$HOME/.deckhand/skill/deckhand"; fi
cat > "$HOME/.deckhand/bin/dh" <<SHIM
#!/usr/bin/env sh
exec python3 "$HOME/.deckhand/skill/deckhand/dh.py" "\$@"
SHIM
chmod +x "$HOME/.deckhand/bin/dh"
say "✓ dh shim → $HOME/.deckhand/bin/dh   (add to PATH: export PATH=\"\$HOME/.deckhand/bin:\$PATH\")"
if [ "$HOOK" = 1 ]; then
  python3 "$HOME/.deckhand/skill/deckhand/dh.py" resume --install-hook claude >/dev/null && \
    say "✓ Claude Code SessionStart hook (new, resumed, cleared, compacted sessions start from .deckhand/RESUME.md)"
else
  say "(optional) ./install.sh --claude-hook — Claude Code sessions in a deckhand project then start from its RESUME"
fi
say ""
say "Next: open your agent and say what you want, e.g. \"Build a website for my bakery. Phased mode.\""
say "Step by step, copy-a-sentence: docs/USE-CASES.md"
