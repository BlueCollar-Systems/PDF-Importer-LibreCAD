# Round 5 — Reviewer N Questions (2026-07-03)

**Author:** Anonymous Reviewer N
**Rules:** Questions only — no self-answers; respond in a peer answer doc per `Instructions 0607202613216.txt`. (Reviewer N's ≥3 cross-answer quota was met in Rounds 3–4: J5, J6, K1–K5, M1.)
**Theme (owner-directed):** *What haven't we thought of? What can be added or improved? How do we make this more powerful?* Plus one required outside-the-box question. Owner has specifically requested evaluation of **QR/barcode tag scanning (e.g., galvanizing-rated part tags)** for automating fabricated-part tracking.

---

## Q-N6 — Barcode/QR part tracking: scan-to-lookup first, or full lifecycle? (owner-requested)

**Context (verified on disk):** Steel Logic already has inventory (`inventory_screen.dart`, SQLite via `database_helper.dart`), a time clock suite, and PDF Callout Lookup. The importers emit `import_report.json` with `text_spans` + `generic_tags` (piece marks and BOM rows are extractable). Nothing in the ecosystem reads a physical tag today.

Fab shops that galvanize use metal barcode tags that survive the zinc bath (e.g., galvanizing-rated part tags). If every fabricated part gets one, the app camera becomes the bridge between the physical part and its digital record.

**Question:** For the first shipped slice, should scanning be **(a) scan-to-lookup** (scan → open/create a part record: piece mark, project, heat number, status) or **(b) full lifecycle tracking** (statuses fit-up → welded → inspected → shipped → galvanized → returned, with timestamps and operator)? Specifically:
1. Which symbologies must v1 read — Code 128 / Code 39 (typical metal tags), DataMatrix, QR — and do we standardize our *own* printed tags on QR with a URL payload so any phone camera (no app) can also resolve it?
2. Data model: does a scanned tag key into the existing inventory table, a new `parts` table, or both (inventory = stock, parts = fabricated assemblies)?
3. Offline-first is non-negotiable on shop floors — scan queue with later sync, same pattern as `inventory_sync.dart` / `time_clock_sync.dart`?
4. Which scanner dependency fits the mission (bundled, offline, oldest-hardware-friendly): `mobile_scanner` (MLKit-based), ZXing port, or platform camera intents — and what is the fallback for devices without a camera (manual tag-ID entry field in the same omni-box)?

---

## Q-N7 — The digital thread: piece marks from PDF → app parts → tag scans → reports

**Context:** The importers already extract BOM tables and piece-mark text from shop drawings; the app tracks inventory and time; the website renders reports. But nothing connects them: a part's identity is re-typed at every step today.

**Question:** Should we define one shared `bcs.part/1.0` record (piece mark, project, drawing ref = `source_pdf.sha256` + page, heat number, tag ID, status history) so that: importers export a parts list from a drawing's BOM → Steel Logic imports it and prints/assigns tags → scans update status → time entries auto-link when the task text contains a known piece mark (the omni time parser already extracts tags like `45x90`)? What's the minimum viable schema and which repo owns it (corpus, like the other contract schemas)?

---

## Q-N8 — What haven't we thought of: capture at the point of work

**Context:** Everything we've built assumes typed input. Shop reality: gloves, grinder dust, two ladders up.

**Question:** Which zero-typing capture channels are worth a slice, ranked by value-to-effort:
1. **Voice** — push-to-talk into the omni-box ("log two and a quarter hours welding B-14"), offline speech-to-text?
2. **Photo OCR of mill test reports (MTRs)** — camera → heat number + grade auto-filled into inventory, linking traceability docs to parts?
3. **Photo-as-record** — attach a photo to any part/time entry (fit-up evidence, weld visual), stored locally, hash-referenced?
4. **Count-by-camera** — point at a bundle of identical parts, count them (even a manual tally-tap counter beats a clipboard)?
Which existing screen hosts each (omni-box is the obvious front door), and which are explicitly out of scope for a local-first app?

---

## Q-N9 — Making the calculators more powerful without more surface

**Context:** The omni calculator engine is landing (see `QA-2026-07-03_app-omni-coordination.md` — precision contract pinned). The instructions demand power under a simple surface.

**Question:** Which domain packs should ship behind the same single input box, and in what order:
1. **Fab formulas** — bend allowance/deduction, arc length, bolt circle coordinates, stair stringer rise/run (some exist as separate screens today — should they become omni-box phrases like "bolt circle 8 holes on 12 in"?),
2. **Weight/CG** — "weight of W12x26 x 30 ft" straight from the AISC database the app already ships,
3. **Vent/drain hole sizing for galvanizing** (the instructions' own example: "vent hole size for 45ft pipe") — which published galvanizer guideline do we encode, and do we cite it inline in the result?
4. **Grade-aware capacity lookups** — or is anything that smells like engineering design out of bounds per the app's "reference only, verify with an engineer" disclaimer?
Where is the line between "calculator" and "liability"?

---

## Q-N10 — OUTSIDE THE BOX (required): the tag IS the URL — parts that identify themselves to any phone, no app installed

**Premise:** We control a website with CI/CD and dynamic metadata. QR tags can encode URLs. An inspector, galvanizer, erector, or GC does **not** have Steel Logic installed — but every one of them has a camera app.

**Question:** Should our printed QR tags encode `https://bluecollar-systems.com/p/<opaque-id>` so that *any* phone scanning a part opens a lightweight public page showing exactly what the owner chooses to publish for that part — piece mark, project, drawing thumbnail, galv date, inspection status, "report a problem" button — while the *same* scan inside Steel Logic opens the full editable record? Sub-questions:
1. Privacy/tenancy: opaque IDs + owner-controlled publish toggle per project (default private → page shows only "contact fabricator")?
2. Hosting: static JSON per part pushed to the site (fits the current static Cloudflare Pages model) vs. a worker/KV lookup?
3. This makes the website a **product surface for people who never visit it** — does that change what the website team prioritizes (uptime, page weight on cell connections, printable tag sheets)?
4. Failure mode: what does the page show for a scanned tag whose part was never published — and can it *sell* the toolkit there ("this tag was made with Steel Logic") without being obnoxious?

---

## Q-N11 — What can we learn from every import (opt-in telemetry as a corpus engine)

**Context:** Our corpus grows by hand. Meanwhile every real-world import that fails or falls back is exactly the PDF class we need — and we never hear about it.

**Question:** Should importers offer a strictly **opt-in, local-first "share this report" action** (never the PDF itself — only the `import_report.json`, already anonymized: counts, modes, fallback reasons, no drawing content) that posts to a website endpoint feeding a "failure class" dashboard — so corpus acquisition targets what actually breaks in the field instead of what we guess? What are the hard privacy lines (no filenames, no text spans, no geometry), and does the report schema need a `redaction_level` field first?

---

*End of Round 5 Reviewer N questions — 6 questions (Q-N6 owner-requested scanner, Q-N10 outside-the-box). Awaiting cross-answers from other reviewers; do not answer your own.*
