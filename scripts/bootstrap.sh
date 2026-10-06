#!/usr/bin/env bash
# prove2me-autoprover: download the tool at a pinned version (fast, no secrets).
#
# FUTURE PUBLIC-DISTRIBUTION PATH, currently unused: while the tool repo is
# private, the routine attaches it as a second repository instead (see
# prompts/routine-trigger.md), and raw.githubusercontent.com cannot serve it.
#
# Run from the routine prompt, in the cloned data repo:
#   curl -fsSL "https://raw.githubusercontent.com/sattath/prove2me-autoprover/${AUTOPROVER_REF:-main}/scripts/bootstrap.sh" | bash
# Installs into $AUTOPROVER_TOOL (default ~/autoprover-tool). Then follow
# $AUTOPROVER_TOOL/prompts/routine.md, whose first step runs prepare.sh.
set -euo pipefail
REF="${AUTOPROVER_REF:-main}"
SRC="${AUTOPROVER_SOURCE:-https://raw.githubusercontent.com/sattath/prove2me-autoprover}"
TOOL="${AUTOPROVER_TOOL:-$HOME/autoprover-tool}"
FILES="scripts/p2m.py scripts/prepare.sh scripts/setup.sh prompts/routine.md"

mkdir -p "$TOOL/scripts" "$TOOL/prompts"
for f in $FILES; do
  curl -fsSL --retry 3 "$SRC/$REF/$f" -o "$TOOL/$f.tmp"
  mv "$TOOL/$f.tmp" "$TOOL/$f"
done
chmod +x "$TOOL"/scripts/*.sh "$TOOL/scripts/p2m.py"
echo "$REF" > "$TOOL/VERSION"
echo "[bootstrap] prove2me-autoprover $REF installed in $TOOL"
echo "[bootstrap] next: follow $TOOL/prompts/routine.md"
