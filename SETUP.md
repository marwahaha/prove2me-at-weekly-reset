# Setting up prove2me-at-weekly-reset

This file serves two readers:

- **You**, setting it up by hand: follow the steps in order.
- **Claude**, setting it up for you: paste this line into Claude Code (the app or the CLI) and answer its questions:

  ```
  Set up prove2me-at-weekly-reset for me by following SETUP.md in github.com/sattath/prove2me-at-weekly-reset
  ```

Every step is marked **[You]** (only you can do it, usually in a browser) or **[Claude]** (Claude does it; by hand you do it yourself). Every step ends with a **Check**, so a step that is already done is skipped, and running the setup again is safe.

Total time: about 20 minutes, mostly waiting for the first test run.

## Instructions for Claude

Read this whole file before starting. Then:

- **Start with a short welcome**, before any check or question, in your own words and a few lines at most. Cover:
  - what the tool does: once a week, just before the user's weekly Claude limit resets, a cloud agent uses the allowance they have left to try to prove open theorems on Prove2me in Lean;
  - what setup involves: about 20 minutes, a few things they do in the browser (Claude walks them through each), the rest done by Claude;
  - what they need: their Claude subscription, a Prove2me account and a GitHub account;
  - that nothing is submitted under their name until they decide to go live at the end.

  For example: "I'll help you set up prove2me-at-weekly-reset. Once a week, just before your weekly Claude limit resets, it uses the allowance you have left to try to prove open theorems on Prove2me. Setup takes about 20 minutes: you'll do a few things in your browser, and I'll walk you through each one and do the rest. You'll need your Prove2me and GitHub accounts. Nothing is submitted under your name until you decide to go live at the end. Let's start."

- **Never ask for, read, print or store the Prove2me API key.** The user pastes it into the cloud environment themselves. If the user pastes it into chat anyway, do not repeat it, and tell them to mint a new one, since the chat now holds it.
- Do the **[Claude]** steps yourself. For a **[You]** step, give the user the exact clicks and the ready-to-paste values from this file, then wait until they say it is done and run the step's Check.
  - Spell each **[You]** step out in your message, one step at a time: what to do, where (a link), and which buttons. Never refer to a step only by its number ("are steps 1 and 2 done?"): the user has not read this file.
- Run each step's Check first. If it passes, say so and move on.
- Ask before anything outward-facing that this file does not already cover: creating the repo, creating or changing the routine, starting a run, and switching to live mode each need the user's yes.
- Ask the user's choices one at a time, with a recommended default. Where the client can show clickable choices (an interactive form or a menu), use them instead of plain text.
- If a Check fails twice, stop and tell the user what you saw. Do not improvise around it.
- If `gh` or `git` fails with a TLS or certificate error (e.g. `OSStatus -26276`) while your shell is sandboxed, that is the sandbox, not GitHub: rerun the command outside the sandbox, with the user's approval.

## Step 0. What you need [You]

