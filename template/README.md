# My prove2me-autoprover data

Private data repo for [prove2me-autoprover](https://github.com/sattath/prove2me-autoprover):

- `autoprover.config.json`: my settings (usage gate, caps, which claims to attempt, dry run on/off).
- `logs/`: one `<run_id>.md` summary and `<run_id>.jsonl` event log per run, written and pushed by the routine. In dry run, `logs/<run_id>/` holds the solutions that would have been submitted.

Keep this repo private. It holds no secrets: the Prove2me key lives in the cloud environment's variables.
