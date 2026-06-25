# Anonymous Synthesis - Pre-Test Question Round

Date: 2026-06-25
Status: Agreement reached; implementation slice completed in corpus repo

## Questions Asked

At least four new questions were asked before answer work began:

1. `Unrealized question.md` - what similar tools/apps can we learn from?
2. `Anonymous question - semantic text verification.md` - how do we automatically prove text modes create the right host entity types?
3. `Anonymous question - source provenance and audit trail.md` - how do imported objects trace back to PDF source content and decisions?
4. `Anonymous question - first launch installer self test.md` - how do packages prove readiness on a clean/offline/low-permission PC?
5. `Anonymous question - failed import recovery contract.md` - how do imports roll back or quarantine partial work after cancel/crash/timeout/OOM?

## Answers Posted

Every active reviewer answered questions they did not ask:

- `Anonymous answers - reviewer source provenance lane.md`
- `Anonymous answers - reviewer recovery-skip 2026-06-25.md`
- `Anonymous answers - recovery semantics provenance comparison.md`

## Agreement

The reviewers agree on the following:

- Visual screenshots are not enough. Semantic proof must inspect parent-software object types or output entities.
- Every package should expose a Ready Check / Health Check before real project files are imported.
- Every import should have a recoverable session model: transaction first, quarantine if rollback is unsafe, diagnostics always preserved.
- Provenance should use compact IDs on host objects plus a complete sidecar manifest rather than bloating every object with large JSON.
- Similar tools teach useful patterns: page ranges, category choices, batch conversion, font mapping, scale calibration, markup/takeoff reports, support bundles, and parser test corpora.
- Website claims must distinguish source-test green, packaged-artifact green, oldest-host launch green, and human field confirmation green.

## Resolved Disagreement

One answer proposed a "fastest / balanced / maximum fidelity" style control. That conflicts with `BCS-ARCH-001` if treated as a hidden quality tier.

Resolution: safe operational guards are allowed; silent fidelity downgrade is not. A "safe mode" may chunk pages, stage output, warn about memory/entity counts, or defer expensive cleanup. It must not silently choose worse geometry. Any fidelity-impacting fallback must be explicit in the UI/report.

## Implementation Completed

Implemented shared evidence contracts in:

```text
C:\1pdf-test-corpus
```

New files:

- `PRETEST_ACCEPTANCE_CONTRACTS.md`
- `schemas/ready_check.schema.json`
- `schemas/text_entity_verification.schema.json`
- `schemas/source_provenance.schema.json`
- `schemas/import_recovery.schema.json`
- `tools/validate_contract_schemas.py`

Updated:

- `README.md`

Validation command:

```powershell
python tools\validate_contract_schemas.py
```

## Next Engineering Slice

The next implementation pass should wire these contracts into host code in this order:

1. `actual_text_entity_types` in import reports.
2. Ready Check output from existing preflight/compatibility tools.
3. Import recovery status for failure/cancel paths.
4. Source provenance sidecar for selected object diagnostics.
5. Website Report Doctor support for the new schema files.

## Current Decision

Agreement is reached for this round. The corpus repo now contains the shared contract artifacts needed before user testing. Remaining host implementation work is scoped and no longer ambiguous.
