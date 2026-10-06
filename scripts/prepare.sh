#!/usr/bin/env bash
# prove2me-autoprover: per-run preparation. Idempotent; safe to rerun.
#
# 1. writes the Prove2me credentials from $PROVE2ME_CREDENTIALS (never echoed),
# 2. finishes anything setup.sh could not (toolchain, Mathlib, cache),
# 3. re-pins the workspace if Prove2me's default environment changed,
# 4. smoke-tests that Lean + Mathlib load from the cache.
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
if [ ! -s "$CREDS_FILE" ]; then
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
retry elan toolchain install "$TOOLCHAIN" || { log "toolchain install failed"; exit 1; }

cd "$WS"
REV="$(grep -oE '[0-9a-f]{40}' lakefile.lean | head -1)"
if [ "$(git -C .lake/packages/mathlib rev-parse HEAD 2>/dev/null)" != "$REV" ]; then
  log "fetching Mathlib $REV"
  retry lake update >/dev/null 2>&1 || { log "lake update failed"; exit 1; }
fi
log "fetching prebuilt Mathlib cache"
retry lake exe cache get >/dev/null 2>&1 || lake exe cache get! >/dev/null 2>&1 \
  || { log "cache get failed"; exit 1; }

# 4. Smoke test: should take seconds. If it starts compiling Mathlib, the cache missed.
mkdir -p AutoproverCheck
printf 'import Mathlib.Tactic.NormNum\nexample : (2:ℚ) + 2 = 4 := by norm_num\n' > AutoproverCheck/Smoke.lean
if timeout 600 lake env lean AutoproverCheck/Smoke.lean; then
  log "Lean + Mathlib ready ($TOOLCHAIN, Mathlib ${REV:0:7})"
else
  log "smoke test failed"; exit 1
fi
