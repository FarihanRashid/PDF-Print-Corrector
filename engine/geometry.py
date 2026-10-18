"""
geometry.py

Pure, dependency-free math for building PDF content-stream transformation
matrices (the six numbers used by the PDF ``cm`` operator) and for
transforming rectangles / quad points that live in *unrotated* default
page space (e.g. annotation ``/Rect`` and ``/QuadPoints`` entries, which
are NOT affected by a page's content stream and must be moved by hand).

All angles are in degrees, counter-clockwise positive, matching the
conventional mathematical / PDF user-space orientation (y axis points
up). All offsets are already expected to be expressed in PDF points
(1/72 inch) -- conversion from millimetres happens in the caller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

Matrix = Tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class Transform:
    """A rigid-body-plus-scale transform: scale about a pivot, then
    rotate about the same pivot, then translate.

    Composition order matches the app's transformation pipeline:
    Scale -> Rotation -> Translation. All three happen in a single
    matrix so the PDF content stream is only ever wrapped once.
    """

    dx: float
    dy: float
    rotation_deg: float
    pivot_x: float
    pivot_y: float
    scale: float = 1.0

    def matrix(self) -> Matrix:
        """Return the 6-number affine matrix (a, b, c, d, e, f).

        Maps a point (x, y) to (a*x + c*y + e, b*x + d*y + f), matching
        the operand order of the PDF ``cm`` operator.

        Derivation: for a point p, first scale and rotate about the
        pivot c = (pivot_x, pivot_y), then translate by (dx, dy):

            p' = R(theta) * scale * (p - c) + c + (dx, dy)

        Expanding gives the six matrix components below. Setting
        scale=1.0 reduces exactly to a pure rotate+translate, so this
        is a strict superset of the app's original transform.
        """
        theta = math.radians(self.rotation_deg)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        cx, cy = self.pivot_x, self.pivot_y
        s = self.scale

        a, b = s * cos_t, s * sin_t
        c, d = -s * sin_t, s * cos_t
        e = cx - s * (cx * cos_t - cy * sin_t) + self.dx
        f = cy - s * (cx * sin_t + cy * cos_t) + self.dy
        return (a, b, c, d, e, f)


def apply_matrix(matrix: Matrix, x: float, y: float) -> Tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def transform_rect(matrix: Matrix, rect: List[float]) -> List[float]:
    """Transform an axis-aligned rect [x0, y0, x1, y1].

    Because a rotation can tilt the rectangle, the result is the
    axis-aligned bounding box of the four transformed corners. For
    rotation == 0 this is exact with no bounding-box growth.
    """
    x0, y0, x1, y1 = rect
    corners = [
        apply_matrix(matrix, x0, y0),
        apply_matrix(matrix, x1, y0),
        apply_matrix(matrix, x1, y1),
        apply_matrix(matrix, x0, y1),
    ]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return [min(xs), min(ys), max(xs), max(ys)]


def transform_quad_points(matrix: Matrix, quad_points: List[float]) -> List[float]:
    """Transform an /QuadPoints array (groups of 4 (x, y) pairs)."""
    result: List[float] = []
    for i in range(0, len(quad_points) - 1, 2):
        x, y = quad_points[i], quad_points[i + 1]
        nx, ny = apply_matrix(matrix, x, y)
        result.extend([nx, ny])
    return result


def transform_point_list(matrix: Matrix, points: List[float]) -> List[float]:
    """Transform a flat [x0, y0, x1, y1, ...] list, e.g. /Vertices, /L."""
    result: List[float] = []
    for i in range(0, len(points) - 1, 2):
        x, y = points[i], points[i + 1]
        nx, ny = apply_matrix(matrix, x, y)
        result.extend([nx, ny])
    return result


def mm_to_points(mm: float) -> float:
    return mm * 72.0 / 25.4


def points_to_mm(points: float) -> float:
    return points * 25.4 / 72.0


def rotate_vector(dx: float, dy: float, angle_deg: float) -> Tuple[float, float]:
    """Rotate a 2D offset vector by angle_deg (counter-clockwise positive).

    Used to re-express a translation offset that was calibrated in
    "physical paper" space into a landscape page's own coordinate
    space, so the printed result lands in the same physical spot
    regardless of the page's authored orientation.
    """
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    return (dx * cos_t - dy * sin_t, dx * sin_t + dy * cos_t)


def normalize_landscape_transform(box: List[float], counter_clockwise: bool) -> Tuple[List[float], "Transform"]:
    """Compute the box + content transform that turns a landscape page
    into a portrait one, filling the new frame exactly (no scaling,
    no cropping -- old_w and old_h simply swap).

    Returns (new_box, transform) where new_box is [0, 0, new_w, new_h]
    and transform is the Transform to apply to the page's content and
    annotations. Verified against known reference corners; see the
    derivation notes below for why these specific translations are
    correct (get them wrong and content silently lands off-page).

    Clockwise (-90 deg): (x, y) -> (y, -x), then shift by (-y0, x1)
    Counter-clockwise (+90 deg): (x, y) -> (-y, x), then shift by (y1, -x0)
    Both map [x0, y0, x1, y1] exactly onto [0, 0, old_h, old_w].
    """
    x0, y0, x1, y1 = box
    if counter_clockwise:
        return [0.0, 0.0, y1 - y0, x1 - x0], Transform(dx=y1, dy=-x0, rotation_deg=90.0, pivot_x=0.0, pivot_y=0.0)
    return [0.0, 0.0, y1 - y0, x1 - x0], Transform(dx=-y0, dy=x1, rotation_deg=-90.0, pivot_x=0.0, pivot_y=0.0)
