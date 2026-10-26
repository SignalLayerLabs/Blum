# Independent review — 26 October 2026

Status: NOT READY TO MERGE. The initial implementation is retained in a draft PR while the following confirmed findings are corrected with regression tests.

Important findings:
1. Order retries regenerate decision clocks before idempotency comparison; strategy recovery has the same risk.
2. Manual paper orders are not visited by the subscription-only cycle.
3. Symbol-only position/source identity can merge incompatible currency contracts.
4. New-risk settlement does not recheck account halt, loss stops and stale marks completely.
5. Several orders can each consume the full capacity of one observation.
6. Ordinary partially filled stops do not retain activation.
7. Paper stepping omits configured financing that replay applies.
8. Caller-supplied future provenance can admit future observations; availability ordering needs validation.
9. Provenance-only changes can bypass consumed confirmation protection.
10. Stored family trial counts and multiplicity intervals become stale after more alternatives are registered.

Additional findings: charts should expose missing valuation segments; the web dependency lockfile is not yet present; PostgreSQL concurrency checks must use independent repositories rather than one process-local lock.

Live broker integration, paid data acquisition, production cutover and native execution parity remain outside this PR's scope. Quote-qualified performance remains unavailable. The branch has not been approved for merge or deployment.
