# Anonymous Project Briefing — BlueCollar PDF Importer Ecosystem (for third-party reviewers)

**Document ID:** QA-2026-06-24_third-party-project-briefing  
**Audience:** New anonymous third-party reviewers, auditors, and human field testers  
**Classification:** Anonymous — no author attribution  
**Last updated:** 2026-06-25  
**Status:** Authoritative onboarding document — read before any other QA file

---

## Executive summary

BlueCollar Systems builds **PDF vector importers** for fabrication-shop CAD workflows: SketchUp, FreeCAD, LibreCAD (2D), and Blender, plus a **Steel Logic** mobile/desktop app and a **BlueCollar website** for downloads, install help, and import-report diagnosis. The engineering ambition is **100% visual and scalable accuracy** within honest host-software limits — not pixel-perfect clones across hosts, and not claims beyond what each CAD platform can represent.

The project treats **real-world fab-shop PDFs** as the validation target, not synthetic hack targets. A private **test corpus** (`C:\1pdf-test-corpus`) and Desktop Q&A folder coordinate anonymous multi-reviewer QA. As of this session, **automated gates are green**, **four anonymous reviewers agreed GO to commit/push** documentation mirrors, and **deploy artifacts are published** on GitHub Releases — but **field human confirmation has not been completed** by the product owner. That gap is the primary remaining blocker for release sign-off.

---

## 1. Mission and goals

### 1.1 Accuracy ambition

The project targets output that is **indistinguishable from the source PDF within host limits**, while remaining editable where the user selects editable text modes. This is an honest ambition:

- **Visual fidelity:** geometry, dimensions, symbols, and text placement should match the PDF at drawing scale.
- **Scalable fidelity:** imported geometry must respect detected or user-specified drawing scale; scale cross-check warnings surface disagreements.
- **Host limits acknowledged:** SketchUp cannot be LibreCAD; Blender is mesh-centric; LibreCAD is 2D-only. The importers document these boundaries rather than hiding them.

The project **does not** claim 100% on every PDF class (encrypted, corrupt, purely scanned without OCR, exotic font encodings). It **does** claim honest handling: clear errors, `import_report.json` diagnostics, and `human_summary` plain-English explanations.

### 1.2 Four text modes (BCS-ARCH-001)

**BCS-ARCH-001** (`_LLM_CONTROL_PACK/BCS-ARCH-001.md`) is the authoritative architectural decision. It replaced a deprecated seven-preset quality-tier system with:

**Import modes (content strategy):**

| Mode | Purpose |
|------|---------|
| **Auto** | Default — analyze PDF; choose Vector, Raster, or Hybrid |
| **Vector** | Clean vector PDFs — full vector extraction |
| **Raster** | Scanned/image-only — high-DPI placement |
| **Hybrid** | Mixed — vectors where clean; raster where lossy |

**Text modes (orthogonal user preference):**

| Mode | SketchUp | FreeCAD | LibreCAD | Blender |
|------|----------|---------|----------|---------|
| **Labels** | Editable labels | ShapeString (editable) | DXF TEXT | Text object |
| **Glyphs** | Glyph outline geometry | Vector outlines | Outlines (CLI) | Text-run outline meshes |
| **Geometry** | Full stroke geometry | Vector outlines | Outlines | Mesh curves |
| **3D Text** | Extruded display text | ShapeString 3D | **Not supported (2D host)** | 2D only |

LibreCAD honestly exposes **Labels** and **Outlines** in GUI; CLI retains all four modes for parity, but `3d_text` and `glyphs` export as DXF TEXT equivalent to Labels.

### 1.3 Any-PC portability

Every importer is designed to run on **any Windows PC** without relying on OS-bundled Python, Ruby, or Poppler:

- **Bundled Poppler** (where needed for vector extraction)
- **Bundled PyMuPDF** (Python hosts; Blender bootstrap with ABI-aware vendoring)
- **Portable installers** (Inno Setup EXEs, SketchUp RBZ, Blender add-on ZIP)
- **Preflight commands** (`--preflight`, `preflight_check.py`, SU pre-import messagebox) verify dependencies before import

