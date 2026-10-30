The compactor's deploy script, `deploy/compactor/setup.sh`, can't complete a first deploy. It grants the compactor's
service account `roles/storage.objectAdmin` on the data bucket (`--data-bucket`) but never makes that bucket, so a
first run fails at the grant.

- Make `setup.sh` create the data bucket when it doesn't exist: private, with uniform bucket-level access and public
  access prevention, in the job's region; keep it when it exists, as the script already does for the service
  account and the registry. Never create the runs (outbox) bucket: it is hangar's.
- At the end, print the line hangar's terraform needs,
  `run_bucket_readers = ["serviceAccount:flightdeck-compactor@<project>.iam.gserviceaccount.com"]`, and the command
  that checks a night's output: `FLIGHTDECK_DATA_URI=gs://<data-bucket>/parquet/v1 flightdeck query ...`.
- `--dry-run` prints every gcloud command it would run as a line starting with `+ gcloud`, and calls nothing.

Update `deploy/compactor/README.md` to match. Run `tests/test_deploy.py`.
