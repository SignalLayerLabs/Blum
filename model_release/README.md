# BLUM Finance model tooling

This component packages advisory-model inference, contribution handling, sanitization, training and evaluation. It does not own market truth or establish trading alpha. Runtime application version and package version are separate.

**Current source policy:** existing reasoning archives are quarantined for new training and promotion. Paid training, automatic launch and automatic dataset publication remain disabled pending a validated replacement dataset. The presence of a script or earlier model artifact is not permission to bypass those gates.

| Path | Responsibility |
| --- | --- |
| [blum_finance](blum_finance) | Inference schemas, local memory and opt-in contribution tools |
| [training](training) | Training configuration, source sanitization and job code |
| [evaluation](evaluation) | Candidate, base-model and task evaluation |
| [release](release) | Artifact construction, conversion and publication tooling |
| [model_card](model_card) and [dataset_card](dataset_card) | Templated release metadata |
| [contribution_repo](contribution_repo) | Quarantine contribution-repository documentation |
| [tests](tests) | Package contracts |
| [pyproject.toml](pyproject.toml) | Install metadata and optional dependency groups |

From the repository root, install the extras needed for the work, for example:

```bash
python -m pip install -e './model_release[test,release]'
PYTHONPATH=model_release python -m pytest -q model_release/tests
```

Inference and hardware-specific evaluations require their matching extras and compatible hardware. Test fixtures do not establish provider reliability or model performance on future outcomes.

Read [data acceptance](../docs/research/data-quality.md), [gated HF operations](../docs/operations/huggingface-training.md), and the package [contribution contract](CONTRIBUTING.md). Earlier results remain in the [model release report](../docs/reports/blum-finance-model-release-report.md) and [benchmark report](../docs/reports/public-benchmark-report.md), explicitly as historical records.
