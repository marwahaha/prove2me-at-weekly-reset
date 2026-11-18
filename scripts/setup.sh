#!/usr/bin/env bash
# prove2me-autoprover: environment setup (the slow, cacheable part).
#
# Installs elan (Lean's version manager), the Lean toolchain of the Prove2me
# default environment, the prove2me_workspace, and Mathlib's prebuilt cache.
#
# * Claude Code routine: paste this whole file into the cloud environment's
#   "Setup script" box. It is self-contained (it does not need this repo).
#   The routine snapshots the result only if setup finishes in about five
#   minutes, so every step is time-boxed; whatever does not fit is finished by
#   scripts/prepare.sh at the start of each run. Never fails the session.
#
# No secrets are used here.
set -u

# Platform default environment when this was written; prepare.sh re-checks
# against GET /environments every run and re-pins if Prove2me moved on.
TOOLCHAIN="${P2M_TOOLCHAIN:-leanprover/lean4:v4.33.1}"
MATHLIB_REV="${P2M_MATHLIB_REV:-0df444a360eaa60ab8c11dca51a86af692955474}"
WS="${PROVE2ME_WORKSPACE:-$HOME/prove2me_workspace}"
BUDGET="${P2M_SETUP_BUDGET_SECONDS:-270}"   # stay under the ~5 min snapshot limit
START=$SECONDS
left() { echo $(( BUDGET - (SECONDS - START) )); }
log() { echo "[setup +$((SECONDS - START))s] $*"; }

# 0. Python's `cryptography` package, for the encrypted renewed Prove2me key. p2m.py also
#    installs it on first use if missing; doing it here caches it with the environment.
#    The check really loads Fernet: a distro copy can import but crash without _cffi_backend.
#    --ignore-installed puts a working copy in the user site even next to a broken one.
FERNET_OK='from cryptography.fernet import Fernet; Fernet(Fernet.generate_key())'
python3 -c "$FERNET_OK" >/dev/null 2>&1 \
  || timeout 120 python3 -m pip install -q --user --ignore-installed cryptography cffi >/dev/null 2>&1 \
  || timeout 120 python3 -m pip install -q --user --break-system-packages --ignore-installed cryptography cffi >/dev/null 2>&1 \
  || true
python3 -c "$FERNET_OK" >/dev/null 2>&1 \
  || log "could not install a working Python cryptography package (p2m.py retries on first use)"

# 1. elan + toolchain (Lean itself; ~200 MB)
if ! command -v elan >/dev/null 2>&1 && [ ! -x "$HOME/.elan/bin/elan" ]; then
  log "installing elan"
  curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
    | sh -s -- -y --default-toolchain none --no-modify-path || log "elan install failed"
fi
export PATH="$HOME/.elan/bin:$PATH"
grep -q '.elan/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.elan/bin:$PATH"' >> "$HOME/.bashrc"
log "installing toolchain $TOOLCHAIN"
timeout "$(left)" elan toolchain install "$TOOLCHAIN" || log "toolchain install incomplete"

# 2. Prove2me workspace (skill docs + Definitions/Theorems/Solutions layout)
WS_URL=https://github.com/prove2me/prove2me_workspace.git
if [ -d "$WS/.git" ]; then
  git -C "$WS" pull -q --ff-only || true
elif [ -n "$(ls -A "$WS" 2>/dev/null)" ]; then
  # $WS exists but is not a checkout (e.g. a cached .lake survived). Clone next to
  # it and copy the checkout in without overwriting or deleting anything.
  log "workspace exists without .git: merging a fresh checkout into it (no overwrites)"
  TMP_WS="$(mktemp -d)/ws"
  if git clone -q "$WS_URL" "$TMP_WS"; then
    cp -Rn "$TMP_WS/." "$WS/" 2>/dev/null || true   # existing files are kept
  else
    log "workspace clone failed"
  fi
else
  git clone -q "$WS_URL" "$WS" || log "workspace clone failed"
fi

# 3. Pin the workspace to the environment (same files `p2m.py pin-env` writes)
mkdir -p "$WS/AutoproverCheck"
echo "$TOOLCHAIN" > "$WS/lean-toolchain"
cat > "$WS/lakefile.lean" <<EOF
import Lake
open Lake DSL

package «prove2me» where
  leanOptions := #[⟨\`autoImplicit, false⟩]

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @
  "$MATHLIB_REV"

lean_lib «Definitions» where
  globs := #[.submodules \`Definitions]
lean_lib «Theorems» where
  globs := #[.submodules \`Theorems]
@[default_target]
lean_lib «Solutions» where
  globs := #[.submodules \`Solutions]
lean_lib «AutoproverCheck» where
  globs := #[.submodules \`AutoproverCheck]
EOF

# 4. Mathlib source checkout + prebuilt .olean cache (the big download, ~5 GB).
#    `lake exe cache get` is what avoids compiling Mathlib from source (hours).
cd "$WS" || exit 0
if [ "$(left)" -gt 30 ]; then
  log "lake update (fetch Mathlib at $MATHLIB_REV)"
  timeout "$(left)" lake update >/dev/null 2>&1 || log "lake update incomplete; prepare.sh finishes it"
fi
if [ "$(left)" -gt 30 ]; then
  log "lake exe cache get"
  timeout "$(left)" lake exe cache get >/dev/null 2>&1 || log "cache get incomplete; prepare.sh finishes it"
fi
log "done (anything incomplete is finished by scripts/prepare.sh)"
exit 0