Non-technical users are a first-class audience: one-click or few-click install paths are prioritized over developer-only workflows.

### 1.4 Steel Logic app and steel_shapes ecosystem

Beyond CAD importers, the ecosystem includes:

- **Steel Logic app** (`C:\1 Structural_Steel_Shapes_App`, GitHub `BlueCollar-Systems/Steel-Shapes`) — offline AISC shape lookup, inventory, job clock, PDF callout lookup (Round 6 slice).
- **steel_shapes ecosystem** — related repos for DXF/DWG shapes, SketchUp shape libraries, screenshots, and website download metadata.
- **Future bridge:** PDF-BOM → takeoff via `import_report.json` / CSV ingestion (partial — callout lookup shipped; full BOM bridge open).

### 1.5 Validation philosophy

- **Real fab-shop PDFs** (e.g. `1017 - Rev 0.pdf`, welding charts, multi-sheet shop sets) are Tier-1 human confirmation targets.
- **Web-acquired corpora** (pdf.js, OpenPreserve, PDF Association) supplement breadth under Apache-2.0 / open licenses.
- **User proprietary shop PDFs** stay **manifest-only** in git — never committed.
- Synthetic stress PDFs (`corpus-stress/`) target documented failure modes with WASM oracle validation.

---

## 2. Parameters and constraints

### 2.1 Host software matrix

| Host | Minimum / target | Runtime notes |
|------|------------------|---------------|
| **SketchUp** | 2017+ | **Ruby 2.2 baseline** on SU 2017 — syntax and API constraints are real; CI Ruby 2.2 gate enforced |
| **FreeCAD** | Current stable + prior versions where practical | Python embedded in FreeCAD; pdfcadcore canonical |
| **LibreCAD** | Current stable | **2D honest** — no 3D text; portable ZIP is canonical install |
| **Blender** | **5.x** (5.1.2 smoke-tested) | cp310-abi3 wheels; add-on path and PyMuPDF bootstrap |

Each host adapter implements the same **BCS-ARCH-001** mode model; host-specific limitations are documented in per-repo `COMPATIBILITY.md` and the website capability matrix.

### 2.2 Canonical paths on `C:\`

