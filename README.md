# prove2me-autoprover

A community tool for people who have both a Claude subscription and a [Prove2me](https://prove2.me) account. It uses the part of your weekly Claude allowance that would otherwise go unused. In the last hours before your weekly limit resets, a scheduled cloud agent attempts proofs of open Lean 4 theorems on Prove2me, and submits only the proofs that pass strict local checks.

Everything runs in the cloud, as a [Claude Code routine](https://code.claude.com/docs/en/routines). No local machine is involved and nobody needs to watch it.

> **Status: early.** The maintainer is testing it on their own account first. Routines are a research-preview feature of Claude Code, so details can change. Issues and pull requests are welcome.

> [!WARNING]
> **Paid extra usage.** If "extra usage" / usage credits are enabled on your Claude account or organization, a run can continue on metered overage after your subscription allowance runs out, **and you will be charged**. Every run checks your usage before it starts, before each claim, before each local build and before each submission, and stops if the account is on paid overage or above the caps (see *Usage gate* below). That check is a strong safeguard but not a guarantee: usage can still overshoot between two checks. Turn extra usage off at [claude.ai/settings/usage](https://claude.ai/settings/usage) before enabling live runs. On Team and Enterprise plans, an admin does this at claude.ai/admin-settings/usage.

## One user, one setup

This repository is the shared tool. Everything personal stays with you:

| | Who provides it |
|---|---|
| Claude subscription and its allowance | you (subscription credentials are for individual use: never share or pool them) |
| Prove2me account and API key | you |
| **Private data repo**: your `autoprover.config.json` and run logs | you, created from [`template/`](template/) |
| Cloud environment + routine on claude.ai | you |
| Scripts and agent prompt | this repo, attached to your routine next to your data repo |

Proofs are submitted under your Prove2me account, and every one carries a footer saying it was made by prove2me-autoprover in an unattended run.

## How a run works

```
 once a week, 2 hours before your weekly Claude limit resets
          │
          ▼
 routine starts a fresh cloud VM, clones YOUR private data repo + this tool repo
          │
 setup.sh      (cached by the environment) elan, Lean toolchain, prove2me_workspace, Mathlib cache
 prepare.sh    write Prove2me credentials, re-pin the environment, quick Lean check (full setup only if it fails)
          │
 Claude, following prompts/routine.md:
   p2m.py usage       go only inside the last lead_hours before the weekly reset and below the caps
   p2m.py candidates  shortlist from your saved list / missions / search, per your config
   p2m.py fetch       mirror the target and every platform module it imports
   p2m.py usage --for start-claim   before each claim; gives the claim's time budget
   write Solutions/Sol_<name>.lean, loop on  p2m.py check   (usage checkpoint, then build)
   p2m.py submit      usage checkpoint, re-runs every check, then submits (or stops here in dry run)
   p2m.py summary     logs/<run>.md + .jsonl → committed and pushed to your data repo
   p2m.py notify      push notification / optional webhook, per your notify setting
```

### Usage gate

Design goal: **never harm the people who contribute.** A bug in this tool must not have a seriously negative effect on your Claude allowance. The tool therefore only uses allowance that is about to expire unused, stays well away from your limits, and enforces this in [`scripts/p2m.py`](scripts/p2m.py) rather than only asking the agent to.

`p2m.py usage` makes one tiny Haiku call and reads the rate-limit information Claude Code reports with it: how much of the 5-hour and of the weekly window is used, and when each resets. With the default settings:

- **Time window.** Work happens only in the last `lead_hours` (default 2) before the weekly limit resets, and stops `reset_buffer_minutes` (default 5) before the reset, so next week's allowance is never touched. Each claim's time budget is `minutes_per_claim` or the time left until that buffer, whichever is smaller.
- **Hard caps.** Work stops once the 5-hour window reaches `max_five_hour_utilization` (50%) or the weekly window reaches `max_weekly_utilization` (80%). These are absolute fractions of each window, not of the leftover.
- **Stricter limits for starting a claim.** A new claim starts only if the 5-hour window is at most 40% and the weekly window at most 75% (the caps minus `claim_start_margin_five_hour` and `claim_start_margin_weekly`), so a claim begun just under a cap has room to finish.
- **No paid overage** (`stop_on_overage`, default on), and **no work if usage can't be read** (`allow_unknown_usage`, default off).

Where it is enforced: at run start (`p2m usage`), before each claim (`p2m usage --for start-claim`), inside every `p2m check` (before each Lean build; a reading up to 3 minutes old may be reused) and inside every `p2m submit`, dry runs included (always a fresh reading). On a no-go, `check` and `submit` exit with code 6 without building or submitting anything.

What this does and does not guarantee:

- The caps are checked at these checkpoints, not metered continuously. The overshoot past a cap is bounded by the Claude usage between two checkpoints. Since every `check` reads usage first, that is normally one iteration of the agent's write-and-build loop (including any scratch experiments and reading in that iteration). The agent is also told to end each claim at its time budget, but that part is a prompt rule, not code.
- Readings are whole percents, as Claude reports them.
- They count your whole account, including your own use of Claude at the same time. If you are working heavily during the run, the run stops earlier; it never pushes your total past the caps by more than the overshoot above.
- An older config with `stop_at_utilization` still works, but it can only lower the caps, never raise them above 50% and 80%. To raise a cap you must set the new key explicitly.

**Schedule.** The routine runs once a week, at (weekly reset - `lead_hours`) + 7 minutes. `python3 scripts/p2m.py schedule` reads your reset time and prints that time as a weekly cron line in UTC, plus your local time. If a scheduled run finds itself outside the window, the schedule no longer matches your reset (for example after a plan change), and the run stops and notifies you with the corrected cron line (set `expect_window_on_schedule` to `false` to turn this off if you schedule runs more often on purpose). For a manual **Run now** outside the window, either ignore that notification or set `AUTOPROVER_IGNORE_WINDOW=1` in the environment for the test; it skips only the time-window rule, never the caps, and you should remove it afterwards.

All Prove2me traffic goes through [`scripts/p2m.py`](scripts/p2m.py), so the safety rules are enforced in code, not only requested in the prompt.

- **Local gates before any submission.** Every one of these must pass, and `submit` re-runs them on the exact bytes it sends:
  - `lake build` compiles the file (Lean's build tool, the equivalent of `make`).
  - There is a top-level `theorem solution`, and it does not import its own target.
  - Lean confirms that `solution` has exactly the target's type.
  - `#print axioms solution` lists only the standard axioms `propext`, `Classical.choice` and `Quot.sound`. This is Lean reporting everything a proof ultimately rests on. A hidden `sorry` (Lean's "trust me" placeholder) shows up there as `sorryAx`, and `native_decide` shows up as `Lean.ofReduceBool`. Either one blocks the submission.
- **Proof-sketches build only on lemmas that already exist.** A sketch, or "reduction", proves a target from other platform theorems that may still be open. The helper mirrors each imported theorem locally as an `axiom`, so `#print axioms` names it explicitly. Those names are allowed and nothing else is. The tool never creates new problems or definitions on Prove2me, and never comments, votes or rates.
- **Dry run.** This is the default. Proofs are attempted and fully checked, but nothing is submitted. Would-be submissions are saved to your data repo for you to read.
- **Caps:** `max_claims_per_run`, `max_submissions_per_run` and `minutes_per_claim`.
- **Secrets stay out of the transcript and logs.** The agent never needs to read your API key, because the helper does.

### A few Lean terms

- **Lean 4** is the proof checker. A proof that compiles is correct.
- **Mathlib** is Lean's large library of mathematics.
- **Pinned environment.** Prove2me checks every theorem against one exact Mathlib commit and Lean version. The cloud machine installs exactly that pair: elan installs Lean, and `lake exe cache get` downloads about 5 GB of precompiled Mathlib. That download saves hours of compilation.
- **Mirrored definitions.** Most theorems on Prove2me import platform definitions. The helper copies those files into the local `Definitions/` and `Theorems/` folders, so a local build behaves exactly like the server's.

## Setup (about 20 minutes)

### 1. Prove2me API key

On prove2.me, log in, open the account menu and click **API key**. Your secret value is the whole line `{"api_key":"p2m_..."}`.

**Keys expire after 30 days.** When a run log says `API key rejected`, mint a new key and update the environment variable.

### 2. Private data repo

1. Create a **private** GitHub repo, e.g. `prove2me-autoprover-data`.
2. Copy the files from [`template/`](template/) into it.
3. Edit `autoprover.config.json`:
   - **`lead_hours`:** default `2`. Runs do real work only in the last 2 hours before your weekly Claude limit resets. The tool reads the reset time itself.
   - **`max_five_hour_utilization`**, **`max_weekly_utilization`**, the two `claim_start_margin_*` keys, `reset_buffer_minutes` and **`stop_on_overage`:** the other usage-gate settings (see *Usage gate*). Keep the defaults unless you have a reason.
   - **`selection`:** what to attempt.
     - `sources` can include `saved` (your saved list on prove2.me, the easiest way to steer it), `missions` (the open leaves of the `mission_ids` you list) and `search` (`query`, `tags`, `sort`).
     - Filters: `max_statement_chars`, `skip_flagged` and `skip_attempted_by_me`.
   - **`dry_run`:** keep it `true` until you've read a few logs.
   - **`notify`:** when to send you a notification; see *Notifications* below.

### 3. Cloud environment

At [claude.ai/code](https://claude.ai/code), open the environment selector and choose **New environment**. Fill in:

- **Network access: Custom.** Tick *Also include default list of common package managers*, and add:
  ```
  prove2.me
  lakecache.blob.core.windows.net
  *.lean-lang.org
  release-assets.githubusercontent.com
  objects.githubusercontent.com
  ```
  If setup reports that Lean or the Mathlib cache could not be downloaded, switch to **Full**.
- **Environment variables:**
  ```
  PROVE2ME_CREDENTIALS={"api_key":"p2m_..."}
  BASH_DEFAULT_TIMEOUT_MS=600000
  BASH_MAX_TIMEOUT_MS=1800000
  ```
  - ⚠️ Environment variables are **visible to anyone who uses that environment**. On Team and Enterprise plans there's no hidden credential store yet, so use a **personal** environment, never an organization-shared one. The value is only a Prove2me key: it expires in 30 days and you can replace it at any time.
- **Setup script:** paste the whole of [`scripts/setup.sh`](scripts/setup.sh).
  - The environment caches its result only if setup finishes within about 5 minutes, so the script time-boxes itself.
  - Whatever doesn't fit (usually part of the Mathlib download) is finished at the start of each run.

### 4. Routine

Create the routine at [claude.ai/code/routines](https://claude.ai/code/routines), or with `/schedule` in Claude Code. Set:

- **Repositories:** your private data repo and this tool repo, nothing else. The routine clones both; logs are pushed only to the data repo.
  - While this repo is private, attaching it is the only way a run can get the tool. Once it is public, the plan is to attach only the data repo and have each run download the tool at a pinned version with [`scripts/bootstrap.sh`](scripts/bootstrap.sh) (variable `AUTOPROVER_REF`).
- **Environment:** the one from step 3.
- **Prompt:** paste [`prompts/routine-trigger.md`](prompts/routine-trigger.md). It locates both clones and hands over to the full instructions in [`prompts/routine.md`](prompts/routine.md).
- **Model:** use the selector by the prompt. Opus is the strongest prover; Sonnet uses less allowance.
- **Connectors:** remove all. The routine needs none.
- **Schedule:** once a week, 2 hours before your weekly reset plus 7 minutes. Run `python3 scripts/p2m.py schedule` on any machine signed in to your Claude account: it prints the weekly cron line in UTC (for example `7 6 * * 2`) and your local time. Set it with `/schedule update`. The cron is in UTC, so daylight saving does not shift it. If your reset time changes, a run notifies you with the new line.

Then click **Run now** once, open the run to watch it, and check `logs/` in your data repo. Outside the 2-hour window the run stops at the usage gate and notifies you that the schedule looks misaligned; that is expected for a manual run (see *Usage gate* for `AUTOPROVER_IGNORE_WINDOW`).

**Note:** a green run status only means the session ran. Read the log to see what it actually did.

## Results

Your data repo's `logs/` folder holds, for each run:
- `<run_id>.md`: a table of theorem, outcome, submission id and note.
- `<run_id>.jsonl`: every event of the run.
- `<run_id>/`: in dry run, the solutions that would have been submitted.

Earlier logs are also how the tool avoids retrying theorems it already attempted.

Outcomes:
- **`ACCEPTED` / `SKETCH_ACCEPTED`:** verified by Prove2me.
- **`CE`, `WA`, `SORRY`, `FAILED`, `ERROR`:** rejected by the server. See the [Prove2me status glossary](https://github.com/prove2me/prove2me_workspace/blob/main/references/prove.md).
- **`DRY_RUN_PASSED_LOCAL_CHECKS`:** would have been submitted.
- **`GAVE_UP`, `OUT_OF_TIME`, `USAGE_LIMIT`, `SKIPPED`:** nothing was submitted.

## Notifications

At the end of each run, the tool can tell you what happened. Set `notify` in `autoprover.config.json`:

- **`important`** (default): only runs that submitted something (whatever the verdict), or that would have in dry run, and runs that stopped on something only you can fix: Prove2me key missing or expired, Lean setup failed, paid overage, usage unreadable, a schedule that no longer matches your weekly reset, or a tool error.
- **`every_run`**: also runs that attempted claims but submitted nothing.
- **`off`**: no notifications. The logs are still written.

Runs that stop at a usage cap, or near the reset, don't notify by themselves; their log is pushed.

A message looks like `prove2me-autoprover: 2 accepted (theorem_a, theorem_b), 1 rejected (CE). Log: logs/<run_id>.md`, or `prove2me-autoprover needs you: Prove2me API key missing or rejected; ...`.

**Push notification (default).** The agent sends the message as a Claude push notification. You receive it if the Claude mobile or desktop app is signed in to the same account with notifications turned on. If push isn't available in a run, nothing is sent; the log is always the full record.

**Webhook (optional).** To get the same message in Slack, Discord or any phone via ntfy:

1. Get a webhook URL:
   - **Slack:** create an [incoming webhook](https://api.slack.com/messaging/webhooks) for a channel (`https://hooks.slack.com/services/...`).
   - **Discord:** channel settings, *Integrations*, *Webhooks*, *New Webhook*, *Copy Webhook URL*.
   - **ntfy:** pick a hard-to-guess topic name and subscribe to it in the [ntfy app](https://ntfy.sh); the URL is `https://ntfy.sh/<topic>`.
2. Add it to the cloud environment's variables: `AUTOPROVER_WEBHOOK_URL=<url>`. Treat the URL as a secret, since anyone who has it can post to your channel. (The config key `notify_webhook_url` also works, but the data repo is the wrong place for a secret.)
3. With **Custom** network access, add the webhook's domain to the environment's allowed domains: `hooks.slack.com`, `discord.com` or `ntfy.sh`.

A failed webhook call only prints a warning; it never stops a run. Test it locally with `python3 scripts/p2m.py notify --message "test"`.

## Fallback: GitHub Actions

If routines don't work for you, [`.github/workflows/autoprover.yml`](.github/workflows/autoprover.yml) runs the same prompt on GitHub's runners with [`anthropics/claude-code-action`](https://github.com/anthropics/claude-code-action), authenticated with a `claude setup-token` token from your subscription.

This route is **untested so far**. Setup notes are at the top of the workflow file.

## Development

```bash
export PROVE2ME_WORKSPACE=$HOME/autoprover_ws        # a dedicated dir: setup overwrites its lakefile
export PROVE2ME_CREDENTIALS_FILE=/path/to/credentials.json
export AUTOPROVER_DATA=/path/to/your-data-repo      # config + logs
bash scripts/setup.sh && bash scripts/prepare.sh
python3 scripts/p2m.py status
python3 scripts/p2m.py usage [--for start-claim]     # go/no-go; AUTOPROVER_IGNORE_WINDOW=1 skips the lead-window rule
python3 scripts/p2m.py schedule                      # weekly cron line for (reset - lead_hours)
python3 -m unittest discover -s tests                # offline usage-gate tests
python3 scripts/p2m.py candidates
python3 scripts/p2m.py fetch <theorem_id>
python3 scripts/p2m.py solution <submission_id>        # read an earlier attempt
python3 scripts/p2m.py check <theorem_id> $PROVE2ME_WORKSPACE/Solutions/Sol_<name>.lean
AUTOPROVER_WEBHOOK_URL=https://ntfy.sh/<topic> python3 scripts/p2m.py notify --message test
AUTOPROVER_DRY_RUN=true python3 scripts/p2m.py submit <theorem_id> <file> --explanation-file expl.md
```

| Path | What |
|---|---|
| `template/` | starting files for a user's private data repo |
| `prompts/routine-trigger.md` | the short prompt pasted into the routine |
| `prompts/routine.md` | the agent's full instructions |
| `scripts/setup.sh` | environment setup script (cached) |
| `scripts/bootstrap.sh` | future public path: download the tool at `AUTOPROVER_REF` (unused while private) |
| `scripts/prepare.sh` | per run: credentials, environment pin, smoke test; Mathlib update and cache only if the smoke test fails |
| `scripts/p2m.py` | Prove2me client, claim selection, local gates, submission, logs |
| `tests/` | offline tests of the usage gate (no network, no Claude calls) |

## Limitations

- **One environment per run.** Only theorems in Prove2me's default Lean/Mathlib environment are attempted.
- **Usage is checked, not metered.** The gate reads usage at checkpoints (run start, each claim, each build, each submission). Between two checkpoints the agent can use more than expected; see *Usage gate* for the bound.
- **Local type check can be skipped.** It is skipped when the solution and target files declare the same helper names. The Prove2me server still checks the type.
- **Setup cache expires weekly.** The environment's cache lasts about 7 days, so weekly runs usually start by re-downloading part of Mathlib, which takes several minutes.

## License

Apache 2.0, matching Prove2me's terms for public contributions.
