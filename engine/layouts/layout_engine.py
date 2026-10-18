"""
layout_engine.py

Builds the physical booklet PDF from the page pairing computed by
booklet.py: embeds each source page as a reusable Form XObject
(lossless -- fonts, vectors, images all pass through untouched) and
places two of them side-by-side per output sheet.

Duplex modes
------------
Long-edge (the common default for portrait documents, "flip on the
long edge / book-style"): back-side sheets use the same left/right
column arrangement as front sides.

Short-edge ("flip on the short edge / calendar-style", which is what
a manual short-edge duplex workflow needs): the entire back sheet is
rotated 180 degrees, which simultaneously swaps which column ends up
on which side AND corrects each page's up/down orientation -- this is
the same convention professional booklet-printing tools use, verified
here by construction (a 180-degree rotation is its own, unambiguous
correction for a flip along the perpendicular axis).

Auto vs Manual just changes how output pages are arranged:
  - Auto: a single PDF with front/back sheets interleaved in the
    order a printer's own duplex unit expects (front, back, front,
    back, ...), so the printer's "duplex: on" setting handles the
    physical alignment.
  - Manual: two separate PDFs (fronts, then backs) so the person can
    print all fronts, physically flip the stack by hand, and print
    backs as a second pass. Exactly how a specific printer's manual
    feed re-orders the stack varies by model, so a short test print
    is worth doing before committing a long document either way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pikepdf
from pikepdf import Array, Dictionary, Name, Pdf

from engine.geometry import Transform, mm_to_points
from engine.layouts.booklet import SheetPages, compute_sheet_pages


@dataclass
class BookletOptions:
    duplex_mode: str = "auto_long"  # "auto_long", "auto_short", "manual_long", "manual_short"
    gutter_mm: float = 0.0  # extra space at the spine, e.g. for stapling/binding margin
    sheet_gap_mm: float = 0.0  # gap between the two pages on a sheet


@dataclass
class BookletResult:
    sheet_count: int
    page_count: int
    output_paths: List[str]  # one path (auto modes) or two (manual: fronts, backs)
    warnings: List[str]


def _is_auto(duplex_mode: str) -> bool:
    return duplex_mode.startswith("auto")


def _is_short_edge(duplex_mode: str) -> bool:
    return duplex_mode.endswith("short")


def _reference_page_size(pdf: Pdf) -> Tuple[float, float]:
    """Use the first page's dimensions as the slot size every page is
    placed into. Booklet imposition assumes uniform page size (true
    after landscape normalization, and true for the vast majority of
    real documents); a page that differs gets centered and, if
    larger, is not resized (kept lossless -- see _place_page)."""
    box = pdf.pages[0].mediabox
    return float(box[2]) - float(box[0]), float(box[3]) - float(box[1])


def _place_page(
    sheet_pdf: Pdf,
    sheet_page,
    source_xobjects: dict,
    page_number: int,
    slot_x: float,
    slot_y: float,
    slot_w: float,
    slot_h: float,
) -> None:
    """Place source page `page_number` (1-indexed, 0 = blank) into a
    slot on the sheet at (slot_x, slot_y) sized slot_w x slot_h."""
    if page_number == 0:
        return  # blank slot -- nothing to draw

    xobj_name, xobj_ref, src_w, src_h = source_xobjects[page_number]

    # Center within the slot; only scale down if the source page is
    # actually larger than the slot (never upscale -- never enlarge
    # beyond the source's own resolution/vector precision).
    scale = min(slot_w / src_w, slot_h / src_h, 1.0)
    draw_w, draw_h = src_w * scale, src_h * scale
    offset_x = slot_x + (slot_w - draw_w) / 2.0
    offset_y = slot_y + (slot_h - draw_h) / 2.0

    if xobj_name not in sheet_page.Resources.get("/XObject", {}):
        if "/XObject" not in sheet_page.Resources:
            sheet_page.Resources["/XObject"] = Dictionary()
        sheet_page.Resources["/XObject"][xobj_name] = xobj_ref

    content = (
        f"q\n{scale:.6f} 0 0 {scale:.6f} {offset_x:.6f} {offset_y:.6f} cm\n"
        f"/{xobj_name.lstrip('/')} Do\nQ\n"
    ).encode("ascii")

    existing = sheet_page.obj.get("/Contents")
    if existing is None:
        new_contents = Array([Pdf.make_stream(sheet_pdf, content)])
    elif isinstance(existing, Array):
        new_contents = Array([*existing, Pdf.make_stream(sheet_pdf, content)])
    else:
        new_contents = Array([existing, Pdf.make_stream(sheet_pdf, content)])
    sheet_page.obj["/Contents"] = new_contents


def _build_sheet_side(
    sheet_pdf: Pdf,
    source_xobjects: dict,
    left_page: int,
    right_page: int,
    page_w: float,
    page_h: float,
    gutter_pt: float,
    gap_pt: float,
    rotate_180: bool,
) -> None:
    sheet_w = page_w * 2 + gutter_pt + gap_pt
    sheet_h = page_h

    sheet_pdf.add_blank_page(page_size=(sheet_w, sheet_h))
    sheet_page = sheet_pdf.pages[-1]

    left_x = 0.0
    right_x = page_w + gutter_pt + gap_pt

    _place_page(sheet_pdf, sheet_page, source_xobjects, left_page, left_x, 0.0, page_w, page_h)
    _place_page(sheet_pdf, sheet_page, source_xobjects, right_page, right_x, 0.0, page_w, page_h)

    if rotate_180:
        cx, cy = sheet_w / 2.0, sheet_h / 2.0
        transform = Transform(dx=0.0, dy=0.0, rotation_deg=180.0, pivot_x=cx, pivot_y=cy)
        matrix = transform.matrix()
        a, b, c, d, e, f = matrix
        prefix = f"q\n{a:.6f} {b:.6f} {c:.6f} {d:.6f} {e:.6f} {f:.6f} cm\n".encode("ascii")
        suffix = b"\nQ\n"
        existing = sheet_page.obj["/Contents"]
        wrapped = Array([Pdf.make_stream(sheet_pdf, prefix), *existing, Pdf.make_stream(sheet_pdf, suffix)])
        sheet_page.obj["/Contents"] = wrapped


def build_booklet(input_path: str, output_path: str, options: BookletOptions) -> BookletResult:
    """Build a saddle-stitch booklet-imposed PDF from input_path.

    Auto duplex modes produce a single output_path with sheets
    interleaved front, back, front, back, ... . Manual modes produce
    two files: output_path with "_fronts" inserted before the
    extension, and another with "_backs".
    """
    warnings: List[str] = []
    source = pikepdf.open(input_path)
    try:
        page_count = len(source.pages)
        if page_count == 0:
            return BookletResult(0, 0, [], ["Source PDF has no pages."])

        page_w, page_h = _reference_page_size(source)
        for i, page in enumerate(source.pages):
            box = page.mediabox
            w, h = float(box[2]) - float(box[0]), float(box[3]) - float(box[1])
            if abs(w - page_w) > 1.0 or abs(h - page_h) > 1.0:
                warnings.append(
                    f"Page {i + 1} ({w:.0f}x{h:.0f}pt) differs from the reference size "
                    f"({page_w:.0f}x{page_h:.0f}pt) and will be centered, not stretched."
                )

        sheets = compute_sheet_pages(page_count)
        gutter_pt = mm_to_points(options.gutter_mm)
        gap_pt = mm_to_points(options.sheet_gap_mm)
        short_edge = _is_short_edge(options.duplex_mode)

        fronts_pdf = pikepdf.new()
        backs_pdf = pikepdf.new()

        # Embed every source page as a reusable Form XObject once,
        # then reference it from as many sheet slots as needed
        # (a page only ever appears in exactly one slot for a normal
        # booklet, but sharing the embedding logic keeps this simple).
        front_xobjects = {}
        back_xobjects = {}
        for i, page in enumerate(source.pages):
            page_num = i + 1
            box = page.mediabox
            w, h = float(box[2]) - float(box[0]), float(box[3]) - float(box[1])
            fx = page.as_form_xobject()
            front_xobjects[page_num] = (f"/P{page_num}", fronts_pdf.copy_foreign(fx), w, h)
            bx = page.as_form_xobject()
            back_xobjects[page_num] = (f"/P{page_num}", backs_pdf.copy_foreign(bx), w, h)

        for sheet in sheets:
            _build_sheet_side(
                fronts_pdf, front_xobjects, sheet.front_left, sheet.front_right,
                page_w, page_h, gutter_pt, gap_pt, rotate_180=False,
            )
            _build_sheet_side(
                backs_pdf, back_xobjects, sheet.back_left, sheet.back_right,
                page_w, page_h, gutter_pt, gap_pt, rotate_180=short_edge,
            )

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        output_paths: List[str] = []

        if _is_auto(options.duplex_mode):
            combined = pikepdf.new()
            for i in range(len(sheets)):
                combined.pages.append(fronts_pdf.pages[i])
                combined.pages.append(backs_pdf.pages[i])
            combined.save(output_path)
            output_paths.append(output_path)
        else:
            base, ext = os.path.splitext(output_path)
            fronts_path = f"{base}_fronts{ext}"
            backs_path = f"{base}_backs{ext}"
            fronts_pdf.save(fronts_path)
            backs_pdf.save(backs_path)
            output_paths.extend([fronts_path, backs_path])
            warnings.append(
                "Manual duplex: print the fronts file first, then physically flip the "
                "printed stack and feed it back through for the backs file. Do a short "
                "test print (e.g. 8 pages) first to confirm your printer's manual-feed "
                "order matches -- if pages come out reversed, print the backs file with "
                "your PDF reader's own 'reverse pages' print option."
            )

        return BookletResult(
            sheet_count=len(sheets),
            page_count=page_count,
            output_paths=output_paths,
            warnings=warnings,
        )
    finally:
        source.close()