| Path | Role |
|------|------|
| `C:\1PDF-Importer-SketchUp` | Canonical SketchUp importer (git: `BlueCollar-Systems/PDF-Importer-SketchUp`) |
| `C:\1PDF-Importer-FreeCAD` | Canonical FreeCAD importer |
| `C:\1PDF-Importer-LibreCAD` | Canonical LibreCAD importer |
| `C:\1PDF-Importer-Blender` | Canonical Blender importer |
| `C:\1pdf-test-corpus` | Canonical test corpus — set `BCS_CORPUS_ROOT` |
| `C:\1BlueCollar-Website` | Website + Report Doctor |
| `C:\1 Structural_Steel_Shapes_App` | Steel Logic app |
| `C:\Users\Rowdy Payton\Desktop\PDFTest Files\Q&A\` | **Authoritative anonymous Q&A drop zone** |
| `C:\Users\Rowdy Payton\Desktop\PDFTest Files\` | User shop PDF mirror source |

**Stale / absent paths (do not use):**

- `C:\1SU-PDFimporter` — empty, not a git clone
- `C:\1pdfcadcore`, `C:\1FC-PDFimporter`, `C:\1LC-PDFimporter`, `C:\1BL-PDFimporter` — absent; pdfcadcore lives inside FreeCAD and syncs to LC/BL

### 2.3 QA process parameters

- **Anonymous reviewers** (A/B/C/D or role labels) — no self-answering; no author names in Q&A.
- **Minimum four agreements** required for documentation commit/push gate (achieved 2026-06-25).
- **Coordination hub** (`QA-2026-06-24_COORDINATION-HUB.md`) is the single team channel.
- **Desktop Q&A authoritative**; mirrored to `_LLM_CONTROL_PACK/QA/` in each repo.
- **Priority tags:** P0 (blocks release) · P1 (next slice) · P2 (moonshot/research).

### 2.4 Legal and licensing constraints

| Topic | Policy |
|-------|--------|
| **SketchUp 2017 installer** | **Do not host** SketchUp Make 2017 on the website — Trimble redistribution/trademark constraints |
| **User shop PDFs** | Manifest-only in git; proprietary; mirror from Desktop |
| **Web corpus tiers** | Apache-2.0 (pdf.js), OpenPreserve, CC BY-SA 4.0 (PDF 2.0 examples) — acquired under documented licenses |
| **GWG / NIST / Adobe** | Manifest-only or never bundle per license |
| **GitHub org** | `BlueCollar-Systems` — private corpus repo `pdf-test-corpus` |

### 2.5 Explicit non-claims

The project **does not** claim:

1. **LibreCAD 3D text** — 2D host; 3D text modes are honestly N/A or CLI-parity only.
2. **Pixel parity across hosts** — same PDF may look slightly different in SU vs FC vs LC vs BL due to text engines, mesh vs NURBS, and DXF TEXT limitations.
3. **CI green = field sign-off** — automated tests are necessary but not sufficient; human confirmation script must be executed.
4. **Per-span OCG on geometry text** — Round 3 ruling: geometry text uses layer grouping; not per-span OCG tags.
5. **Blender separate per-character glyph objects** — current releases do not claim this; T-06 resolved by documenting Glyphs as text-run outline meshes.

---

## 3. Architecture snapshot

### 3.1 Core engine layout

```
PDF file
   │
   ├─► Python hosts (FC, LC, BL)
   │      pdfcadcore (canonical in FreeCAD)
   │      ├── Poppler / PyMuPDF extraction
   │      ├── import_report.json writer (bcs.import_report/1.1)
   │      └── host adapter (FC sketcher, LC DXF, BL mesh)
   │
   └─► SketchUp host
          Ruby engine (extracted/sketchup_ext/)
          ├── qa_report.rb mirrors import_report schema
          ├── Import Health menu
          └── RBZ release packaging
