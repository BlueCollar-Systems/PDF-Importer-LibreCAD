# Preserve sampled curves across LibreCAD saves

The old two DXF writers inferred smooth curves from dense polylines and passed
their sampled vertices to `add_spline()` as FIT points. A real LibreCAD
2.2.1.5 / Qt 5.15.2 Save As changed the 33 FIT points into 33 CONTROL points
with clamped uniform knots. Those definitions describe different curves; matching
point counts did not prove that the source path survived. The failed native
comparison remains available with the local validation evidence.

`dxf_builder._add_polyline` and the adapter's primitive stroke emitter now keep
the admitted vertices as one editable polyline. Modern files use LWPOLYLINE;
R12 uses native POLYLINE. Original Bezier controls are not retained by the
current primitive carrier, so the writers do not invent or refit them. Existing
source-qualified circle/arc promotion is unchanged.

## Validation

- 60 focused tests passed in 17.34 seconds, including 19 new cases across both
  writers, R12/R2007/R2018, scales 1/2.5, dense angular paths, independent
  analytic cubic checks, and the existing circle/arc/visual checks.
- Python 3.9 syntax parsing passed for the two changed modules and the new test;
  this syntax check is not a claim that every dependency supports that runtime.
- A source-driven fictional vector PDF produced a repaired DXF, with no manual
  modification of that candidate. All 33 previously admitted curve vertices
  survive within 1e-12 mm. At 2,049 independently evaluated points on this
  fixture's original source cubic, the largest sampled distance to the polyline
  is 0.0343669 mm. This is a measured fixture approximation, not an all-PDF error
  bound or an exact Bezier-control claim.
- Actual LibreCAD File > Save As wrote DXF2007. Independent read-only comparison
  retains every supported individual geometric payload, the fill hole, units,
  visible bounds, filled SOLID area, and geometric redraw sequence. The curve
  remains a 33-vertex LWPOLYLINE; neither candidate nor saved drawing has SPLINE.
- The saved file audits with zero errors and one surfaced orphan PLOTSETTINGS
  housekeeping fix. This isolating vector case contains no text or raster;
  vacuous text/image checks are not counted as coverage.

- Root closed that native document, reopened the owned saved DXF through File >
  Open, and verified the actual loaded path in the title/status. The model view
  retains the same curve, circle/ellipse, rectangle, dash/stroke, hole and fill
  layout. This confirms the bounded real-host close/save/reopen check.

## Bound evidence

| Artifact | SHA-256 |
| --- | --- |
| Fictional vector source PDF | `8806b7974fe43b9fc91662f11ff9f7b10aa3424e6c711792ff81a15b2d0a47dc` |
| Source-created repaired DXF | `0d1d07c0a8aff39302dac454191141acce0243a07222d511242a148346fb0638` |
| Actual native DXF2007 save | `5df234f30217a141d729a06088a0eab548999b9987d850e1b3932c7db3aa80a6` |
| Independent curve source acceptance | `7231037665a8f582a32992eb8ec1899b1f8f4b52a5c702b37a5808c4ad79c3b9` |
| Independent native-save comparison | `59276ae68e43214bb519face44b17611c63ed7e3d9ef44b915974a4ade5cc70b` |
| Comparison helper v3 | `82a8012e464457ab3b352ce42e97cdb38425a6b25caaf40f671950ff9722ab0f` |
| Eleven semantic comparison controls | `c422ad0215f3496951fe0a6d8aba073b8b7dda1ff4613d1303195152a3d415d9` |

Whole-document semantic equivalence is deliberately not certified: the native
writer changes some color transport and drops source dash XDATA. Those changes
remain visible in the comparison. Single convex HATCH boundaries changing from
PolylinePath to the same closed LineEdge chain, duplicate endpoints of closed
zero-width straight polylines, and DXF standard symbol transport are handled by
narrow checked rules. Fit/control spline conversion, missing image assets,
changed contour points, hidden-layer flags, source text or unknown conversions
are not accepted as housekeeping.

The separate reproduced cross-folder IMAGE reference break is a different fix;
this polyline repair does not normalize or conceal it. Original fixtures, failed
comparisons, the diagnostic image failure and old test packages remain intact.
