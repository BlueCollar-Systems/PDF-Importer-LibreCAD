# Outside-the-Box Review - Reviewer A - SketchUp Importer

Date: 2026-06-24
Scope: `C:\1PDF-Importer-SketchUp` plus Desktop Q&A context in `C:\Users\Rowdy Payton\Desktop\PDFTest Files\Q&A`
Role: Reviewer A, SketchUp/product-engineering lens
Constraint: No source code edited. Report only.

## Short Verdict

The SketchUp importer has gone well beyond "make the test files work" in several areas: it has a real Auto/Vector/Raster/Hybrid model, bundled Poppler helpers, text-mode routing, OCG-to-Tag support, scale detection, open-gate diagnostics, headless corpus infrastructure, and now an Import Health direction. That is a serious product foundation.

But I do not think it has gone far enough yet on proof, trust, and workflow closure. The biggest remaining gap is not a single parser bug. It is that accuracy claims are still too dependent on stable regression hashes, selected field PDFs, and human interpretation. The next leap should be: make scale, text fidelity, layer fidelity, and fallback reasons visibly trustworthy to a non-technical SketchUp user before they build production work from an import.

## Observations

1. The importer is architecturally ambitious and mostly pointed the right way.
   The pipeline now includes built-in Ruby parsing, Poppler/MuPDF assisted text/raster/SVG paths, XObject expansion, OCG layer mapping, page rotation handling, scale detection, cleanup, JSON reporting, and post-import UI. This is not a toy extension.

2. BCS-ARCH-001 is doing useful product discipline.
   The old quality-preset sprawl is mostly gone from user-facing mode selection. Auto/Vector/Raster/Hybrid is the right mental model, and text rendering being orthogonal is the right call.

3. Text has received real engineering attention.
   Recent tests cover the 1017 field pain: label/3D Text placement, vertical quantities, leaders, section labels, and mode routing. I ran:
   - `ruby test\import_dialog_defaults_test.rb` - 22 runs, 108 assertions, pass
   - `ruby test\qa_report_test.rb` - 5 runs, 37 assertions, pass on current worktree
   - `ruby test\layer_manager_test.rb` - 5 runs, 11 assertions, pass
   - `ruby test\text_mode_routing_test.rb` - 10 runs, 85 assertions, pass
   - `ruby test\text_mode_placement_test.rb` - 51 assertions, pass
   - `ruby test\text_label_placement_test.rb` - 122 assertions, pass
   - `ruby test\smoke_test.rb` - 59 checks, pass

4. Diagnostics are getting much closer to support-ready.
   The current worktree adds `import_health.rb`, a menu item, richer diagnostics, and `extra.human_summary`. That is exactly the right product direction. Users should not need to hunt in `%TEMP%` or paste Ruby Console logs to answer "what happened?"

5. Packaging is better than normal for SketchUp extensions.
   `build_release.py` fails release builds when bundled Poppler helpers are missing. That is high leverage because it prevents "works on the developer PC" releases.

6. There is a live documentation/behavior mismatch on first-run text mode.
   `README.md` says first-run fallback is Geometry, and an inline comment says Geometry on first run. The code and tests use `FIRST_RUN_TEXT_MODE = '3D Text'`. This is not just cosmetic: it affects what a new user sees and what support should recommend.

7. Corpus CI exists, but the feedback loop is still heavy.
   `corpus-placement.yml` validates baseline JSON in GitHub-hosted CI but skips the full corpus unless `BCS_CORPUS_ROOT` is available. My local `ruby test\corpus_placement_test.rb` run exceeded a four-minute command timeout. That is useful signal: the lane exists, but it is not yet a fast everyday review gate.

8. Some legacy language remains internally.
   `DocumentProfiler.suggest_mode` still returns `:technical`, and `:raster_only` remains as a profile type. This may be harmless if it is purely domain classification, but the vocabulary is close enough to the removed preset system that it deserves a cleanup or explicit comment saying "profile label, not import mode."

## Risks And Limitations

1. Scale trust is still not strong enough for production confidence.
   `resolved_scale` is present, but the product should assume scale is the silent killer. A title block guess should be cross-checked against measured dimensions when possible. If the importer can say "scale confidence 82%" but not "a 24'-0" dimension agrees within 1.5%," the user still has to trust magic.

2. Import reports still lack enough phase timing.
   `qa_report.rb` currently records `performance.phases.total_ms`; it does not split parse, content streams, XObject expansion, external text extraction, SVG glyph render, raster render, geometry build, cleanup, and report write. Without phase timing, "this PDF is slow" remains hard to triage.

