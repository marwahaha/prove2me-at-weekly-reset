#!/usr/bin/env bash
# prove2me-at-weekly-reset: per-run preparation. Idempotent; safe to rerun.
#
# 1. writes the Prove2me credentials from $PROVE2ME_CREDENTIALS (never echoed),
# 2. re-pins the workspace if Prove2me's default environment changed,
# 3. if Mathlib is already at the pinned rev and a quick smoke test passes, stops there
#    (the usual case: no `lake update`, no cache download),
# 4. otherwise finishes anything setup.sh could not (Mathlib, cache) and smoke-tests again.
# Exit codes: 0 ready, 3 credentials missing/invalid, 1 Lean not ready.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WS="${PROVE2ME_WORKSPACE:-$HOME/prove2me_workspace}"
export PATH="$HOME/.elan/bin:$PATH"
log() { echo "[prepare] $*"; }

# Network hiccups are common on first boot; retry the slow steps.
retry() { local n=0; until "$@"; do n=$((n+1)); [ $n -ge 3 ] && return 1; sleep 10; done; }

[ -d "$WS/.git" ] || bash "$REPO/scripts/setup.sh"

# 1. Credentials: the secret holds the whole credentials.json, i.e. {"api_key": "p2m_..."}.
if [ -n "${PROVE2ME_CREDENTIALS:-}" ]; then
  ( umask 077; printf '%s' "$PROVE2ME_CREDENTIALS" > "$WS/credentials.json" )
fi
# PROVE2ME_CREDENTIALS_FILE (used by p2m.py) may point elsewhere, e.g. in local tests.
CREDS_FILE="${PROVE2ME_CREDENTIALS_FILE:-$WS/credentials.json}"
# With a separate AUTOPROVER_ENCRYPTION_SECRET, the pasted key may be gone once a renewed key
# exists in the data repo; pin-env below then checks that the renewed key works.
if [ ! -s "$CREDS_FILE" ] && [ -z "${AUTOPROVER_ENCRYPTION_SECRET:-}" ]; then
  log "no Prove2me credentials: set the PROVE2ME_CREDENTIALS secret / environment variable"
  exit 3
fi

# 2-3. Pin to the platform's current default environment (also validates the key).
cd "$REPO"
if ! python3 scripts/p2m.py pin-env >/dev/null; then
  log "could not reach Prove2me with these credentials"
  exit 3
fi
TOOLCHAIN="$(cat "$WS/lean-toolchain")"
command -v elan >/dev/null || bash "$REPO/scripts/setup.sh"
elan toolchain list 2>/dev/null | grep -qF "$TOOLCHAIN" \
  || retry elan toolchain install "$TOOLCHAIN" || { log "toolchain install failed"; exit 1; }

cd "$WS"
REV="$(grep -oE '[0-9a-f]{40}' lakefile.lean | head -1)"
mkdir -p AutoproverCheck
printf 'import Mathlib.Tactic.NormNum\nexample : (2:ℚ) + 2 = 4 := by norm_num\n' > AutoproverCheck/Smoke.lean
# `lake env lean` builds nothing, so with a missing cache it fails fast instead of compiling
# Mathlib; the timeout is a second guard against a long hang.
smoke() { timeout -k 10 "$1" lake env lean AutoproverCheck/Smoke.lean; }

# Fast path: toolchain installed, Mathlib at the pinned rev, cache loads. Skips the network.
if [ "$(git -C .lake/packages/mathlib rev-parse HEAD 2>/dev/null)" = "$REV" ] \
   && smoke 120 >/dev/null 2>&1; then
  log "Lean + Mathlib already ready (cached) ($TOOLCHAIN, Mathlib ${REV:0:7})"
  exit 0
fi

if [ "$(git -C .lake/packages/mathlib rev-parse HEAD 2>/dev/null)" != "$REV" ]; then
  log "fetching Mathlib $REV"
  retry lake update >/dev/null 2>&1 || { log "lake update failed"; exit 1; }
fi
log "fetching prebuilt Mathlib cache"
retry lake exe cache get >/dev/null 2>&1 || lake exe cache get! >/dev/null 2>&1 \
  || { log "cache get failed"; exit 1; }

# 4. Smoke test: should take seconds. If it starts compiling Mathlib, the cache missed.
if smoke 600; then
  log "Lean + Mathlib ready ($TOOLCHAIN, Mathlib ${REV:0:7})"
else
  log "smoke test failed"; exit 1
fi
