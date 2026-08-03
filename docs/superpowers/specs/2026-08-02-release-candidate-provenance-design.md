# Release Candidate Provenance Design

## Purpose

LibreCAD release publication already compares every distributable byte with an
accepted manifest. Version 1.0.78 strengthens that contract so acceptance also
proves which GitHub-hosted candidate run and source commit produced those bytes.
The process must stay fail-closed and preserve the existing two-push workflow:
the code commit produces a retained candidate, and a manifest-only descendant
commit authorizes publication of those identical bytes.

## Chosen approach

The release workflow writes `dist/release-candidate-provenance.json` after the
source and portable ZIPs have been built and smoked. It then signs both ZIPs
and the canonical sidecar together in one GitHub artifact attestation from the
pinned `actions/attest` v4 action. The sidecar records:

- schema and product version;
- repository, workflow, immutable workflow SHA, run ID, run attempt, and
  candidate head SHA;
- runner and deterministic build contract;
- SHA-256 and size of both candidate ZIPs; and
- a digest of the Git blobs that `build_release.py` includes in the source ZIP.

When the expected accepted-artifact check fails, GitHub retains the two ZIPs,
the provenance sidecar, and the old manifest for one day. Candidate acceptance
requires an explicit sidecar and a clean checkout at the recorded candidate
SHA. Before trusting the sidecar, the default acceptance path invokes
`gh attestation verify --format json` independently for both ZIPs and the
sidecar. It binds repository, signer workflow and immutable workflow SHA,
source digest/ref, GitHub-hosted runner, trigger, and exact run-attempt URI from
trusted certificate extensions. Historical results are filtered, and all three
subjects must expose the same exact attestation bundle containing the complete
three-name/digest subject set. A verifier callback exists only so offline unit
tests can inject a deterministic substitute; the CLI cannot bypass genuine
attestation verification. Acceptance also queries the authenticated GitHub run API for the
sidecar run ID, requires the exact attempt/head/workflow/event/branch and a
completed failure conclusion, downloads the named non-expired retained artifact
from that run into an isolated temporary directory, and byte-compares its two
ZIPs and provenance sidecar with the local acceptance inputs. The verifier then
rechecks the package payload digest, portable smoke, and four executable
members.

Portable extraction is lexically anchored to
`<canonical repo>/dist/windows-portable`. Before staging, rename, restore, or
removal, the repository root, `dist`, target, candidate, and backup chains are
checked for symbolic links, Windows junctions, or other reparse points. The ZIP
is extracted into a fresh sibling staging directory and atomically replaces
only that canonical target.

The resulting `bcs.release_artifacts/1.1` manifest embeds the candidate
provenance. Normal publication verification accepts either the candidate SHA or
a descendant whose only tracked change since the candidate is
`.release/accepted-artifacts.json`. It recomputes the package payload digest and
all artifact hashes, reconstructs the canonical original sidecar, then repeats
the original three-subject attestation and retained-run byte authentication.
This prevents a locally forged manifest-only descendant from authorizing a
release. The separate publisher job does not persist checkout credentials,
never runs repository scripts with a write token, and independently rehashes
both transferred ZIPs against the strict accepted manifest before tokened
release creation. Any other source, workflow, version, tree, ZIP, executable,
run, or attestation change fails closed.

## Alternatives rejected

1. Embedding provenance inside the ZIPs was rejected because including a ZIP's
   own digest creates a recursive hash problem and changes the bytes being
   accepted.
2. Relying only on GitHub artifact attestations remains rejected because
   attestations establish signer/source provenance but do not replace the
   repository's deterministic byte-for-byte manifest gate. The two controls
   are now required together.
3. Continuing with hash-only schema 1.0 was rejected because a local dirty tree
   or unrelated candidate run could be deliberately accepted without a durable
   source/run binding.

## Native Text/Labels smoke

The portable smoke gate adds deterministic Text and Labels conversions using a
small synthetic LibreCAD Font 1 asset and a synthetic LibreCAD installation
layout. It launches no CAD host and reads no private PDF. For every native item,
the smoke reopens the generated DXF, resolves every reported entity handle to a
live modelspace `TEXT`, matches delivered content, and requires executable/LFF
binding, LFF hash and glyph coverage, cap-height serialization, and reopen proof
from the actual import report. Existing Glyphs smoke remains to protect the
exact-outline path.

## Safety and privacy

- ZIP extraction rejects absolute paths, drive-qualified paths, `..` traversal,
  symlinks/reparse-style entries, duplicate conflicting members, and unexpected
  layouts.
- Candidate and accepted manifests use exact schemas at every object level:
  unknown keys, duplicate keys, non-string runner metadata, `NaN`, `Infinity`,
  and private/local diagnostic metadata are rejected.
- Acceptance never deletes outside the canonical repository `dist` staging
  paths and uses atomic replacement where practical.
- The sidecar contains no private corpus paths or contents.
- Supplied PDFs and generated CAD/model counterparts remain outside every
  repository and release artifact.
- Schema 1.0 remains readable only for historical v1.0.77 verification tests;
  new v1.0.78 acceptance requires schema 1.1 provenance.

## Success criteria

1. Candidate provenance and one cryptographic attestation for both ZIPs and the sidecar are
   produced by the hosted workflow and the candidate is retained on the
   expected first verifier failure.
2. `--accept` refuses missing, stale, mismatched, locally fabricated,
   unattested, self-hosted, dirty-tree, or wrong-commit candidates.
3. A manifest-only descendant rebuilds byte-identical artifacts and publishes.
4. Any package-included change after the candidate invalidates acceptance.
5. Source ZIP, portable ZIP, four executables, and report/DXF-backed native
   Text/Labels smoke all verify before publication.