3. Fallbacks are accurate but not always user-actionable.
   The code can rasterize fill-art floods, text-dominant pages, and no-stream pages. The report should make these decisions explicit per page: "Page 2 rasterized because it has 0 vector paths and 420 text spans" or "Page 4 used labels because Poppler/MuPDF was unavailable."

4. Geometry fidelity proof is still stability-biased, not oracle-biased.
   Baselines prove "did not change," which is valuable. They do not prove "matches the PDF." Add a tiny set of golden vector oracles with human-reviewed primitive ranges, scale expectations, and layer/text expectations.

5. Layer fidelity is under-proven for mixed text paths.
   Vector paths map through OCG layers well. Native Labels can preserve per-span layers when routed through internal parsing. Geometry/Glyphs appear to use a text fallback layer rather than per-span OCG. That may be a deliberate host limitation, but it should be visible in docs and reports.

6. "Any PC" still needs clean-machine proof, not only bundled files.
   The RBZ includes Poppler helper files, but the release process should publish a helper manifest: filenames, versions, checksums, license notices, and a clean Windows SketchUp 2017/2024/2025 install smoke result. Old PCs fail in boring ways.

7. Open gate intentionally fails open if the gate itself errors.
   That is documented, but support needs to know it means malformed edge cases can still reach the parser. Keep the policy if needed for compatibility, but make report reasons obvious when the parser later fails.

8. The current worktree changed while this review was running.
   The repo was clean at start. Later, uncommitted changes appeared in `main.rb`, `metadata.rb`, `qa_report.rb`, `test/qa_report_test.rb`, plus new `import_health.rb`. I treated them as current context and did not modify or revert them.

## Questions Asked And Answered

1. Have we gone far enough on accuracy?
   Not yet. We have better extraction and placement tests, but need scale cross-checks, golden vector oracles, and per-page fallback explanations before "accuracy" feels production-grade.

2. Have we gone far enough on performance?
   Not yet. There are smart heuristics and glyph component budgets, but not enough phase timing, cancellation, sharding, or low-spec PC benchmarks.

3. Have we gone far enough on text fidelity?
   We have gone far for 1017-style fabrication text. We have not gone far enough on font-span quality scoring, Unicode/font failure summaries, and clear "editable vs exact outline" expectations.

4. Have we gone far enough on layer fidelity?
   Mostly for vector OCG-to-Tags. Not enough for text-mode-specific layer behavior and post-import remapping to existing SketchUp Tags.

5. Have we gone far enough on UX?
   The direction is right with Import Health and human summaries. The next UX gap is preflight: tell users what they will get before a long import.

6. Have we gone far enough on install reliability?
   Better than average because Poppler is bundled and checked at build time. Still needs a clean-machine release manifest and first-run "all helpers working" proof.

7. Have we gone far enough on diagnostics?
   The new diagnostics are a big step, but phase timings and per-page decision reasons are still missing.

8. Have we gone far enough on real-world workflows?
   Not quite. Detailers need scale trust, layer mapping into existing Tag structures, revision re-import/diff, and "import only this page/detail" workflows.

## Bold Ideas

1. Scale cross-check banner.
   Compare detected title-block scale against one or more dimension strings and a measured vector span. Show a non-blocking banner: "Title block says 48x; dimension 24'-0" implies 47.7x; use title block, measured dimension, or manual reference." Short safe step: add report-only `extra.scale_cross_checks`.

2. Golden vector oracle set.
   Pick 3 to 5 PDFs and record reviewed expectations: page count, scale, layer names, primitive count range, text count range, expected raster fallback yes/no, and key anchor coordinates. This complements baseline stability.

3. Per-page decision ledger.
   Add `extra.pages[]` with `mode_resolved`, `reason`, `paths`, `text_items`, `images`, `fallback`, and `warnings`. This would make Auto mode trustworthy and supportable.

4. Import preflight summary.
   Before import, show: helpers found, text mode consequences, layer behavior, page count, estimated heavy/dense text warning, and "expected output." Keep it plain: editable labels vs exact outlines.

5. Import Health 2.0 with "Copy Support Summary."
   The current Import Health idea is excellent. Add a clipboard-safe one-click summary containing human_summary, report path, log path, helper status, SketchUp version, importer version, and fallback reason.

6. Layer remap after import.
   Add a dry-run tool that maps imported PDF Tags to existing model Tags by exact/fuzzy match. Example: `A-WALL`, `A Wall`, and `A_Wall` collapse to the user's existing `A-Wall` Tag after confirmation.

7. Revision-aware re-import.
   Start small: if the same PDF SHA or same filename was imported before, show previous report metrics and ask whether to replace, overlay, or import only selected pages. Stable primitive IDs can be a moonshot later.

