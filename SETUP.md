# Setting up prove2me-autoprover

This file serves two readers:

- **You**, setting it up by hand: follow the steps in order.
- **Claude**, setting it up for you: paste this line into Claude Code (the app or the CLI) and answer its questions:

  ```
  Set up prove2me-autoprover for me by following SETUP.md in github.com/sattath/prove2me-autoprover
  ```

Every step is marked **[You]** (only you can do it, usually in a browser) or **[Claude]** (Claude does it; by hand you do it yourself). Every step ends with a **Check**, so a step that is already done is skipped, and running the setup again is safe.

Total time: about 20 minutes, mostly waiting for the first test run.

## Instructions for Claude

Read this whole file before starting. Then:

- **Never ask for, read, print or store the Prove2me API key.** The user pastes it into the cloud environment themselves. If the user pastes it into chat anyway, do not repeat it, and tell them to mint a new one, since the chat now holds it.
- Do the **[Claude]** steps yourself. For a **[You]** step, give the user the exact clicks and the ready-to-paste values from this file, then wait until they say it is done and run the step's Check.
- Run each step's Check first. If it passes, say so and move on.
- Ask before anything outward-facing that this file does not already cover: creating the repo, creating or changing the routine, starting a run, and switching to live mode each need the user's yes.
- Ask the user's choices one at a time, with a recommended default.
- If a Check fails twice, stop and tell the user what you saw. Do not improvise around it.

## Step 0. What you need [You]

