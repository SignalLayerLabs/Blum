# Implementation plan

1. Repair executable factory contracts, virtual-clock daily bar leakage and gap stop prices with regression tests.
2. Add a deterministic curriculum kernel: closed-bar adapter, versioned expert catalogue, cost-aware account, contextual predictor, fixed partitions and reproducible random training blocks. Observe failing tests before implementation.
3. Persist source packs, checkpoints and separate historical/prospective episodes; add bounded worker, stored public read and protected manual run.
4. Expose curriculum progress in Research. Run a pinned local real-data experiment and publish the actual receipt, including failure/abstention results.
5. Verify full backend/frontend/build/migration checks, independent code review, push a concrete PR. Preserve the original requirement for explicit merge approval.