```

- **pdfcadcore** is embedded in `1PDF-Importer-FreeCAD` and **synced** to LibreCAD and Blender via manifest + `pdfcadcore_sync_check.py`.
- **SketchUp** maintains a **Ruby mirror** of report schema and diagnostics — not a Python subprocess for core import.

### 3.2 import_report.json schema

- **Schema ID:** `bcs.import_report/1.1`
- **Canonical implementation:** `pdfcadcore/import_report.py` (Python); `qa_report.rb` (SketchUp)
- **Key fields:**
  - `schema`, `version`, `source_pdf` (with SHA-256)
  - `fidelity` diagnostics (primitive counts, text mode, fallback flags)
  - `extra.human_summary` — plain-English import narrative (Round 4)
  - `extra.scale_crosscheck` — scale agreement banner data (Round 5)
  - Performance timing (`total_ms`; granular phases deferred P2)
- **Consumers:** host UI (Import Health), website **Report Doctor**, future Steel Logic BOM bridge

### 3.3 GitHub organization and repositories

| Repository | Purpose |
|------------|---------|
| `BlueCollar-Systems/PDF-Importer-SketchUp` | SketchUp extension |
| `BlueCollar-Systems/PDF-Importer-FreeCAD` | FreeCAD workbench + pdfcadcore canonical |
| `BlueCollar-Systems/PDF-Importer-LibreCAD` | LibreCAD portable + CLI |
| `BlueCollar-Systems/PDF-Importer-Blender` | Blender add-on |
| `BlueCollar-Systems/BlueCollar-Website` | Downloads, install help, Report Doctor |
| `BlueCollar-Systems/Steel-Shapes` | Steel Logic app |
| `BlueCollar-Systems/pdf-test-corpus` | Private test corpus manifest + web PDFs |

---

## 4. QA process timeline

### 4.1 Round 1 — Anonymous improvement reports (2026-06-23)

Four anonymous improvement reports (`QA-2026-06-23_improvement-report-01.md` … `04.md`) plus synthesis. Identified accuracy, performance, and parity opportunities across all hosts.

### 4.2 Round 2 — Challenge and resolution (2026-06-23)

Skeptical reviewers challenged Round 1 overclaims. **Outcome: CONDITIONAL GO** — dense-text performance fix accepted (SU v3.7.55+); wording softened; blocking sign-off tied to strict timing benchmark and manual retest.

### 4.3 Round 3 — Full-repo scan (2026-06-23) — CLOSED

Four reviewers scanned errors, improvements, cross-repo sync, and app/website. **Q1–Q5 resolved. Verdict: GO to push.** Automated tests and pdfcadcore sync green.

### 4.4 Field fixes — text and leaders (2026-06-23→24)

Text-leader alignment root cause fixed (SU v3.7.58). Eleven field screenshots reviewed; BOM vertical quantities (v3.7.59+), Blender PyMuPDF bootstrap, FC ShapeString sizing, LC launcher discovery — **fixed locally; user retest pending**.

### 4.5 Round 4 — Creative vision (2026-06-24)

Anonymous reviewers asked whether the project had gone "outside the box."

- **Phase 1 shipped:** `human_summary`, SU Import Health menu (v3.7.61), website capability matrix (v1.0.56), Report Doctor (v1.0.57–58).
- **Phase 2 open:** P0/P1 backlog (CLI stderr templates, span_quality, layers→tags, WASM core moonshots, etc.).
- **Close rule:** Phase 2 ships **or** user signs off field screenshot validation.

### 4.6 Round 5 — P0 backlog slice (2026-06-24)

Partial ship: scale cross-check (`extra.scale_crosscheck`), golden-vector oracles (`golden_oracles.json`), preflight copy deck. Deferred: R4-03 CLI stderr templates, R4-05 span_quality, R4-30 confidence %.

### 4.7 Outside-box extension (2026-06-24)

Website Report Doctor, metadata guard (no private Steel-Shapes assets in public metadata), Steel Logic privacy copy updates. Does not close overall QA session.

### 4.8 Round 6 — Corpus and app features (2026-06-24→25)

- Private `pdf-test-corpus` repo created on GitHub.
- Web-acquired Tier-1/Tier-2 PDFs documented and acquired.
- Synthetic stress corpus + WASM oracle (9/9 pass).
- Steel Logic **PDF Callout Lookup** shipped; full PDF-BOM bridge remains open.
- SU corpus placement gate: 25 OK + 1 expected encrypted-PDF refusal.

### 4.9 Four-reviewer agreement — GO to push (2026-06-25)

| Reviewer | Lens | Vote |
|----------|------|------|
| A | SketchUp / field-readiness | AGREE |
| B | Python hosts + pdfcadcore sync | AGREE |
| C | Process / coordination | AGREE (conditional: mirror + log) |
| D | Website + Steel app + legal | AGREE |

**4/4 AGREE — GO** for commit/push of Q&A mirrors. **Not** field-release sign-off.

### 4.10 Human confirmation script — NOT YET COMPLETED

`QA-2026-06-24_human-confirmation-script.md` defines a 60–90 minute shop-floor session across all hosts. **Status: ready but not started by the product owner.** This is open thread **T-01** (P0).

### 4.11 Coordination hub communication model

1. Read `QA-2026-06-24_COORDINATION-HUB.md` + `QA-2026-06-24_open-threads.md` first.
2. Append status to `QA-2026-06-24_worker-status-log.md`.
3. Post peer questions to open-threads; reply in `QA-2026-06-24_reply-<topic>.md`.
4. Search Desktop Q&A before creating duplicate docs.
5. Bump workstream table when blocked or done.

### 4.12 Incident — Ruby 2.2 load failure (2026-06-25)

| Item | Detail |
|------|--------|
| **Reporter** | Field customer (SketchUp 2017) |
| **Symptom** | Extension fails to load — Ruby syntax error at parse time |
| **Root cause** | Endless range `text[-69..]` in `import_health.rb` (Ruby 2.6+); `.positive?` in `qa_report.rb` (Ruby 2.3+) |
| **Fix** | v3.7.66 — `text[-69, 69]` and `> 0` comparisons |
| **Prevention** | v3.7.67/68 — `tools/ruby22_syntax_check.rb`, `test/ruby22_compat_test.rb`, CI workflow on Ruby 2.2 Docker |
| **Customer impact** | **v3.7.65 and earlier may fail on SketchUp 2017.** Use **v3.7.67+** (latest **v3.7.68**). |

---

## 5. Current shipped versions

Verified from **GitHub Releases** and **git tags** on `origin/main` as of **2026-06-25**:

| Component | Latest release tag | GitHub repo | Notes |
|-----------|-------------------|-------------|-------|
| **SketchUp** | **v3.7.68** | PDF-Importer-SketchUp | Supersedes v3.7.65 for SU 2017; includes Ruby 2.2 CI gate |
| **FreeCAD** | **v4.0.48** | PDF-Importer-FreeCAD | pdfcadcore canonical |
| **LibreCAD** | **v1.0.41** | PDF-Importer-LibreCAD | Portable ZIP canonical |
| **Blender** | **v1.0.44** | PDF-Importer-Blender | Blender 5.x cp310-abi3 |
| **Website** | **v1.0.62** | BlueCollar-Website | Report Doctor, capability matrix, preflight copy |
| **Steel Logic** | **v1.0.10** (tag) | Steel-Shapes | `pubspec.yaml` reports `1.0.9+11` build counter |

**Coordination hub snapshot** (human confirmation prep, slightly older): SU 3.7.66, FC 4.0.47, LC 1.0.40, BL 1.0.43, Website 1.0.60, Steel Logic 1.0.9+11 — use **release table above** as authoritative for downloads.

---

## 6. Status matrix — DONE vs IN PROGRESS vs BLOCKED

### 6.1 DONE

| Area | Evidence |
|------|----------|
| Core PDF import (all hosts) | Round 3 GO; corpus gates pass |
| BCS-ARCH-001 mode unification | `_LLM_CONTROL_PACK/BCS-ARCH-001.md`; clean-break tests |
| Four text modes (within host limits) | Text mode verification matrix; LC 2D honest |
| Bad-PDF gates | Encrypted/corrupt PDF graceful errors |
| Performance fixes | SU dense-text v3.7.55+; overhead pass |
| Deploy artifacts verified | User-verified Downloads builds; GitHub Releases current |
| Test corpus repo | `BlueCollar-Systems/pdf-test-corpus` private; `acquire_tier1.ps1` |
| pdfcadcore sync | `pdfcadcore_sync_check.py` ALL IN SYNC |
| Ruby 2.2 compatibility gate | v3.7.67/68 + CI scanner |
| Round 4 Phase 1 | human_summary, Import Health, capability matrix, Report Doctor |
| Round 5 slice 1 | scale_crosscheck, golden oracles, preflight copy |
| Four-reviewer doc push gate | 4/4 AGREE (2026-06-25) |
| Outside-box website slice | Report Doctor, metadata guard, privacy copy |
| Round 6 partial | Public corpus tooling; PDF Callout Lookup in Steel Logic |

### 6.2 IN PROGRESS

| Area | Owner / doc |
|------|-------------|
| Round 4 Phase 2 field validation | WS-R4P2 — P0/P1 backlog |
| Human confirmation session | WS-HC — script ready, not started |
| Round 5 P1 remainder | R4-03 CLI stderr, R4-05 span_quality, R4-30 confidence % |
| Steel Logic PDF-BOM bridge | T-10 — callout lookup only so far |
| Blender glyph semantics | T-06 resolved — docs/UI now describe text-run outline meshes |

### 6.3 BLOCKED

| Blocker | Waiting on |
|---------|------------|
| **T-01 Field screenshot sign-off** | Product owner / human tester retest of eleven screenshots |
| **Round 4 Phase 2 close** | User field sign-off **or** remaining P0 backlog ship |
| **Release sign-off** | Human confirmation script completion (Section 6 in script) |
| Optional moonshots | R4-27 WASM core, steellogic:// deep links, etc. — explicitly non-blocking |

---

## 7. How to participate

### 7.1 Start here (reading order)

1. **This briefing** — `QA-2026-06-24_third-party-project-briefing.md`
2. **`QA-2026-06-24_COORDINATION-HUB.md`** — active workstreams and blockers
3. **`Q&A_INDEX.md`** — full document map
4. **`QA-2026-06-24_open-threads.md`** — unresolved peer questions
5. Host-specific `HUMAN_CONFIRMATION.md` and `INSTALL.md` in each repo

### 7.2 Authoritative locations

| Location | Role |
|----------|------|
| `Desktop\PDFTest Files\Q&A\` | **Authoritative** anonymous reviewer drop zone |
| `_LLM_CONTROL_PACK/QA/` in each repo | Git-tracked mirror (sync after Desktop updates) |
| `_LLM_CONTROL_PACK/BCS-ARCH-001.md` | Architecture decision record |

### 7.3 Human confirmation script

**Path:** `QA-2026-06-24_human-confirmation-script.md`

- Duration: 60–90 minutes
- Tester: shop foreman or detailer + one engineer
- Corpus: `C:\1pdf-test-corpus` with `BCS_CORPUS_ROOT` set
- Preflight: `python C:\1pdf-test-corpus\tools\list_tier1.py --host <SU|FC|LC|BL> --resolved`
- Tier-1 PDF matrix with per-host text mode checkboxes
- Sign-off block: GO / NO-GO for release

### 7.4 Corpus setup

```powershell
git clone https://github.com/BlueCollar-Systems/pdf-test-corpus C:\1pdf-test-corpus
$env:BCS_CORPUS_ROOT = 'C:\1pdf-test-corpus'
powershell -ExecutionPolicy Bypass -File C:\1pdf-test-corpus\tools\acquire_tier1.ps1
powershell -ExecutionPolicy Bypass -File C:\1pdf-test-corpus\tools\acquire_tier1.ps1 -MirrorDesktop
```

Access to the private corpus repo requires org invitation from the project owner.

### 7.5 Anonymous Q&A rules (from source instructions)

- Ask at least four questions; answer at least three others' questions.
- Do not answer your own questions.
- No author names — remain anonymous to avoid bias.
- Free use of tools, extensions, and dependencies.
- Importers must bundle all required dependencies for any-PC portability.

---

## 8. Deploy artifacts reference

### 8.1 GitHub Releases (primary download source)

| Host | Latest artifact | Install |
|------|-----------------|---------|
| SketchUp | `SketchUp-PDF-Importer_v3.7.68.rbz` | Extension Manager → Install Extension |
| FreeCAD | v4.0.48 release bundle | Workbench install per INSTALL.md |
| LibreCAD | v1.0.41 portable ZIP | Extract; run `LibreCAD-PDF-Importer.exe` |
| Blender | v1.0.44 add-on ZIP | Preferences → Add-ons → Install |
| Website | v1.0.62 snapshot | Deployed to bluecollar-systems.com |
| Steel Logic | v1.0.10 | App store / sideload per repo README |

### 8.2 Version supersession notes

- **User-verified Downloads builds at v3.7.65** (and matching FC/LC/BL versions) were validated in deploy artifact verification — functional for modern SketchUp hosts.
- **For SketchUp 2017 (Ruby 2.2):** v3.7.65 **fails to load**. Minimum **v3.7.66** (hotfix); recommended **v3.7.67** or **v3.7.68** (includes CI prevention gate).
- Always prefer **latest tag** from GitHub Releases unless regression testing a specific version.

### 8.3 Automated verification commands

```powershell
# pdfcadcore sync (from FreeCAD repo)
python pdfcadcore_sync_check.py