- A Claude subscription (Pro, Max, Team or Enterprise) with Claude Code, and access to Claude Code on the web (claude.ai/code).
- A [Prove2me](https://prove2.me) account.
- A GitHub account, connected to Claude Code on the web: claude.ai/code must be able to clone your private repositories.
- For Claude-driven setup: the `gh` CLI, signed in (`gh auth login`).

**Check [Claude]:** `gh auth status` succeeds, and `gh repo view sattath/prove2me-autoprover` works (while the tool repo is private, this needs access to it).

## Step 1. Turn off paid extra usage [You]

If "extra usage" (usage credits) is on, a run can continue on paid overage after your subscription allowance runs out, **and you will be charged**. The tool checks for overage at every step and stops (see *Usage gate* in the README), but that check is a safeguard, not a guarantee.

Open [claude.ai/settings/usage](https://claude.ai/settings/usage) and turn extra usage off. On Team and Enterprise plans an admin does this at claude.ai/admin-settings/usage.

While you are there, note when your **weekly** limit resets. Step 5 needs it.

**Check:** you confirm extra usage is off.

## Step 2. Prove2me API key [You]

On prove2.me, log in, open the account menu and click **API key**. Your secret value is the whole line `{"api_key":"p2m_..."}`. Keep it for step 4. **Don't paste it into chat with Claude.**

**Keys expire after 30 days, but you paste one only once.** Every run renews the key and stores the new one, encrypted, in your data repo (see *Prove2me key renewal* in the README).

**Check:** you have the key ready.

## Step 3. Private data repo [Claude]

Your data repo holds your settings (`autoprover.config.json`) and the run logs. It must be **private**.

1. Ask the user for the repo name (default `prove2me-autoprover-data`) and whether to create it under their GitHub account.
2. Create it from the files in [`template/`](template/):

   ```bash
   gh repo create <name> --private --clone
   cp -R <tool clone>/template/. <name>/
   ```

   `<tool clone>` is a clone of this repo; make one with `gh repo clone sattath/prove2me-autoprover` if needed.
3. Ask the user's choices for `autoprover.config.json`, one at a time, and write them:
   - **`selection`:** what to attempt.
     - `sources` can include `saved` (your saved list on prove2.me, the easiest way to steer it), `missions` (the open leaves of the `mission_ids` you list) and `search` (`query`, `tags`, `sort`).
     - Filters: `max_statement_chars`, `skip_flagged` and `skip_attempted_by_me`.
   - **`dry_run`:** keep it `true` for now. Step 7 switches to live.
   - **`notify`:** when to send a notification: `important` (default), `every_run` or `off`. See *Notifications* in the README.
   - **`discussion`:** `"off"` (default) or `"deadends"` to let runs post short dead-end notes in mission discussions, at most `max_comments_per_run` (default 2) per run. See *Discussions* in the README.
   - Leave the usage-gate keys at their defaults unless the user has a reason: `lead_hours` (default `2`: runs work only in the last 2 hours before the weekly reset), `max_five_hour_utilization`, `max_weekly_utilization`, the two `claim_start_margin_*` keys, `reset_buffer_minutes` and `stop_on_overage`. See *Usage gate* in the README.
4. Commit and push to the default branch.

**Check:** `gh repo view <owner>/<name> --json visibility,defaultBranchRef` shows `PRIVATE`, and `autoprover.config.json` is on the default branch and is valid JSON.

## Step 4. Cloud environment [You]

There is no command or API for creating a cloud environment yet, so this step is in the browser. Claude shows you the values; you paste them.

At [claude.ai/code](https://claude.ai/code), open the environment selector and choose **New environment** (or edit the one you already use for this tool). Fill in:

- **Name:** `prove2me-autoprover`.
- **Network access: Custom.** Tick *Also include default list of common package managers*, and add:
  ```
  prove2.me
  lakecache.blob.core.windows.net
  *.lean-lang.org
  release-assets.githubusercontent.com
  objects.githubusercontent.com
  ```
  If setup reports that Lean or the Mathlib cache could not be downloaded, switch to **Full**. If you add a webhook for notifications (README, *Notifications*), add its domain too.
- **Environment variables** (paste your own key in the first line):
  ```
  PROVE2ME_CREDENTIALS={"api_key":"p2m_..."}
  BASH_DEFAULT_TIMEOUT_MS=600000
  BASH_MAX_TIMEOUT_MS=1800000
  ```
  - ⚠️ Environment variables are **visible to anyone who uses that environment**. On Team and Enterprise plans, use a **personal** environment, never an organization-shared one.
  - ⚠️ **This first key has two roles.** It logs in until it expires, and it is also the password that encrypts every renewed key in your data repo. **Never delete or change `PROVE2ME_CREDENTIALS`**, even after Prove2me starts rejecting the key in it, or the renewed key can no longer be read.
  - **Optional: separate the two roles.** Add a fourth line, `AUTOPROVER_ENCRYPTION_SECRET=...`, a random secret that becomes the encryption password. Then `PROVE2ME_CREDENTIALS` may be removed after the first successful renewal, and `AUTOPROVER_ENCRYPTION_SECRET` is the variable that must stay. See *Prove2me key renewal* in the README.
    - To generate it, run `python3 scripts/p2m.py new-secret` in a clone of this repo. It puts the ready-to-paste line on the clipboard (macOS, Windows, WSL and Linux desktops), or, without a clipboard, in a file only you can read, `~/autoprover-secret.txt` (delete it after pasting). It never prints the secret.
    - Claude: run that command yourself, tell the user where the line went, and never read the file or the clipboard. Don't keep any other copy: if the secret is ever lost, a fresh Prove2me key (step 2) and a new secret restore everything.
  - The environment's "network secrets" option does not fit here: it adds a fixed header, while Prove2me exchanges the key for a token in a request body.
- **Setup script:** paste the whole of [`scripts/setup.sh`](scripts/setup.sh). (Claude: offer to copy it to the clipboard, e.g. `pbcopy < scripts/setup.sh` on macOS.)
  - The environment caches its result only if setup finishes within about 5 minutes, so the script time-boxes itself.
  - Whatever doesn't fit (usually part of the Mathlib download) is finished at the start of each run.

**Check:** you confirm the environment is saved under the name above. The test run in step 6 checks the rest.

## Step 5. Routine [Claude]

The routine is the scheduled cloud agent that does the work. Claude creates it with its routine tool (in Claude Code, `/schedule`; Claude can also call the routine API directly). By hand, create it at [claude.ai/code/routines](https://claude.ai/code/routines).

Settings:

- **Name:** `prove2me-autoprover`.
- **Repositories:** your private data repo and this tool repo, nothing else. The routine clones both; logs are pushed only to the data repo.
  - While this repo is private, attaching it is the only way a run can get the tool. Once it is public, the plan is to attach only the data repo and have each run download the tool at a pinned version with [`scripts/bootstrap.sh`](scripts/bootstrap.sh) (variable `AUTOPROVER_REF`).
- **Environment:** the one from step 4.
- **Prompt:** the whole of [`prompts/routine-trigger.md`](prompts/routine-trigger.md). It locates both clones and hands over to the full instructions in [`prompts/routine.md`](prompts/routine.md), which runs read fresh from GitHub each time.
- **Model:** ask the user. Opus is the strongest prover; Sonnet uses less allowance.
- **Tools:** Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, PushNotification.
- **Connectors:** none.
- **Schedule:** once a week, at the weekly reset minus `lead_hours` (2 hours) plus 7 minutes, as a cron line in UTC (for example `7 6 * * 2`). The cron is in UTC, so daylight saving does not shift it.
  - Claude: run `python3 scripts/p2m.py schedule` in the tool clone. It reads the reset time from your Claude account and prints the cron line. It needs the `claude` CLI; if that fails, compute the line from the reset time the user noted in step 1.
  - If the line is wrong, the first scheduled run notices that it is outside the window and notifies you with the corrected line. The same happens if your reset time changes later.

If a routine named `prove2me-autoprover` already exists, update it instead of creating a second one.

**Check:** the routine is listed (`/schedule list`, or the routine tool's list action) with both repositories, the environment from step 4 and the cron line above.

## Step 6. Test run [Claude]

A test run goes through the whole pipeline (clone, setup, Lean, usage gate, one claim, log, notification) without submitting anything:

1. In the data repo, set `"test_run": true` in `autoprover.config.json`, commit and push. A test run is a dry run with at most one claim, and it skips the 2-hour window rule, so it works at any time. The usage caps still apply: if your weekly usage is above 75%, the test stops early at the gate, which is a valid result.
2. Start the routine now (**Run now** on its page, `/schedule run`, or the routine tool's run action), and give the user the run's link.
3. When it ends (usually 10 to 45 minutes), read the run's log (the routine tool's run log, or open the run) and the new `logs/<run_id>.md` in the data repo.
4. Set `"test_run": false` again, commit and push. **Don't skip this:** while it is `true`, every run is a one-claim dry run.

A healthy run shows, in order: both repositories cloned, the setup script completed (or "cached from previous run"), `p2m usage` with `"go": true`, `prepare.sh` printing `Lean + Mathlib ready`, a claim fetched and checked, then a log committed to `logs/`. Its `Mode:` line reads `TEST RUN`, and its `Stopped because:` line says why it ended.

Common problems:

| What you see | What to do |
|---|---|
| Clone fails | claude.ai/code has no access to one of the repos: connect GitHub there and grant it both repositories. |
| `API key rejected` / credentials missing | Mint a new key (step 2) and replace the environment variable (step 4). Needed only if no run renewed the key for about 4 weeks. |
| Lean or Mathlib download failed | Switch the environment's network access to **Full** (step 4). |
| `Stopped because: ... usage ... >= cap` | Your own usage is above the caps; the gate worked. Test again when usage is lower. |
| No log and the run ended at once with "You've hit your weekly limit" | Your weekly limit was already used up. Test after it resets. |

**A green run status only means the session ran.** Read the log to see what it actually did.

**Check:** the test log exists and its `Stopped because:` line is not an error, and `test_run` is back to `false`.

## Step 7. Go live [Claude, with your yes]

After reading a few dry-run logs (scheduled runs write one every week), the user decides whether to go live. With their explicit yes, set `"dry_run": false` in `autoprover.config.json`, commit and push. From then on, proofs that pass every local check are submitted under the user's Prove2me account, each with a footer saying it was made by prove2me-autoprover.

**Check:** `autoprover.config.json` on the default branch has the intended `dry_run` value.

## Afterwards

- **Key renewal is automatic.** Each run renews the Prove2me key, so it stays valid for 30 days after the last run. Never delete the encryption password from the environment: `PROVE2ME_CREDENTIALS` (your first key), or `AUTOPROVER_ENCRYPTION_SECRET` if you added one. You need to paste a new key (steps 2 and 4) only if a run notifies you that renewal failed repeatedly, or that the key was rejected because no run renewed it for about 4 weeks.
- **Debugging:** ask Claude Code to list the routine's runs and read a run's log; it can do this without opening claude.ai.
- **Updates:** each run clones the tool fresh from GitHub, so fixes to the tool reach you automatically. Only the two pasted copies do not update by themselves: the routine's prompt (step 5) and the environment's setup script (step 4). When the tool's changelog or README says one of them changed, paste it again, or ask Claude to update the routine's prompt.
