# Round 3 Questions — Reviewer K

**Date:** 2026-07-02  
**Session:** New contributor verification and optimization focus

---

## Q1: Fraction stacking performance vs accuracy tradeoff

The handoff identifies a P0 regression where stacked fractions merge into flat, full-size tokens that overrun adjacent text (e.g., `4'-7/2`, `1'-0¾` in `1017 - Rev 0.pdf`). The root cause is in `pdfcadcore/primitive_extractor.py::_merge_stacked_fractions` with tolerances like `_FRAC_Y_SPREAD_MM = 4.5`.

**Question:** To maximize both accuracy and performance, should we:
- Render merged fractions at reduced scale to match original stacked footprint (more complex geometry, slower import)
- Keep flat merged tokens but improve spacing algorithms to prevent overlap (faster but less visually accurate)
- Implement adaptive merging based on text density analysis (balanced approach)

What is the target performance budget for text processing on typical shop drawings (50-100 pages)?

---

## Q2: Cross-host text mode consistency vs host limitations

The four text modes (Labels, 3D Text, Glyphs, Geometry) have different implementations across hosts:
- SketchUp: Native labels vs mesh text fallback
- FreeCAD: ShapeString with bbox shrinking
- LibreCAD: 2D honest (DXF TEXT only)
- Blender: Text-run outline meshes (not per-character)

**Question:** Should we prioritize:
- Visual consistency across hosts (same appearance, different entity types)
- Semantic consistency (same entity types, accept visual differences)
- Host-optimal implementations (each host uses its best native approach)

How do we document these differences honestly without confusing non-technical users?

---

## Q3: Dependency bundling strategy for antivirus false positives

The handoff notes EDR/antivirus quarantine of unsigned PyInstaller EXEs (LibreCAD portable) and unsigned FreeCAD installer as P1 issues.

**Question:** To maximize portability while minimizing false positives:
- Should we pursue code signing certificates (cost, maintenance overhead)
- Switch to different packaging (e.g., MSIX for Windows, signed installers)
- Provide multiple distribution formats (portable + installer)
- Focus on whitelist/reputation building with vendors

What's the acceptable support overhead for helping users with quarantine issues?

---

## Q4: Legacy host support impact on modern features

SketchUp 2017/Ruby 2.2 support is explicitly non-negotiable, but this restricts:
- Modern Ruby syntax (`<<~MSG`, `.match?`, `.positive?`)
- Advanced text layout algorithms
- Performance optimizations available in newer Ruby versions

**Question:** How do we balance:
- Maintaining SU 2017 compatibility (core mission requirement)
- Adding advanced features for modern SketchUp versions
- Code complexity from dual-path implementations

Should we consider feature detection at runtime with graceful degradation, or maintain a single lowest-common-denominator codebase?

---

## Q5: Real-world performance targets for heavy PDFs

The handoff mentions "large/heavy PDF performance on old PCs" as SketchUp backlog, but no concrete targets.

**Question:** What are the specific performance requirements:
- Maximum import time for 100-page architectural drawings on 8-year-old hardware
- Memory usage limits to avoid crashes on 4GB RAM systems
- Acceptable UI responsiveness during processing

Should we implement progressive loading/streaming for very large files, or focus on optimizing the current batch approach?

---

*All questions focus on the core tension between maximum accuracy/fidelity and practical performance/portability for non-technical shop users.*
