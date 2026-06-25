# QA-2026-06-25 - Reviewer A Agreement: SketchUp/Public Corpus

## Verdict

**GO for the SketchUp/public-corpus commit/push lane.**

The SketchUp/public-corpus content is QA-acceptable based on the evidence below. After transient concurrent repo movement during this review, final verification shows local `main` clean and synchronized with `origin/main`.

This is not a blanket all-product release sign-off. The broader human field screenshot retest remains open under T-01 / WS-FIELD.

## Evidence Reviewed

- Read the coordination hub, open threads, and worker status log:
  - `QA-2026-06-24_COORDINATION-HUB.md`
  - `QA-2026-06-24_open-threads.md`
  - `QA-2026-06-24_worker-status-log.md`
- Read Round 6 corpus/app notes:
  - `QA-2026-06-24_round6-corpus-and-features.md`
  - `QA-2026-06-24_round6-codex-implementation-note.md`
  - `QA-2026-06-24_round6-importer-test-findings.md`
  - `QA-2026-06-24_round6-public-corpus-coordination-addendum.md`
  - `QA-2026-06-24_round6-app-shape-lookup-implementation.md`
- Coordination state says WS-R6 is implemented and validated: public corpus gate `25 OK + 1 expected refusal`.
- Open threads show no unresolved P0 specific to the SketchUp public-corpus gate. The remaining P0 is human field screenshot sign-off.
- Public-corpus addendum records:
  - 26 PDFs scanned.
  - 25 OK.
  - 1 expected refusal for `encryption_openpassword.pdf`.
  - 0 unexpected failures.
  - 0 timeouts.
  - Large public construction PDFs produced complete simulated label placement counts where text existed.
- Repo status final verification:
  - `git status --porcelain=v1 -b` -> `## main...origin/main`
  - `HEAD` short SHA: `2a45fb0`
  - `origin/main` short SHA: `2a45fb0`
  - `main...origin/main` cherry-pick comparison empty.
  - `git diff --stat` empty.
- Relevant committed scope is present:
  - `tools/public_pdf_corpus_manifest.json`
  - `tools/download_public_pdf_corpus.py`
  - `corpus_paths.rb`
  - `test/CORPUS_CI.md`
  - `test/support/corpus_harness.rb`
  - `test/corpus_placement_test.rb`
  - `tools/generate_corpus_baselines.rb`
  - committed corpus baseline JSON files.
- Lightweight read-only checks passed:
  - `ruby -c test/support/corpus_harness.rb` -> `Syntax OK`
  - `ruby -c test/corpus_placement_test.rb` -> `Syntax OK`
  - `ruby -c tools/generate_corpus_baselines.rb` -> `Syntax OK`
- Read-only search confirmed expected-refusal handling exists in the committed SketchUp harness:
  - `test/support/corpus_harness.rb` maps `encryption_openpassword.pdf` to encrypted/password-protected refusal.
  - `test/corpus_placement_test.rb` and `tools/generate_corpus_baselines.rb` call `CorpusHarness.expected_refusal?`.

## Remaining Non-Blockers

- T-01 / WS-FIELD human screenshot sign-off remains required before a broader release claim.
- Large public construction PDFs are useful for local/human confidence but may be too slow for default CI; tiering remains a policy choice, not a commit blocker.
- The full Steel Logic PDF-BOM/takeoff bridge remains open. The Round 6 app slice currently shipped is PDF Callout Lookup, which is correctly scoped as the first bridge.
- FreeCAD/LibreCAD/Blender comparable public-corpus baseline policy is still a cross-host follow-up. That does not block the SketchUp public-corpus lane.

## Commit/Push Scope

No new SketchUp commit or push is pending from my review. The current local repo is already synchronized with `origin/main` at `2a45fb0`.

The reviewed pushed scope is:

- `2a37d33` - test corpus manifest integration and golden oracle harness.
- `42bfe1c` - public-corpus/golden-oracle follow-up plus QA coordination mirror updates.
- `a86ce77` - `v3.7.65` version bump.
- `ee6d3c5` - commit-readiness Q&A mirror.
- `2a45fb0` - four-reviewer agreement Q&A, current `HEAD` / `origin/main`.

Do not include this Desktop QA agreement file in a SketchUp source commit.
