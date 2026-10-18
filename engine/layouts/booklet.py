"""
booklet.py

Saddle-stitch booklet imposition: computes which two source pages go
side-by-side on each side of each physical sheet, so that when the
printed sheets are stacked, folded in half, and stitched at the
crease, the pages read in order 1, 2, 3, ... N.

This module is pure page-number arithmetic -- no PDF library
dependency -- so the imposition math can be verified independently of
how the sheets actually get rendered (see layout_engine.py for that).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class SheetPages:
    """One physical sheet's four page slots, 1-indexed page numbers.
    0 means "blank" (used to pad a page count that isn't a multiple
    of 4 -- every booklet needs a multiple of 4 source pages, padding
    with blanks at the end)."""

    sheet_number: int
    front_left: int
    front_right: int
    back_left: int
    back_right: int


def compute_sheet_pages(page_count: int) -> List[SheetPages]:
    """Compute the front/back page pairing for every sheet.

    Standard saddle-stitch formula: for a booklet of n pages (n a
    multiple of 4), sheet i (0-indexed) carries:
        front: [n - 2i,      2i + 1]
        back:  [2i + 2,      n - 2i - 1]

    A page_count not divisible by 4 is padded with blank (0) pages at
    the end, since a folded sheet always contributes exactly 4 page
    slots -- there's no way to print a booklet with a partial sheet.
    """
    if page_count <= 0:
        return []

    padded = page_count
    while padded % 4 != 0:
        padded += 1

    sheets: List[SheetPages] = []
    n = padded
    for i in range(padded // 4):
        front_left = n - 2 * i
        front_right = 2 * i + 1
        back_left = 2 * i + 2
        back_right = n - 2 * i - 1

        sheets.append(
            SheetPages(
                sheet_number=i + 1,
                front_left=front_left if front_left <= page_count else 0,
                front_right=front_right if front_right <= page_count else 0,
                back_left=back_left if back_left <= page_count else 0,
                back_right=back_right if back_right <= page_count else 0,
            )
        )
    return sheets


def verify_pairing_invariant(sheets: List[SheetPages], page_count: int) -> bool:
    """Sanity-check the imposition against the defining property of
    correct saddle-stitch pairing: on every sheet, the two front pages
    sum to (padded_page_count + 1), and so do the two back pages --
    this holds because folding N pages in half always pairs page k on
    one layer with page (N+1-k) directly across the fold from it.

    Also checks every page 1..page_count appears in exactly one slot
    (no duplicates, nothing missing) and every non-zero slot value is
    a valid page number.
    """
    if not sheets:
        return page_count == 0

    # padded count = 4 * number of sheets
    padded = len(sheets) * 4
    expected_sum = padded + 1

    seen = set()
    for s in sheets:
        front_pair = [p for p in (s.front_left, s.front_right) if p != 0]
        back_pair = [p for p in (s.back_left, s.back_right) if p != 0]
        if len(front_pair) == 2 and sum(front_pair) != expected_sum:
            return False
        if len(back_pair) == 2 and sum(back_pair) != expected_sum:
            return False
        for p in (s.front_left, s.front_right, s.back_left, s.back_right):
            if p != 0:
                if p in seen or p > page_count:
                    return False
                seen.add(p)

    return seen == set(range(1, page_count + 1))
