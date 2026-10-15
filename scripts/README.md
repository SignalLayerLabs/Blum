# Script catalog

[Documentation](../docs/README.md) · [Development](../docs/guides/development.md) · [Deployment](../docs/operations/deployment.md)

These entry points keep stable paths because Docker, CI, tests and trusted jobs call them directly. Run from the repository root with the appropriate dependencies and private environment. The catalog groups them by purpose without changing runtime contracts.

## Data inspection and verification

| Script | Purpose |
| --- | --- |
| [audit_historical_sources.py](audit_historical_sources.py) | Reproduce reviewed packaged-source hashes and acceptance counts |
| [audit_blum_release_dataset.py](audit_blum_release_dataset.py) | Inspect a model-release dataset and its gates |
| [build_historical_price_cache.py](build_historical_price_cache.py) | Build historical price inputs from configured providers; not a prospective track record |
| [verify_ascent_replay.py](verify_ascent_replay.py) | Reproduce a bounded price-only ASCENT replay offline |

## Trusted research and model operations

| Script | Purpose |
| --- | --- |
| [run_ascent.py](run_ascent.py) | Read stored status or explicitly run/resume a bounded experiment |
| [finrlx_runner.py](finrlx_runner.py) | Background runner boundary for the FinRL-X integration |
| [export_blum_model_release.py](export_blum_model_release.py) | Prepare a reviewed, redacted model-release dataset |
| [export_blum_training_dataset.py](export_blum_training_dataset.py) | Export reasoning records for inspection; raw exports do not automatically qualify for training |
| [train_blum_challenger.py](train_blum_challenger.py) | Optional HF training job code; paid training remains disabled |
| [evaluate_blum_challenger.py](evaluate_blum_challenger.py) | Evaluate a candidate against explicit immutable inputs |
| [promote_blum_model.py](promote_blum_model.py) | Explicit authenticated model publication/promotion tooling |

The current [data quarantine](../docs/research/data-quality.md) applies before any export is used for new training or promotion. An executable script is not evidence of eligibility or authorization to launch a paid job. Follow the [gated model operations guide](../docs/operations/huggingface-training.md).

## Release and runtime

| Script | Purpose |
| --- | --- |
| [check_space_metadata.py](check_space_metadata.py) | Validate the maintained root HF Space card contract |
| [check_release_revision.py](check_release_revision.py) | Reject stale main revisions or missing required CI jobs |
| [deploy_huggingface.py](deploy_huggingface.py) | Fast-forward-only publication of canonical source to HF |
| [verify_deployment.py](verify_deployment.py) | Check revision, protected content, readiness, public APIs and mutation denial |
| [start.sh](start.sh) | Docker entrypoint, embedded PostgreSQL startup and recovery orchestration |
| [postgres_recovery.py](postgres_recovery.py) | Package/restore a checked base-backup and WAL bundle |
| [restore_status_server.py](restore_status_server.py) | Temporary startup/restore status server |
| [hf_sync_decision.py](hf_sync_decision.py) | Retained compatibility classifier for the old HF-to-GitHub sync; no automatic import workflow remains |

Recovery and deployment can affect persistent evidence. Use the [operations guide](../docs/operations/deployment.md), preserve backups and verify readiness before declaring recovery complete. The public observatory does not invoke these administrative operations.