- A Claude subscription (Pro, Max, Team or Enterprise) with Claude Code, and access to Claude Code on the web (claude.ai/code).
- A [Prove2me](https://prove2.me) account.
- A GitHub account, connected to Claude Code on the web: claude.ai/code must be able to clone your private repositories.
- Nothing to install. If the [`gh` CLI](https://cli.github.com) happens to be installed and signed in, Claude uses it to create your data repo; otherwise you create it in the browser in step 3 (about two minutes).

**Check [Claude]:**
- Run `gh auth status`. If it succeeds, step 3 uses the `gh` path; if `gh` is missing or not signed in, it uses the browser path. Do not install `gh` or ask the user to; just say which path step 3 will take.
- Get a copy of this repo to work from: `gh repo clone sattath/prove2me-at-weekly-reset`, or `git clone https://github.com/sattath/prove2me-at-weekly-reset`, or download and unpack <https://github.com/sattath/prove2me-at-weekly-reset/archive/refs/heads/main.zip>. Below, `<tool clone>` is that folder.

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

1. Ask the user for the repo name (default `prove2me-at-weekly-reset-data`) and whether to create it under their GitHub account.
2. Make a local folder `<name>` with the files in [`template/`](template/):
   - **`gh` path:** `gh repo create <name> --private --clone`, then `cp -R <tool clone>/template/. <name>/`.
   - **Browser path:** `mkdir <name> && cp -R <tool clone>/template/. <name>/` (nothing on GitHub yet).
3. Ask the user **only these three choices** for `autoprover.config.json`, one at a time, and write them:
   - **`selection.fields`:** the user's areas of interest. Run `python3 scripts/p2m.py fields` (or `p2m.py fields quantum` to filter) in the tool clone; it lists Prove2me's fields with their numbers of missions and unfinished missions. (Prove2me's live list needs the API key, which you never have, so it prints the snapshot shipped in the tool. That is expected.) Let the user pick any number of them from a clickable multi-select (in the Claude app, an interactive form grouped by area, each field with its number of unfinished missions; in a plain terminal, a numbered list), never a wall of text, and write the slugs, e.g. `["quantum-information", "theoretical-computer-science"]`. An empty list means no preference: runs then take open theorems from the whole library, most votes first.
   - **`notify`:** when to send a notification: `important` (default), `every_run` or `off`. See *Notifications* in the README.
   - **`discussion`:** `"off"` (default) or `"deadends"` to let runs post short dead-end notes in mission discussions, at most `max_comments_per_run` (default 2) per run. See *Discussions* in the README.

   **Do not ask about anything else**; the template's defaults are right for a new user, and asking about them only adds questions. In particular:
   - `dry_run` stays `true` (step 7 switches to live) and `test_run` stays `false` (step 6 sets it briefly).
   - The rest of `selection` stays as is. Mention in one sentence that theorems the user saves on prove2.me are always tried first, before the fields. (For reference: `sources` runs saved theorems, then `mission_ids`, then the fields' unfinished missions, at most `missions_per_run` per run, highest closability first, and only without fields a whole-library search by votes; the filters are `max_statement_chars`, `skip_flagged` and `skip_attempted_by_me`.)
   - The usage-gate keys stay at their defaults (`lead_hours` 2, the caps and margins; see *Usage gate* in the README), unless the user brings them up.
4. Put the files on GitHub:
   - **`gh` path:** commit and push to the default branch.
   - **Browser path [You]:** give the user these steps, with the folder's full path:
     1. Open [github.com/new](https://github.com/new). Repository name: `<name>`. Choose **Private**. Leave everything else as it is, and click **Create repository**.
     2. On the new repo's page, click **uploading an existing file**. Drag `autoprover.config.json` and `README.md` from the folder `<full path>` onto the page, then click **Commit changes**. (`.gitignore` can stay behind; runs never need it.)

**Check:**
- `gh` path: `gh repo view <owner>/<name> --json visibility,defaultBranchRef` shows `PRIVATE`, and `autoprover.config.json` is on the default branch and is valid JSON. Right after the first push GitHub may still report no default branch; wait 10 seconds and check again (that does not count as a failed Check).
- Browser path: `curl -s -o /dev/null -w '%{http_code}' https://github.com/<owner>/<name>` prints `404` (a public repo would give `200`; this is how you know it is private without signing in), and the user confirms that the repo's page lists `autoprover.config.json`.

**Browser path, later steps:** you cannot push to or read the private data repo. Where steps 6 and 7 say to change `autoprover.config.json` and push, give the user the exact edit instead: open the file on GitHub, click the pencil icon, change that one line, click **Commit changes**. Where they say to read a log in the data repo, ask the user to open it and paste its text, or read the run's own output through the routine tool.

## Step 4. Cloud environment [You]

There is no command or API for creating a cloud environment yet, so this step is in the browser. Claude shows you the values; you paste them.

At [claude.ai/code](https://claude.ai/code), click the environment button (a cloud icon and an environment name, just below the prompt box) and choose **+ New environment** (or edit the one you already use for this tool). **Click-by-click screenshots:** [docs/environment-howto](docs/environment-howto/README.md).

Claude, if you have a browser tool (e.g. the Claude app's browser pane), filling in the form for the user is the default; in the test setup it turned "I don't understand" into one action for the user. Ask the user to sign in to claude.ai in that browser themselves. Fill in everything below except the key, leaving the first line of the environment variables empty. The setup script editor ignores typed or keyboard-pasted text; insert the script with a synthetic paste event and compare what the editor holds against `scripts/setup.sh`. Then hand over: the user types the key line and clicks **Add environment**. Don't look at the page (no screenshots, no page reads, no page text) from the moment they start typing it; afterwards, check the result from the environment list (Check below), not from the page. Never type credentials yourself, including the claude.ai sign-in. If the page doesn't match these instructions (labels changed, a menu won't open twice in a row), stop and walk the user through the screenshots instead of improvising. Without a browser tool, walk the user through the screenshots.

Fill in:

- **Name:** `prove2me-at-weekly-reset`.
- **Network access: Limited.** Keep **Allow package managers** ticked, and add these allowed domains:
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
  ENABLE_CLAUDEAI_MCP_SERVERS=false
  ```
  - `ENABLE_CLAUDEAI_MCP_SERVERS=false` keeps your claude.ai connectors (Gmail, Drive, Slack, ...) out of every run in this environment, even if one is attached to the routine by mistake. It is one layer of several; see step 5.
  - The page shows a warning under this box not to add secrets. Here that is expected: tell the user before they get there. It is why the next point matters.
  - ⚠️ Environment variables are **visible to anyone who uses that environment**. On Team and Enterprise plans, use a **personal** environment, never an organization-shared one.
  - ⚠️ **This first key has two roles.** It logs in until it expires, and it is also the password that encrypts every renewed key in your data repo. **Never delete or change `PROVE2ME_CREDENTIALS`**, even after Prove2me starts rejecting the key in it, or the renewed key can no longer be read.
  - **Optional: separate the two roles.** Add a fifth line, `AUTOPROVER_ENCRYPTION_SECRET=...`, a random secret that becomes the encryption password. Then `PROVE2ME_CREDENTIALS` may be removed after the first successful renewal, and `AUTOPROVER_ENCRYPTION_SECRET` is the variable that must stay. See *Prove2me key renewal* in the README. Claude: mention this option in one sentence; don't make it a question the user has to answer before saving. The default is to skip it.
    - To generate it, run `python3 scripts/p2m.py new-secret` in a clone of this repo. It puts the ready-to-paste line on the clipboard (macOS, Windows, WSL and Linux desktops), or, without a clipboard, in a file only you can read, `~/autoprover-secret.txt` (delete it after pasting). It never prints the secret.
    - Claude: run that command yourself, tell the user where the line went, and never read the file or the clipboard. Don't keep any other copy: if the secret is ever lost, a fresh Prove2me key (step 2) and a new secret restore everything.
  - The environment's "network secrets" option does not fit here: it adds a fixed header, while Prove2me exchanges the key for a token in a request body.
- **Setup script:** the whole of [`scripts/setup.sh`](scripts/setup.sh). Easiest by hand: the editor's **Choose file** button, picking `scripts/setup.sh` from a download or clone of this repo; otherwise paste it. (Claude: offer to copy it to the clipboard, e.g. `pbcopy < scripts/setup.sh` on macOS.) The editor then shows 104 lines; the file's trailing newline isn't counted, so nothing is missing.
  - The environment caches its result only if setup finishes within about 5 minutes, so the script time-boxes itself.
  - Whatever doesn't fit (usually part of the Mathlib download) is finished at the start of each run.

**Check [Claude]:** the environment is listed under its name, from the routine tool's list of environments (in Claude Code, the `RemoteTrigger` tool shows the available environments with their IDs). Note its ID for step 5. Without that tool, the user confirms it is listed under **Personal** when they open the environment button again. The test run in step 6 checks the rest.

## Step 5. Routine [Claude]

The routine is the scheduled cloud agent that does the work. Claude creates it by calling the routine API directly (in Claude Code, the `RemoteTrigger` tool; load it with ToolSearch if needed). Don't run the `/schedule` skill for this: it opens with a generic heads-up (no git repo here, MCP connectors) that doesn't apply and confused the user in testing. By hand, create it at [claude.ai/code/routines](https://claude.ai/code/routines).

Settings:

- **Name:** `prove2me-at-weekly-reset`.
- **Repositories:** your private data repo and this tool repo, nothing else. The routine clones both; logs are pushed only to the data repo.
  - While this repo is private, attaching it is the only way a run can get the tool. Once it is public, the plan is to attach only the data repo and have each run download the tool at a pinned version with [`scripts/bootstrap.sh`](scripts/bootstrap.sh) (variable `AUTOPROVER_REF`).
- **Environment:** the one from step 4.
- **Prompt:** the whole of [`prompts/routine-trigger.md`](prompts/routine-trigger.md). It locates both clones and hands over to the full instructions in [`prompts/routine.md`](prompts/routine.md), which runs read fresh from GitHub each time.
- **Model:** default `opus`. Offer the user the options:

  | Model setting | What it means |
  |---|---|
  | `opus` (default) | The newest Opus, the strongest prover. It is an alias, so the routine moves to a newer Opus by itself when one comes out. |
  | `sonnet` | The newest Sonnet. Uses less allowance per run, proves less. Also moves to newer versions by itself. |
  | A full model ID, e.g. `claude-opus-5-5` | Pinned to that exact version; it never changes until you edit the routine. |

  In the routine dialog, pick the model by name, e.g. **Opus**. Claude, through the routine API: set the model to the alias `opus`, not a full ID, unless the user asks to pin one.
- **Tools:** Bash, Read, Write, Edit, Glob, Grep, PushNotification. **No WebSearch or WebFetch by default**: Lean and the whole of Mathlib are on the machine, and the best runs so far used no web. Web tools would add a way to send data out that bypasses the environment's network allowlist (WebFetch can request any address), and more untrusted text. Claude, through the routine API: also set `disallowed_tools` to `["WebSearch", "WebFetch", "mcp__github"]` (the last is a GitHub tool set built into every cloud session; runs use plain `git` instead).
  - **Optional: full web access**, e.g. so the prover can read papers on arXiv. It takes two switches, on purpose: add WebSearch and WebFetch to the routine's tools (and remove them from `disallowed_tools`), **and** set `"allow_web": true` in `autoprover.config.json`. With only one of the two, the run's self-check stops the run. The cost: a run misled by hostile text could leak what its shell can read, i.e. your Prove2me key, the encryption secret and the data repo's contents (not your GitHub or Claude logins, which never enter the machine). To undo, reverse both switches.
- **Connectors: none. Remove them all.** Connectors (claude.ai's MCP integrations, such as Gmail, Drive or Slack) are set on the routine, not on the environment, and **all of your connectors are included by default**. In the routine dialog, open **Advanced settings → Connectors** and remove every one.
  - Why: every run reads text written by strangers on Prove2me. If such text ever misled the agent, an attached connector would let it act in that service under your name. Without connectors, a run can reach only your Prove2me account (through `p2m.py`'s guarded commands) and the two repositories.
  - Claude, through the routine API: send `clear_mcp_connections: true` when creating the routine, because the server otherwise attaches the user's connectors.
  - Local MCP servers on your computer never reach cloud runs, and neither do your personal `~/.claude` settings or memory.
  - **Three layers keep connectors and web tools out:** none attached here, `ENABLE_CLAUDEAI_MCP_SERVERS=false` in the environment (step 4), and a self-check at the start of every run: if any connector or web tool is available, the run stops before reading anything from Prove2me and notifies you. Three tool sets are built into every cloud session and are not connectors: `mcp__github__…`, `mcp__claude-code-remote__…` and `mcp__ccd_session__…` (which only proposes follow-up sessions to you). The self-check knows them (`p2m safety` lists them), and runs never use them.
- **Schedule:** once a week, at the weekly reset minus `lead_hours` (2 hours) plus 7 minutes, as a cron line in UTC (for example `7 6 * * 2`). The cron is in UTC, so daylight saving does not shift it.
  - Claude: run `python3 scripts/p2m.py schedule` in the tool clone. It reads the reset time from your Claude account and prints the cron line. It needs the `claude` CLI; if that fails, compute the line from the reset time the user noted in step 1.
  - If the line is wrong, the first scheduled run notices that it is outside the window and notifies you with the corrected line. The same happens if your reset time changes later.

If a routine named `prove2me-at-weekly-reset` already exists, update it instead of creating a second one. If another routine of this tool already runs on the same account under a different name, tell the user before creating this one: both would run in the same weekly slot, on the same Claude allowance and the same Prove2me account. Recommend creating the new one paused (`"enabled": false`) unless they mean to replace the old one.

Claude, the create request (fill in the `<...>` parts; generate a fresh lowercase v4 UUID; `content` is the whole of `prompts/routine-trigger.md`):

```json
{
  "name": "prove2me-at-weekly-reset",
  "cron_expression": "<cron line from p2m.py schedule>",
  "enabled": true,
  "clear_mcp_connections": true,
  "job_config": {"ccr": {
    "environment_id": "<environment ID from step 4>",
    "session_context": {
      "model": "opus",
      "sources": [
        {"git_repository": {"url": "https://github.com/<owner>/<data repo>"}},
        {"git_repository": {"url": "https://github.com/sattath/prove2me-at-weekly-reset"}}
      ],
      "allowed_tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "PushNotification"],
      "disallowed_tools": ["WebSearch", "WebFetch", "mcp__github"]
    },
    "events": [{"data": {
      "uuid": "<fresh uuid>", "session_id": "", "type": "user", "parent_tool_use_id": null,
      "message": {"role": "user", "content": "<prompts/routine-trigger.md>"}
    }}]
  }}
}
```

**Check:** the routine is listed (the routine tool's list or get action) with both repositories, the environment from step 4, the cron line above, the model, the tools above, and no connectors.

## Step 6. Test run [Claude]

A test run goes through the whole pipeline (clone, setup, Lean, usage gate, one claim, log, notification) without submitting anything:

Before starting it, tell the user in one or two sentences why nothing is submitted: the test checks the plumbing, and every new setup starts in dry run until they choose to go live (step 7). A proof it finds is not lost: it is saved in the data repo under `logs/<run_id>/`, marked `DRY_RUN_PASSED_LOCAL_CHECKS`, and the user can submit it by hand on prove2.me.

1. In the data repo, set `"test_run": true` in `autoprover.config.json`, commit and push. A test run is a dry run with at most one claim, and it skips the 2-hour window rule, so it works at any time. The usage caps still apply: if your weekly usage is above 75%, the test stops early at the gate, which is a valid result.
2. Start the routine now (**Run now** on its page, or the routine tool's run action), and give the user the run's link.
3. Nothing tells you when the run ends (usually 10 to 45 minutes). Wait for the data repo commit named `autoprover run <run_id>`, or check the routine tool's list of runs. Don't stop at the first new commit: every run first commits `autoprover: renew Prove2me API key (encrypted)`, before its log exists. Then read the run's log (the routine tool's run log, or open the run) and the new `logs/<run_id>.md` in the data repo.
4. Set `"test_run": false` again, commit and push. **Don't skip this:** while it is `true`, every run is a one-claim dry run.

A healthy run shows, in order: both repositories cloned, the setup script completed (or "cached from previous run"), `p2m usage` with `"go": true`, `prepare.sh` printing `Lean + Mathlib ready`, a claim fetched and at least one Lean file compiled, then a log committed to `logs/`. Its `Mode:` line reads `TEST RUN`, and its `Stopped because:` line says why it ended.

Common problems:

| What you see | What to do |
|---|---|
| Clone fails | claude.ai/code has no access to one of the repos: connect GitHub there and grant it both repositories. |
| `API key rejected` / credentials missing | Mint a new key (step 2) and replace the environment variable (step 4). Needed only if no run renewed the key for about 4 weeks. |
| Lean or Mathlib download failed | Switch the environment's network access to **Full** (step 4). |
| `Stopped because: ... usage ... >= cap` | Your own usage is above the caps; the gate worked. Test again when usage is lower. |
| No log and the run ended at once with "You've hit your weekly limit" | Your weekly limit was already used up. Test after it resets. |
| `HTTP 500` from Prove2me in the log | A temporary error on Prove2me's side. The run carries on with other candidates; nothing to fix. |
| `unsafe routine setup: <tools> available but not allowed` | A tool set appeared that the self-check doesn't know. If it is one of your connectors or web tools, remove it (step 5). If it is a tool set built into cloud sessions, report it to the maintainers; until a release knows it, add its prefix (e.g. `mcp__example`) to the routine's `disallowed_tools`. |

**A green run status only means the session ran.** Read the log to see what it actually did.

**Check:** the test log exists and its `Stopped because:` line is not an error, and `test_run` is back to `false`.

## Step 7. Go live [Claude, with your yes]

After reading a few dry-run logs (scheduled runs write one every week), the user decides whether to go live. With their explicit yes, set `"dry_run": false` in `autoprover.config.json`, commit and push. From then on, proofs that pass every local check are submitted under the user's Prove2me account, each starting with a line saying it was proved automatically by prove2me-at-weekly-reset, with a link to the tool.

**Check:** `autoprover.config.json` on the default branch has the intended `dry_run` value.

## Afterwards

- **Key renewal is automatic.** Each run renews the Prove2me key, so it stays valid for 30 days after the last run. Never delete the encryption password from the environment: `PROVE2ME_CREDENTIALS` (your first key), or `AUTOPROVER_ENCRYPTION_SECRET` if you added one. You need to paste a new key (steps 2 and 4) only if a run notifies you that renewal failed repeatedly, or that the key was rejected because no run renewed it for about 4 weeks.
- **Debugging:** ask Claude Code to list the routine's runs and read a run's log; it can do this without opening claude.ai.
- **Updates:** each run clones the tool fresh from GitHub and runs its **newest release tag** (`vYYYY.MM.DD`), not `main`. Runs can push branches but never tags (Anthropic's GitHub proxy rejects tag pushes), so code a misled run pushes is never executed by a later run. New releases reach you automatically. Only the two pasted copies do not update by themselves: the routine's prompt (step 5) and the environment's setup script (step 4). When the tool's changelog or README says one of them changed, paste it again, or ask Claude to update the routine's prompt.
- **Releasing (maintainers):** after pushing to `main`, tag the release: `git tag v$(date -u +%Y.%m.%d) && git push origin --tags` (add `.2`, `.3` for a second release the same day). Run `git fetch --tags` first: another maintainer session may already have tagged today. Until a tag is pushed, runs keep using the previous release.
  - **Trying a fix before releasing it:** tag it `rc-YYYY.MM.DD` (anything not starting with `v`, so live runs ignore it), and in a separate test environment set `AUTOPROVER_REF=rc-YYYY.MM.DD`. Runs of a routine using that environment check out that tag instead of the newest release. Remove the variable afterwards. Only tags can be pinned, never branches, because runs can push branches. Now and then, refresh the field list that setup shows: `python3 scripts/p2m.py fields --live > data/fields.json` (needs a Prove2me key).
