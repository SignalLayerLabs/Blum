# Source audit ledgers

[Documentation](../README.md) · [Data acceptance and limitations](../research/data-quality.md)

These machine-readable records support the historical-source audit carried forward from release 2.2. They are preserved inputs to review, not a live database export or a blanket certification of semantic validity. Quarantined reasoning archives remain excluded from new training/promotion.

| Ledger | Contents |
| --- | --- |
| [huggingface-source-audit.json](huggingface-source-audit.json) | Source discovery, reviewed revisions, acceptance decisions and audit limitations |
| [historical-rejected-rows.json](historical-rejected-rows.json) | Invalid packaged price bars excluded by policy |
| [historical-missing-volume-flags.json](historical-missing-volume-flags.json) | Accepted price observations whose volume remains missing |
| [forex-accepted-weekday-groups.json](forex-accepted-weekday-groups.json) | Non-ambiguous weekday snapshot groups accepted for the declared limited use |
| [forex-conflicting-keys.json](forex-conflicting-keys.json) | Conflicting Forex observations excluded from use |
| [bucket-snapshots-audit.json](bucket-snapshots-audit.json) | Archive hashes, lineage duplication, split/cutoff findings and policy |
| [bucket-novel-lineages.json](bucket-novel-lineages.json) | Additional lineages discovered in persistent archives |
| [snapshot-boundary-crossing-outcomes.json](snapshot-boundary-crossing-outcomes.json) | Outcome occurrences crossing declared snapshot boundaries |
| [snapshot-late-outcomes.json](snapshot-late-outcomes.json) | Late-outcome findings retained for inspection |

Reproduce the packaged-file policy check from the repository root:

```bash
PYTHONPATH=backend python scripts/audit_historical_sources.py --check
```

Provider, dataset and model terms remain separate from the application license. Preserve these ledgers rather than editing their counts to match presentation copy. An accepted historical observation is not a prospectively registered call.
