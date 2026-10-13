# Contributing to BLUM

BLUM welcomes reproducible contributions that improve evidence quality,
decision quality, risk control, learning reliability or runtime performance.

## Before opening a change

1. Search existing issues and discussions.
2. Describe the observed problem and the evidence that it exists.
3. Keep financial logic separate from runtime and presentation concerns.
4. Never add fabricated market data, guaranteed-return claims or hidden
   self-modification.
5. Keep GET endpoints read-only and page rendering snapshot-first.

## Development workflow

1. Fork `SignalLayerLabs/Blum` and create a focused branch.
2. Add or update tests before changing behavior.
3. Run the smallest relevant test set, then the full affected suite.
4. Document data lineage, point-in-time constraints and benchmark methodology.
5. Open a pull request with before/after evidence and known limitations.

Useful commands:

```bash
python3 -m pytest -q
pnpm --dir frontend test
pnpm --dir frontend build
```

## Data and model contributions

Do not commit credentials, personal information, proprietary datasets or data
whose redistribution terms are unclear. Training examples must preserve
point-in-time evidence, source provenance and licensing metadata. Community
memory is quarantined and reviewed; it never changes production weights merely
because it was uploaded.

## Financial safety

BLUM is research and paper-trading software. Contributions must not introduce
real-money execution, guaranteed-profit language or benchmark claims without
stored evidence and sufficient samples.

By submitting a contribution, you agree that it is licensed under Apache-2.0.
