# Final converter acceptance and v1.0.106 publication

The [reconciliation record](2026-10-11-pr69-reconciliation.md) is followed by
the completed source and converter checks below. Native LibreCAD GUI
import/save/reopen and page-composite rendering remain unverified; converter
and DXF persistence checks do not imply that GUI acceptance.

The reconciled runtime at `76ae0c4423dce75bca848e376fe42a94f4847953` passed
2,075 source tests, with 18 skips and 28 subtests. Frozen portable r4 passed
all four actual EXE self-tests and three neutral Glyphs/Text/Labels conversions;
their DXFs reopened with zero audit errors and zero fixes. The converter also
rejected a cyclic PDF without output, preserved its bytes and released its
source-file handle. Original-program triangle/rectangle adversarial tests
retained the exact-contour gate, with positive Glyphs/Geometry DXF persistence.
Version 1.0.106 preparation changed only version metadata; subsequent
publication-control changes did not alter importer runtime or shared core.

Canonical-main auto-release run `38165766090`, attempt 1, built the actual
production candidate at `fe2a0817a28f53cd55dbe2bbc2e5de82dd5b8a07` with
`publish_release=false`. Its source tests, builds, packaged smoke and GitHub
attestation passed. It deliberately failed the exact-byte gate against the
historical v1.0.105 manifest; the publisher was skipped. The failed candidate,
its canonical provenance and historical manifest were preserved.

The unchanged official Python 3.12.10 verifier authenticated that live failed
main run, the retained bytes and GitHub signer/source/ref attestations. It ran
the frozen converter smoke checks before atomic acceptance. Acceptance changed
only `.release/accepted-artifacts.json`; the source ZIP rebuilt after that
change with the same SHA256. The same official verifier passed again at the
committed descendant and merged main. PR #76's three required checks passed.

| Accepted artifact | Bytes | SHA256 |
| --- | ---: | --- |
| Source ZIP | 535,768 | `f539773fd7427a11c47864a8b4746b2e00b8f29ede20212a1ee5599875ac1b2a` |
| Windows portable ZIP | 266,026,019 | `8403c4dfa69e55f2660344b138371aae0dd6661cbd7eb693f2cad10c475b6461` |
| pdf2dxf.exe | 67,073,457 | `9c0cb8cd3acb28232fd25f7ee45e39388ca627588c2994a25325b1e53b64b09e` |
| lcpdf-import.exe | 67,081,405 | `280d3f3c4733187b9776e1204333b3e012c0f597fc162e54053b86ff9bc31ef2` |
| lcpdf-batch.exe | 67,086,535 | `9a87abda1385c473f5e37f78d642bc2d60509d75042f78d2ceb21c4bef227165` |
| lcpdf-gui.exe | 67,070,307 | `bb28d4475307e363508d4796e0dc12591a15d2feef512924bac37ddcaf6e3d1d` |

[Published v1.0.106](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases/tag/v1.0.106)
is immutable and targets accepted-manifest descendant
`a65ca605983d24912de69cf8c5c95549b9f443aa`. Only that manifest differs from
the original attested candidate source. The original two accepted ZIPs were
published directly, avoiding another hosted Windows rebuild; verification and
the manifest-only descendant guard were retained. Actual downloaded release
assets matched those accepted bytes.

The release also carries canonical provenance SHA256
`61ac5ab55850fee19921b3a9c8c3e0baea3ec08a67704b198493a2e0b937f8f7`,
accepted manifest SHA256
`22e70f8b81abd4bad31a9585630414b9f9ea7fae1f2e32dc4632f58d24e066f3`
and checksums. The bound merged-main verification receipt is
`fe61d7af1fa01b42d23e2b6098a1c59eae7c25732c3bd1c0a4fd07c25502cfa2`.

Local source/converter evidence remains in `LibreCAD/Validation-r4` in the test
hub, including `COLD-CONVERTER-CHECKS.json`, source validation and
`PUBLISHED-1.0.106-VERIFIED.json`. The attested candidate, original failed-run
proofs, historical manifest and official acceptance logs remain in separate
local evidence. These tests do not certify every PDF, font, operating system,
hardware configuration or native LibreCAD UI interaction.
