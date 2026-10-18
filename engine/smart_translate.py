"""
smart_translate.py

The Smart Translation solver. Given a requested (dx, dy, rotation,
scale) and a page's content bounding box, finds a transform that
keeps content within the page (plus a safety margin) while NEVER
reducing the requested translation -- for printer-alignment
correction, the shift amount is a fixed physical calibration and
must be applied identically to every page; a page-by-page reduction
in shift defeats the entire purpose. Priority order:

  1. Apply the request exactly, if it already fits.
  2. Keep translation exactly as requested; reduce scale (within the
     user's allowed range) until the full shift fits.
  3. If it still doesn't fit even at the minimum allowed scale, apply
     the full requested translation anyway at the minimum scale and
     report a clipping warning -- the shift itself is never reduced,
     even as a last resort.

This module is pure geometry -- it has no pikepdf/fitz dependency of
its own, which makes it independent of engine/content_bounds.py's
"where did the content actually come from" concern and easy to unit
test on plain numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from engine.geometry import Transform, apply_matrix

BBox = Tuple[float, float, float, float]


@dataclass
class SmartTranslateSettings:
    prevent_clipping: bool = True
    minimum_scale_percent: float = 99.0
    maximum_scale_reduction_percent: float = 2.0
    safety_margin_mm: float = 2.0


@dataclass
class SmartTranslateResult:
    applied_dx: float
    applied_dy: float
    applied_scale: float
    requested_dx: float
    requested_dy: float
    requested_scale: float
    was_adjusted: bool
    fully_avoided_clipping: bool
    note: Optional[str] = None


def _bbox_corners(bbox: BBox):
    x0, y0, x1, y1 = bbox
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _transformed_bounds(bbox: BBox, matrix) -> BBox:
    corners = [apply_matrix(matrix, x, y) for x, y in _bbox_corners(bbox)]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _fits(
    content_bbox: BBox,
    page_box: BBox,
    dx: float,
    dy: float,
    rotation_deg: float,
    scale: float,
    cx: float,
    cy: float,
    margin_pt: float,
) -> bool:
    transform = Transform(dx=dx, dy=dy, rotation_deg=rotation_deg, pivot_x=cx, pivot_y=cy, scale=scale)
    bounds = _transformed_bounds(content_bbox, transform.matrix())
    px0, py0, px1, py1 = page_box
    bx0, by0, bx1, by1 = bounds
    return (
        bx0 >= px0 + margin_pt
        and by0 >= py0 + margin_pt
        and bx1 <= px1 - margin_pt
        and by1 <= py1 - margin_pt
    )


def solve(
    content_bbox: Optional[BBox],
    page_box: BBox,
    requested_dx: float,
    requested_dy: float,
    rotation_deg: float,
    requested_scale: float,
    settings: SmartTranslateSettings,
) -> SmartTranslateResult:
    """Find the best achievable transform for one page, never reducing
    the requested translation.

    content_bbox=None means content bounds couldn't be determined for
    this page (analysis failure or unsupported content) -- in that
    case the request is applied as-is with a note, since guessing
    conservatively would needlessly shrink/limit pages we have no
    real basis to doubt.
    """
    if content_bbox is None:
        return SmartTranslateResult(
            applied_dx=requested_dx,
            applied_dy=requested_dy,
            applied_scale=requested_scale,
            requested_dx=requested_dx,
            requested_dy=requested_dy,
            requested_scale=requested_scale,
            was_adjusted=False,
            fully_avoided_clipping=True,
            note="Content analysis unavailable for this page; applied requested values as-is.",
        )

    px0, py0, px1, py1 = page_box
    cx, cy = (px0 + px1) / 2.0, (py0 + py1) / 2.0
    margin_pt = settings.safety_margin_mm * 72.0 / 25.4

    def fits(scale: float) -> bool:
        return _fits(content_bbox, page_box, requested_dx, requested_dy, rotation_deg, scale, cx, cy, margin_pt)

    # 0. Exact request already fits -- the common case, fast path.
    if fits(requested_scale):
        return SmartTranslateResult(
            applied_dx=requested_dx,
            applied_dy=requested_dy,
            applied_scale=requested_scale,
            requested_dx=requested_dx,
            requested_dy=requested_dy,
            requested_scale=requested_scale,
            was_adjusted=False,
            fully_avoided_clipping=True,
        )

    # 1. Translation stays exactly as requested. Reduce scale within
    # the allowed range, searching for the smallest reduction that
    # makes the FULL shift fit -- the shift itself is never touched.
    min_scale = max(
        settings.minimum_scale_percent / 100.0,
        (requested_scale * 100.0 - settings.maximum_scale_reduction_percent) / 100.0,
    )
    min_scale = min(min_scale, requested_scale)  # never scale up

    if min_scale < requested_scale and fits(min_scale):
        # Fit improves monotonically as scale decreases (more margin),
        # so binary search for the largest scale <= requested that
        # still fits the full translation.
        lo, hi = min_scale, requested_scale  # lo fits, hi does not (already checked above)
        for _ in range(40):
            mid = (lo + hi) / 2.0
            if fits(mid):
                lo = mid
            else:
                hi = mid
        scale = lo
        return SmartTranslateResult(
            applied_dx=requested_dx,
            applied_dy=requested_dy,
            applied_scale=scale,
            requested_dx=requested_dx,
            requested_dy=requested_dy,
            requested_scale=requested_scale,
            was_adjusted=True,
            fully_avoided_clipping=True,
            note="Scale reduced to fit the full requested shift without clipping.",
        )

    # 2. Even the minimum allowed scale doesn't fully avoid clipping.
    # Apply the full requested translation anyway at the minimum
    # scale -- the shift is never reduced, even here -- and report
    # that some clipping may occur.
    scale = min_scale
    fully_avoided = fits(scale)
    note = (
        "Applied the full requested shift at reduced scale; some content may still "
        "be close to or past the edge at this page's minimum-margin areas. Translation "
        "was not reduced -- increase Maximum Automatic Reduction in Settings for more "
        "scale headroom, or accept this page's positioning."
    )
    return SmartTranslateResult(
        applied_dx=requested_dx,
        applied_dy=requested_dy,
        applied_scale=scale,
        requested_dx=requested_dx,
        requested_dy=requested_dy,
        requested_scale=requested_scale,
        was_adjusted=True,
        fully_avoided_clipping=fully_avoided,
        note=note,
    )