8. Low-spec PC performance lane.
   Maintain one "shop PC budget" target: SketchUp 2017, 8 GB RAM, no admin rights, cold install. Publish a small timed matrix for Tier-1 PDFs.

9. Extraction replay bundle.
   Zip `import_report.json`, compatibility report, log excerpt, helper manifest, and content stream hashes. Avoid customer PDF redistribution while preserving enough facts for triage.

10. Confidence overlay, not live preview yet.
   A full live preview is exciting but risky. Safer first version: after import, create an optional temporary overlay/color tag for warnings: rasterized page, low text confidence, unresolved scale, layer overflow.

## Safe Immediate Improvements

1. Resolve the first-run text-mode contradiction.
   Decide whether first-run default is Geometry or 3D Text, then align README, `HOST_COMPATIBILITY.md`, inline comments, tests, and Import Health wording.

2. Add phase timings to `import_report.json`.
   Start with coarse timings only: parse, paths, text, xobjects, geometry_build, svg_text, raster, cleanup, report_write. No UI redesign required.

3. Add per-page Auto/fallback reason fields.
   The code already makes decisions for fill-art flood, no streams, text-dominant pages, and empty vector content. Capture those reasons structurally.

4. Add a clean-machine release checklist.
   For every RBZ release: SketchUp 2017 syntax/smoke, current SketchUp install, bundled helper scan, Import Health screenshot, Compatibility Report saved, one Tier-1 import.

5. Add helper manifest/checksum output.
   Build can already require helper files. Extend it to emit helper filenames, sizes, hashes, and detected license notice files.

6. Make corpus CI tiered.
   Split into Tier 0 quick smoke, Tier 1 representative PDFs under 60 seconds, Tier 2 full corpus, Tier 3 stress/manual. The full corpus should not be the only meaningful fidelity lane.

7. Add report tests for the new Import Health fields.
   `qa_report_test.rb` now covers human_summary and diagnostics. Add a small unit test around `ImportHealth.record!`/`snapshot` without SketchUp UI.

8. Document text-mode layer behavior.
   Make explicit: Labels can preserve editable text, Geometry/Glyphs prioritize visual fidelity, and per-span OCG may not be available for every text route.

9. Add "support-safe path" language.
   Compatibility Report says paths are included. Add a "Copy redacted summary" option later if customer machines have sensitive usernames/project paths.

10. Track corpus command progress in CI logs and local logs.
   My full corpus run timed out without useful partial output in the tool result. Make each PDF flush and optionally write a partial JSON summary after every file.

## What Not To Do

1. Do not reintroduce quality presets or "quick mode."
   BCS-ARCH-001 is right. Performance should come from better algorithms, page strategy, caching, and progressive UX, not a user-facing lower-quality mode.

2. Do not silently rasterize pages without a page-level reason.
   Raster fallback is often correct, but silent fallback destroys user trust when they expected editable geometry.

3. Do not claim SketchUp text parity that the host cannot provide.
   Labels, 3D Text, Glyphs, and Geometry are different products for different workflows. Sell the trade-off honestly.

4. Do not overfit 1017.
   Keep 1017 as a Tier-1 canary, but add diverse oracles: architectural, map/GIS, OCR, vector art, scanned raster, CAD with OCGs, and font-hostile PDFs.

5. Do not host or redistribute SketchUp installers.
   The 2017 policy is correct. Support legacy users with compatibility docs and RBZ installs only.

6. Do not make live preview the next mandatory gate.
   Preview is attractive, but without oracles and timing budget it can become a second slow import. Build report/scale/oracle trust first.

7. Do not bury diagnostics only in JSON.
   JSON is the spine, but SketchUp users need the summary in Import Health and post-import UI.

8. Do not let bundled third-party binaries become invisible supply-chain debt.
   Keep notices, checksums, source URLs, and version provenance visible in every release.

9. Do not collapse every PDF layer into a single text layer without telling the user.
   If a text route cannot preserve layers, report it as a mode limitation.

10. Do not treat "tests pass" as "field-ready."
   The field workflow includes install, first import, wrong mode recovery, scale correction, tag cleanup, support summary, and uninstall/update. Test those as a journey.

## Priority Recommendation

My next sprint order for SketchUp:

1. Fix text default documentation/code alignment.
2. Add phase timings and per-page decision ledger to `import_report.json`.
3. Add scale cross-check diagnostics, report-only first.
4. Add Tier-1 golden vector oracle tests.
5. Extend Import Health with copyable support summary and helper status.

That sequence turns the importer from "powerful and improving" into "trustworthy under pressure," which is what a SketchUp shop-floor user actually needs.
