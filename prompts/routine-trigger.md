You are running prove2me-autoprover unattended. No human is available during this run.

Two repositories are cloned for this run: the user's private data repository (it contains `autoprover.config.json`) and the prove2me-autoprover tool repository (it contains `scripts/p2m.py`).

1. Locate both clones and export their paths. Start from the current directory and its parent; if that fails, search the filesystem:

   ```bash
   for d in "$PWD" "$PWD"/* "$PWD"/.. "$PWD"/../* "$HOME"/* /home/*/* /workspace/* /repos/*; do
     [ -f "$d/autoprover.config.json" ] && [ -z "${AUTOPROVER_DATA:-}" ] && export AUTOPROVER_DATA="$(cd "$d" && pwd)"
     [ -f "$d/scripts/p2m.py" ] && [ -f "$d/prompts/routine.md" ] && [ -z "${AUTOPROVER_TOOL:-}" ] && export AUTOPROVER_TOOL="$(cd "$d" && pwd)"
   done
   [ -n "${AUTOPROVER_TOOL:-}" ] || export AUTOPROVER_TOOL="$(dirname "$(dirname "$(find / -name p2m.py -path '*/scripts/p2m.py' -not -path '*/proc/*' 2>/dev/null | head -1)")")"
   [ -n "${AUTOPROVER_DATA:-}" ] || export AUTOPROVER_DATA="$(dirname "$(find / -name autoprover.config.json -not -path '*/template/*' -not -path '*/proc/*' 2>/dev/null | head -1)")"
   echo "AUTOPROVER_DATA=$AUTOPROVER_DATA AUTOPROVER_TOOL=$AUTOPROVER_TOOL"
   ```

2. Read `$AUTOPROVER_TOOL/prompts/routine.md` and follow it exactly, from its first step to its last. It is your task for this run. Shell variables may not survive between commands: if `AUTOPROVER_DATA` or `AUTOPROVER_TOOL` is unset later, export the same values again.

If either clone cannot be found, do not improvise: if the data repository was found, write `logs/setup-failed-<UTC timestamp>.md` in it with the error output, commit only that file, push it to the data repository's default branch, and stop. Otherwise just stop and report the error.
