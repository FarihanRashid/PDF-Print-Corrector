"""
nup.py

Plain "N pages per sheet" layout -- e.g. printing 2 or 4 slides per
handout page, in normal reading order (unlike booklet.py, which
reorders pages for saddle-stitch folding). This is the "smart" part
of it: for a given source page size, standard sheet size, and N, it
searches every sensible combination of

    - grid arrangement (e.g. for N=2: 2 columns x 1 row, or 1 column
      x 2 rows; for N=4: 2x2, or 4x1, or 1x4)
    - sheet orientation (portrait or landscape)
    - whether each source page is rotated 90 degrees within its cell

and picks whichever combination lets each source page render at the
LARGEST scale -- i.e. wastes the least paper. A portrait source page
placed 2-up often fits much better on a landscape sheet with pages
rotated 90 degrees than on an unrotated portrait sheet, depending on
the actual aspect ratios involved; this searches all of it rather
than assuming one fixed arrangement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class NupLayout:
    rows: int
    cols: int
    sheet_w: float
    sheet_h: float
    page_rotated: bool  # True if each source page is rotated 90 degrees within its cell
    scale: float        # the resulting per-page scale factor (higher = less wasted paper)


def _grid_factor_pairs(n: int) -> List[Tuple[int, int]]:
    """All (rows, cols) with rows*cols == n, rows,cols >= 1."""
    pairs = []
    for rows in range(1, n + 1):
        if n % rows == 0:
            pairs.append((rows, n // rows))
    return pairs


def compute_best_nup_layout(
    page_w: float, page_h: float, base_sheet_w: float, base_sheet_h: float, n: int
) -> NupLayout:
    """Search grid arrangement x sheet orientation x page rotation and
    return the combination that maximizes the per-page scale factor.

    base_sheet_w/h describes the physical paper in ONE orientation
    (e.g. A4 portrait); both that orientation and its landscape
    rotation are tried, since which one wastes less paper depends on
    the source page's own aspect ratio and the chosen grid shape.
    """
    best: NupLayout | None = None

    for rows, cols in _grid_factor_pairs(n):
        for sheet_w, sheet_h in ((base_sheet_w, base_sheet_h), (base_sheet_h, base_sheet_w)):
            cell_w = sheet_w / cols
            cell_h = sheet_h / rows
            for rotated in (False, True):
                eff_page_w, eff_page_h = (page_h, page_w) if rotated else (page_w, page_h)
                if eff_page_w <= 0 or eff_page_h <= 0:
                    continue
                scale = min(cell_w / eff_page_w, cell_h / eff_page_h)
                candidate = NupLayout(
                    rows=rows, cols=cols, sheet_w=sheet_w, sheet_h=sheet_h,
                    page_rotated=rotated, scale=scale,
                )
                if best is None or candidate.scale > best.scale:
                    best = candidate

    assert best is not None
    return best


@dataclass
class NupResult:
    sheet_count: int
    page_count: int
    output_paths: List[str]
    warnings: List[str]


def _is_single_file(duplex_mode: str) -> bool:
    # "single_*" = one interleaved file, for either a real auto-duplex
    # printer OR Acrobat/Reader's own "Manual Duplex" print checkbox
    # (which also consumes one interleaved file and handles the
    # flip-and-reprint prompting itself).
    # "twojob_*" = two completely separate files/print jobs, for a
    # fully manual workflow with no duplex-assist feature at all.
    return duplex_mode.startswith("single")


def _is_short_edge(duplex_mode: str) -> bool:
    return duplex_mode.endswith("short")


def build_nup(
    input_path: str, output_path: str, n: int, base_sheet_w: float, base_sheet_h: float,
    duplex_mode: str = "single_long",
) -> "NupResult":
    """Build an N-up PDF: n source pages per output sheet, in normal
    sequential reading order (1,2 on sheet 1; 3,4 on sheet 2; ...) --
    unlike booklet.py, which reorders pages for folding.

    Reuses the same lossless Form XObject placement technique as
    booklet.py: every source page is embedded once and referenced
    from its grid cell with a positioning matrix, so fonts, vectors,
    and images pass through untouched.

    duplex_mode controls both the output file structure and, for
    short-edge modes, bakes a 180-degree rotation into every other
    sheet so the physical flip direction you'll actually use lines up
    with correct reading order -- see the module docstring in
    layout_engine.py for the full reasoning; the rotation technique
    here is the exact same one verified there.
    """
    import math
    import os

    import pikepdf
    from pikepdf import Array, Dictionary, Pdf

    from engine.geometry import Transform

    source = pikepdf.open(input_path)
    try:
        page_count = len(source.pages)
        if page_count == 0:
            return NupResult(0, 0, [], ["Source PDF has no pages."])

        box = source.pages[0].mediabox
        page_w = float(box[2]) - float(box[0])
        page_h = float(box[3]) - float(box[1])

        layout = compute_best_nup_layout(page_w, page_h, base_sheet_w, base_sheet_h, n)

        warnings: List[str] = []
        for i, page in enumerate(source.pages):
            b = page.mediabox
            w, h = float(b[2]) - float(b[0]), float(b[3]) - float(b[1])
            if abs(w - page_w) > 1.0 or abs(h - page_h) > 1.0:
                warnings.append(
                    f"Page {i + 1} ({w:.0f}x{h:.0f}pt) differs from the reference size; "
                    f"it will be centered in its cell at its own best-fit scale."
                )

        def embed_pages_into(target_pdf) -> dict:
            """Embed every source page as a Form XObject IN target_pdf's
            own object space. Each output document needs its own copy --
            an XObject reference only means something within the
            document that owns it, so this must run once per document
            actually rendered into (never reused across documents)."""
            result = {}
            for i, page in enumerate(source.pages):
                b = page.mediabox
                w, h = float(b[2]) - float(b[0]), float(b[3]) - float(b[1])
                fx = page.as_form_xobject()
                result[i] = (f"/P{i}", target_pdf.copy_foreign(fx), w, h)
            return result

        cos90, sin90 = math.cos(math.radians(90)), math.sin(math.radians(90))
        short_edge = _is_short_edge(duplex_mode)

        def render_sheet(target_pdf, xobjects: dict, sheet_index: int) -> None:
            target_pdf.add_blank_page(page_size=(layout.sheet_w, layout.sheet_h))
            sheet_page = target_pdf.pages[-1]

            for cell_index in range(n):
                page_index = sheet_index * n + cell_index
                if page_index >= page_count:
                    break
                row = cell_index // layout.cols
                col = cell_index % layout.cols
                cell_w = layout.sheet_w / layout.cols
                cell_h = layout.sheet_h / layout.rows
                cell_x = col * cell_w
                cell_y = layout.sheet_h - (row + 1) * cell_h

                xobj_name, xobj_ref, src_w, src_h = xobjects[page_index]
                eff_w, eff_h = (src_h, src_w) if layout.page_rotated else (src_w, src_h)
                draw_w, draw_h = eff_w * layout.scale, eff_h * layout.scale
                offset_x = cell_x + (cell_w - draw_w) / 2.0
                offset_y = cell_y + (cell_h - draw_h) / 2.0

                if "/XObject" not in sheet_page.Resources:
                    sheet_page.Resources["/XObject"] = Dictionary()
                sheet_page.Resources["/XObject"][xobj_name] = xobj_ref

                if layout.page_rotated:
                    a, b = layout.scale * cos90, layout.scale * sin90
                    c, d = -layout.scale * sin90, layout.scale * cos90
                    e = offset_x + src_h * layout.scale
                    f = offset_y
                else:
                    a, b, c, d = layout.scale, 0.0, 0.0, layout.scale
                    e, f = offset_x, offset_y

                content = (
                    f"q\n{a:.6f} {b:.6f} {c:.6f} {d:.6f} {e:.6f} {f:.6f} cm\n"
                    f"/{xobj_name.lstrip('/')} Do\nQ\n"
                ).encode("ascii")
                existing = sheet_page.obj.get("/Contents")
                if existing is None:
                    sheet_page.obj["/Contents"] = Array([Pdf.make_stream(target_pdf, content)])
                else:
                    sheet_page.obj["/Contents"] = Array([*existing, Pdf.make_stream(target_pdf, content)])

            if short_edge and sheet_index % 2 == 1:
                # Every other sheet is a "back" side under simple
                # front/back/front/back sequencing -- rotate it 180
                # degrees, the same verified compensation used for
                # booklet short-edge duplex.
                cx, cy = layout.sheet_w / 2.0, layout.sheet_h / 2.0
                t = Transform(dx=0.0, dy=0.0, rotation_deg=180.0, pivot_x=cx, pivot_y=cy)
                ra, rb, rc, rd, re, rf = t.matrix()
                prefix = f"q\n{ra:.6f} {rb:.6f} {rc:.6f} {rd:.6f} {re:.6f} {rf:.6f} cm\n".encode("ascii")
                suffix = b"\nQ\n"
                existing = sheet_page.obj["/Contents"]
                sheet_page.obj["/Contents"] = Array(
                    [Pdf.make_stream(target_pdf, prefix), *existing, Pdf.make_stream(target_pdf, suffix)]
                )

        sheets_needed = (page_count + n - 1) // n
        sheet_count = sheets_needed

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        output_paths: List[str] = []

        if _is_single_file(duplex_mode):
            out_pdf = pikepdf.new()
            xobjects = embed_pages_into(out_pdf)
            for sheet_index in range(sheets_needed):
                render_sheet(out_pdf, xobjects, sheet_index)
            out_pdf.save(output_path)
            output_paths.append(output_path)
        else:
            fronts_pdf = pikepdf.new()
            backs_pdf = pikepdf.new()
            fronts_xobjects = embed_pages_into(fronts_pdf)
            backs_xobjects = embed_pages_into(backs_pdf)
            for sheet_index in range(sheets_needed):
                if sheet_index % 2 == 0:
                    render_sheet(fronts_pdf, fronts_xobjects, sheet_index)
                else:
                    render_sheet(backs_pdf, backs_xobjects, sheet_index)
            base, ext = os.path.splitext(output_path)
            fronts_path = f"{base}_fronts{ext}"
            backs_path = f"{base}_backs{ext}"
            fronts_pdf.save(fronts_path)
            backs_pdf.save(backs_path)
            output_paths.extend([fronts_path, backs_path])
            warnings.append(
                "Two-file manual mode: print the fronts file, physically flip the "
                "printed stack by hand, then print the backs file. Do a short test "
                "print first to confirm your printer's manual-feed order."
            )

        return NupResult(sheet_count=sheet_count, page_count=page_count, output_paths=output_paths, warnings=warnings)
    finally:
        source.close()
