# Security Policy

## Supported version

Security fixes target the current `main` branch. Historical revisions may not
receive backports.

## Reporting a vulnerability

Do not disclose exploitable vulnerabilities in a public issue. Use GitHub's
private vulnerability reporting for `SignalLayerLabs/Blum` when available.
Include affected revisions, reproduction steps, impact and a proposed remedy if
known. Never include live credentials, broker secrets or personal financial
data in a report.

## Scope

High-priority reports include credential exposure, unauthorized database
access, unsafe model or dataset ingestion, server-side request forgery,
dependency compromise and any path that could turn paper-only behavior into
real execution.

BLUM does not request brokerage credentials and does not execute real-money
orders. A deployment that adds those capabilities is outside the supported
security boundary.
