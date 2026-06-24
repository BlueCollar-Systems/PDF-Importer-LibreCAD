# Round 4 — Cross-Reviewer Debate

**Session:** 2026-06-24  
**Participants:** Reviewers A, B, C, D (anonymous)  
**Format:** Respond, disagree productively, rank by impact vs effort

---

## Opening synthesis

All four agree: **import_report is the spine**. Round 4 should make it speak human without dumbing down engineering truth. Disagreement is *where* to invest UI vs core vs ecosystem.

---

## Debate threads

### Thread 1 — Live preview (A) vs golden vectors (B)

**A:** Preview stops bad imports at the door — highest UX leverage in SketchUp.  
**B:** Preview without oracles is lipstick; you’ll preview confidently wrong geometry on regression.  
**C:** Shop users won’t wait 2s twice — preview must be optional, default off.  
**D:** Neither helps steel callouts specifically — prioritize designation parser after summary ships.

**Resolution:** Golden vectors (B-5) next sprint; preview (A-1) moonshot. **Ship human_summary first** — zero regression risk, helps support immediately.

---

### Thread 2 — human_summary (B) vs preflight wizard (C)

**B:** Summary is post-hoc; wizard is preventive.  
**C:** Wizard scope creeps per host — summary is one function, all hosts.  
**A:** Import Health + summary covers 80% of support calls.  
**D:** Summary should mention shape hints when fabrication profile detected.

**Resolution:** **Build human_summary + Import Health now.** Preflight wizard design doc next — shared copy deck across hosts, not shared UI yet.

---

### Thread 3 — Website matrix (C) vs in-host “what will I get?” (C-3)

**C:** Website matrix helps before download — reduces wrong-host installs.  
**A:** In-host dialog matters more after they’re committed to SU.  
**B:** Matrix should link to text mode docs and diagnostics fields.  

**Resolution:** **Website matrix shipped.** In-host dialog deferred — duplicate table in HtmlDialog when SU dialog refreshes.

---

### Thread 4 — Heatmaps (B-1) vs plain errors (C-2)

**B:** Heatmaps excite brilliant engineers — visual debugging.  
**C:** Foremen need sentences, not PNGs.  
**A:** SU won’t get heatmaps soon — don’t imply parity.

**Resolution:** Heatmaps backlog “next quarter.” Extend plain-error templates in CLI for LC/BL when touching stderr anyway.

---

### Thread 5 — Ecosystem (D) vs core extraction

**D:** Without story, we’re four GitHub repos.  
**B:** domain_hints in report is cheap; deep links are not.  
**C:** Website honest matrix *is* ecosystem story for now.

**Resolution:** Steel README ecosystem paragraph + website matrix cross-links — low effort. Parser/deep link moonshot.

---

## Impact vs effort ranking (group vote)

| Rank | Item | Impact | Effort | Verdict |
|------|------|--------|--------|---------|
| 1 | `extra.human_summary` (pdfcadcore + SU) | ★★★★★ | ★☆☆☆☆ | **Ship now** |
| 2 | SketchUp Import Health menu | ★★★★☆ | ★☆☆☆☆ | **Ship now** |
| 3 | Website capability matrix | ★★★★☆ | ★☆☆☆☆ | **Ship now** |
| 4 | Scale cross-check banner (A-2) | ★★★★★ | ★★★☆☆ | Next sprint |
| 5 | Golden vectors oracle (B-5) | ★★★★☆ | ★★★☆☆ | Next sprint |
| 6 | Preflight wizard (C-1) | ★★★★☆ | ★★★☆☆ | Design then ship |
| 7 | Layer fuzzy match (A-3) | ★★★☆☆ | ★★★☆☆ | Backlog |
| 8 | Confidence heatmaps (B-1) | ★★★☆☆ | ★★★☆☆ | Backlog |
| 9 | Steel designation parser (D-2) | ★★★★☆ | ★★★★☆ | Moonshot |
| 10 | Live preview (A-1) | ★★★★☆ | ★★★★★ | Moonshot |

---

## Productive disagreements (preserved)

1. **A vs B on preview:** Both right — preview is UX; oracles are QA. Sequence matters.  
2. **C vs B on heatmaps:** Engineers want visuals; users want sentences — serve both, different surfaces.  
3. **D vs all on steel:** Ecosystem wins when extraction emits structured hints, not when app nagging every import.

---

*Round 4 debate closed — proceed to backlog + resolution.*
