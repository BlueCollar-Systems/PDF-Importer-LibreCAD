# PDF Test Corpus — Web Research (2026-06-24)

**Purpose:** Legally usable PDF sources for BlueCollar importer human confirmation and CI stress tiers.  
**Scope:** SketchUp, FreeCAD, LibreCAD, Blender importers + Steel Logic app workflows.

---

## Tier 1 — Must-have for human confirmation

| ID | File / set | Source URL | License | What it tests | Hosts | Acquisition |
|----|------------|------------|---------|---------------|-------|-------------|
| T1-01 | `1017 - Rev 0.pdf` | User shop corpus (`Desktop/PDFTest Files`) | Proprietary — **do not commit to git** | Fabrication/structural steel member drawing; dimensions; typical fab PDF | SU, FC, LC, BL, app | **User desktop mirror** → `tier1/user/1017 - Rev 0.pdf` |
| T1-02 | `Welding-Symbol-Chart.pdf` | User desktop | Proprietary — manifest only in git | Welding symbols, annotation density, hybrid scan+vector | SU, FC, LC, BL | **User desktop mirror** |
| T1-03 | `1011 (1 OF 2) - Rev 0.pdf` + `(2 OF 2)` | User desktop | Proprietary — manifest only | Multi-page shop set, title blocks, BOM-adjacent text | All | **User desktop mirror** |
| T1-04 | `hello_world_rotated.pdf` | [mozilla/pdf.js test/pdfs](https://github.com/mozilla/pdf.js/tree/master/test/pdfs) | **Apache-2.0** (repo license) | Page rotation (`/Rotate`), text placement after transform | SU, FC, LC, BL | **Acquired** → `tier1/web/pdfjs/hello_world_rotated.pdf` |
| T1-05 | `helloworld.pdf` | pdf.js test suite | Apache-2.0 | Baseline vector + text sanity | All | **Acquired** |
| T1-06 | `doc_1_3_pages.pdf` (+ doc_2, doc_3) | pdf.js test suite | Apache-2.0 | Multi-page document tree, page labels | All | **Acquired** |
| T1-07 | `Simple PDF 2.0 file.pdf` | [pdf-association/pdf20examples](https://github.com/pdf-association/pdf20examples) | **CC BY-SA 4.0** | Clean vector/text teaching PDF; PDF 2.0 syntax | All | **Acquired** |
| T1-08 | `text_only_fontsNotEmbedded.pdf` | [openpreserve/format-corpus pdfCabinetOfHorrors](https://github.com/openpreserve/format-corpus/tree/master/pdfCabinetOfHorrors) | OpenPreserve corpus (openly licensed test set) | Text extraction without embedded fonts | All | **Acquired** |
| T1-09 | `webCapture.pdf` | OpenPreserve Cabinet | OpenPreserve | Hybrid vector + raster web-capture style | SU, FC, BL | **Acquired** |
| T1-10 | `SCOMBINED.pdf` | User desktop | Proprietary — manifest only | Large multi-sheet combined export | SU, FC | **User desktop mirror** |

---

## Tier 2 — Stress / edge (automated + spot human)

| ID | File / set | Source URL | License | What it tests | Hosts | Acquisition |
|----|------------|------------|---------|---------------|-------|-------------|
| T2-01 | `encryption_openpassword.pdf` | OpenPreserve Cabinet | OpenPreserve | Encrypted PDF (open password workflow) | All | **Acquired** (expect graceful error or password prompt) |
| T2-02 | `corruptionOneByteMissing.pdf` | OpenPreserve Cabinet | OpenPreserve | Corrupt/truncated PDF handling | All | **Acquired** |
| T2-03 | `encrypted-attachment.pdf` | pdf.js tests | Apache-2.0 | Encryption + attachments | All | **Acquired** |
| T2-04 | GWG Processing Steps ZIP (3 PDFs) | [gwg.org/download/processing-steps-specification](https://gwg.org/download/processing-steps-specification/) | GWG IP — testing OK; **no modification**; promo needs permission | **OCG / ISO 19593-1 layers** (cut, varnish, braille) | SU, FC, BL | **Manifest-only** — user must download ZIP |
| T2-05 | NIST PMI test drawings (CTC/FTC) | [NIST MBE PMI download](https://www.nist.gov/ctl/smart-connected-systems-division/smart-connected-manufacturing-systems-group/mbe-pmi-0) | **Public domain (US Gov)** | GD&T, welding symbols, fractions, dimensions | FC, SU | **Manifest-only** — download STEP/PDF derivatives from NIST |
| T2-06 | NIST Reference Building architectural PDFs | [NIST plumbing/architectural drawings](https://www.nist.gov/system/files/documents/2023/07/31/NIST_Reference_Building_Plumbing_Models_Plumbing_Drawings.pdf) | Public domain | Architectural CAD export, schedules, multi-page | All | **Manifest-only** |
| T2-07 | Apache Tika Issue Tracker corpus (sample) | [corpora.tika.apache.org](https://corpora.tika.apache.org/base/packaged/pdfs/) | Per-bug attachment; **malformed subset** | Bad PDFs from real parser bugs | Core only | **Manifest-only** — pick named samples, scan with AV |
| T2-08 | `BOUND SET SEALED DRAWINGS 18 FEB 2026*.pdf` | User desktop | Proprietary | Large architectural set, fonts embedded variant, hybrid | SU, FC | **User desktop** (manual QA; CI opt-out) |
| T2-09 | `annotation-link-text-popup.pdf` | pdf.js | Apache-2.0 | PDF annotations, link popups | All | **Acquired** |
| T2-10 | Poppler test repo subset | [gitlab.freedesktop.org/poppler/test](https://gitlab.freedesktop.org/poppler/test) | **Mixed / unaudited** — some NC files | Real-world edge cases | — | **Do not bundle** — reference only |

---

## Tier 3 — Nice-to-have

| ID | File / set | Source URL | License | What it tests | Acquisition |
|----|------------|------------|---------|---------------|-------------|
| T3-01 | pdf.js full suite (~1.3k PDFs) | [github.com/mozilla/pdf.js/tree/master/test/pdfs](https://github.com/mozilla/pdf.js/tree/master/test/pdfs) | Apache-2.0 | Regression breadth | Clone on demand |
| T3-02 | PDF Association pdf20examples (full) | [github.com/pdf-association/pdf20examples](https://github.com/pdf-association/pdf20examples) | CC BY-SA 4.0 | PDF 2.0 feature matrix | Clone on demand |
| T3-03 | PDF-TREX table dataset (100 PDFs) | [staff.icar.cnr.it/ruffolo/pdf-trex](http://staff.icar.cnr.it/ruffolo/pdf-trex) | Research dataset | Table/BOM layout | **User must download** |
| T3-04 | Tamir Hassan table PDFs | [tamirhassan.com/html/dataset.html](http://www.tamirhassan.com/html/dataset.html) | Academic | EU/US gov table PDFs | **User must download** |
| T3-05 | USGS US Topo geospatial PDF | [pubs.usgs.gov/tm/tm11b2](https://pubs.usgs.gov/tm/tm11b2/) | Public domain | GeoPDF layers, OCG-like behavior | **User must download** quads |
| T3-06 | FreeCAD forum `tavola_prova_freecad.pdf` | [forum.freecad.org](https://forum.freecad.org/viewtopic.php?f=24&t=60689) | Author upload — **check thread** | Architectural TechDraw export | **User must download** |
| T3-07 | Asymptote gallery PDFs | [asymptote.sourceforge.io/gallery/PDFs](https://asymptote.sourceforge.io/gallery/PDFs/index.html) | GPL (Asymptote) | Advanced shadings, clips | Selective download |
| T3-08 | VeraPDF corpus | [github.com/veraPDF/veraPDF-corpus](https://github.com/veraPDF/veraPDF-corpus) | Check per-file | PDF/A edge validation | Clone on demand |
| T3-09 | IUST-PDFCorpus | [zenodo.org/records/3484013](https://zenodo.org/records/3484013) | Research | Fuzz/reader stress | **Do not bundle** (6k+ files) |
| T3-10 | Adobe demo assets | Adobe Demo Asset Terms | **No redistribution** | Marketing samples | **Never bundle** |

---

## Sources explicitly excluded from git bundles

| Source | Reason |
|--------|--------|
| Adobe Acrobat engineering samples (Wayback) | Unclear/redistribution restricted |
| Isartor PDF/A suite | Redistribution not allowed ([pdfa.org terms](https://www.pdfa.org/resource/isartor-test-suite/)) |
| Cal Poly PDF/VT suite | May not alter; redistribution only via PDF Association |
| Poppler test repo (bulk) | Mixed unknown licenses ([Guix discussion](https://lists.libreplanet.org/archive/html/guix-devel/2022-06/msg00394.html)) |
| UNSAFE-DOCS / CC-MAIN unsafe | Malicious by design |
| User bound sets / client PDFs | Copyright — desktop mirror only |

---

## Recommended canonical layout (`C:\1pdf-test-corpus`)

```
manifest.json
README.md
tools/
  acquire_tier1.ps1
  list_tier1.py
tier1/
  web/          ← Apache-2.0 / CC BY-SA / OpenPreserve downloads
  user/         ← copies or junctions from Desktop/PDFTest Files (gitignored)
tier2/
  manifest-only/  ← JSON pointers only
tier3/
  references.md
```

Set `BCS_CORPUS_ROOT=C:\1pdf-test-corpus` for CI and human confirmation scripts.

---

## Index reference

Master index of public corpora: [pdf-association/pdf-corpora](https://github.com/pdf-association/pdf-corpora) (CC BY 4.0 index; **each linked corpus has its own license**).

*Research completed 2026-06-24 for BlueCollar human confirmation prep.*
