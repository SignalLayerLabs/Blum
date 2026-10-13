# BLUM Governance

BLUM is developed in public under the Apache-2.0 license. The canonical source
repository is `SignalLayerLabs/Blum`; Hugging Face hosts the public deployment,
model artifacts and governed datasets.

## Decision principles

- Evidence outranks confidence.
- Point-in-time correctness outranks backtest appearance.
- Capital preservation outranks forced activity.
- Stored, reproducible outcomes outrank marketing metrics.
- Financial intelligence belongs in the Engine; presentation belongs in the
  Runtime; model artifacts assist reasoning but are not market truth.

## Change control

Maintainers review changes for correctness, licensing, data provenance,
look-ahead bias, reproducibility, security and backward compatibility. Risky
weight or rule changes require explicit evidence and reversible activation.
Source code is never modified autonomously by BLUM.

## Community evidence

External usage does not silently transmit data. Contributions are opt-in,
redacted, versioned and quarantined before they can enter a future training
snapshot. A submitted example never changes the active model directly.
