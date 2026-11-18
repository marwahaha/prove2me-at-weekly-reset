# My prove2me-at-weekly-reset data

Private data repo for [prove2me-at-weekly-reset](https://github.com/sattath/prove2me-at-weekly-reset):

- `autoprover.config.json`: my settings (usage gate, caps, which claims to attempt, dry run on/off).
- `logs/`: one `<run_id>.md` summary and `<run_id>.jsonl` event log per run, written and pushed by the routine. In dry run, `logs/<run_id>/` holds the solutions that would have been submitted.

Keep this repo private. It holds no secrets: the Prove2me key lives in the cloud environment's variables.