# SketchUp QA + golden oracle
ruby test/qa_report_test.rb
$env:BCS_CORPUS_ROOT='C:\1pdf-test-corpus'; ruby tools/run_golden_oracle_test.rb

# Ruby 2.2 gate (SketchUp)
ruby tools/ruby22_syntax_check.rb --include-tests
ruby test/ruby22_compat_test.rb

# Python hosts
pytest -q   # LC: 45 pass; BL: 42 pass (per agreement synthesis)
```

---

## 9. Open questions — answered preemptively (FAQ)

### Are we at 100% accuracy?

**No — and we do not claim to be.** We target indistinguishable-from-source within host limits. Some PDF classes (encrypted, corrupt, exotic fonts, dense hybrid scans) will always have honest fallbacks. The `human_summary` and Import Health surfaces explain what happened per import.

### Can we ship?

**Engineering artifacts: yes — releases are published.**  
**Product / field sign-off: not yet.** Human confirmation script (T-01) has not been executed by the product owner. Four-reviewer agreement authorized **documentation push**, not final release.

### What's left?

1. **P0:** Human field retest of eleven screenshots + full human confirmation session.
2. **P1:** Round 4 Phase 2 remainder (CLI stderr templates, span_quality, Steel Logic BOM bridge).
3. **P2:** Moonshots (WASM core, live preview, steellogic://, self-learning loop).

### Who decides GO?

| Gate | Decider |
|------|---------|
| Code/doc commit push (achieved) | ≥4 anonymous reviewers AGREE |
| Field release sign-off | Product owner completing human confirmation script with NO-GO list empty |
| Architecture changes | BCS-ARCH-001 — reject preset reintroduction |

### Is CI green enough?

**No.** CI proves regression safety and sync integrity. Field sign-off requires a human tester on real shop PDFs in real SketchUp/FreeCAD/LibreCAD/Blender installs.

### Can we host SketchUp 2017 for legacy users?

**No.** Website documents non-redistribution; users must obtain SketchUp 2017 independently. We **do** support SU 2017 with v3.7.67+ RBZ.

### Does LibreCAD do 3D text?

**No.** LibreCAD is 2D. CLI accepts 3d_text/glyphs for parity but exports DXF TEXT equivalent to Labels. Documented in COMPATIBILITY.md and capability matrix.

### Is pdfcadcore a separate repo?

**On this machine, no.** Canonical copy lives in `1PDF-Importer-FreeCAD`; manifest-synced to LC and BL. SketchUp uses Ruby, not pdfcadcore Python.

### What about the Steel Logic app?

Shipped through v1.0.10 with PDF Callout Lookup (copy designation → shape data). Full import_report ingestion for BOM takeoff is the next P1 slice.

---

## 10. Peer-review footer — optional feedback for third party

This briefing aims to leave **no required questions**. If you have capacity, the project welcomes optional anonymous feedback on:

1. **Gap analysis:** After reading Section 6, is any **P0** blocker missing from the open-threads list?
2. **Host honesty:** Does the capability matrix (`bluecollar-systems.com` install help + per-repo `COMPATIBILITY.md`) still overpromise anywhere?
3. **Corpus adequacy:** Is Tier-1 (`list_tier1.py --resolved`) sufficient for fab-shop sign-off, or should specific PDF classes be added to Tier-2?
4. **Human confirmation script:** Is the 60–90 minute script in `QA-2026-06-24_human-confirmation-script.md` complete for your shop workflow, or should cases be added?

Reply via `QA-2026-06-24_reply-<your-topic>.md` in Desktop Q&A and link from `QA-2026-06-24_open-threads.md`.

---

## Document map (quick links)

| Document | Purpose |
|----------|---------|
| `Q&A_INDEX.md` | Master index — start navigation |
| `QA-2026-06-24_COORDINATION-HUB.md` | Live workstreams |
| `QA-2026-06-24_agreement-synthesis.md` | 4/4 GO vote record |
| `QA-2026-06-23_round3-resolution.md` | Round 3 close |
| `QA-2026-06-24_round4-resolution.md` | Creative QA Phase 1/2 |
| `QA-2026-06-24_round5-resolution.md` | P0 backlog slice |
| `QA-2026-06-24_human-confirmation-script.md` | Field test script |
| `QA-2026-06-24_ruby22-compat-gate.md` | SU 2017 incident |
| `QA-2026-06-24_test-corpus-web-research.md` | Corpus licensing tiers |
| `QA-2026-06-24_open-threads.md` | Unresolved threads |

---

*Anonymous Project Briefing — BlueCollar PDF Importer Ecosystem — 2026-06-25*
