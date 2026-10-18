"""
content_bounds.py

Detects a PDF page's actual drawn-content bounding box -- as opposed
to its MediaBox/CropBox, which just describes the page's paper size.
Smart Translation needs this to know how much blank margin exists on
each side before deciding whether a requested shift would push
content off the page.

IMPORTANT: this reads structured geometry (text block positions,
vector path bounds, image placement rects) via PyMuPDF -- it does
NOT rasterize anything. Nothing here touches the conversion output;
engine/pdf_engine.py never imports this module for the actual save
path, only engine/smart_translate.py uses it, purely for analysis.
If PyMuPDF is unavailable or a page can't be analysed, callers get
None back and fall back to a safe default (see smart_translate.py).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

BBox = Tuple[float, float, float, float]  # (x0, y0, x1, y1) in PDF page space


def detect_content_bbox(fitz_page) -> Optional[BBox]:
    """Union of text, vector-drawing, and image bounding boxes on a page.

    Returns None if nothing could be determined (blank page, or an
    analysis error) -- callers should treat that as "unknown" and
    fall back conservatively rather than assume an empty page.

    A page with a non-zero /Rotate normally makes PyMuPDF report
    coordinates in the ROTATED "display" space, not the raw MediaBox
    space that pikepdf (and this app's whole transform pipeline)
    works in -- extraction and the page's own rotation would silently
    disagree about where things are. Temporarily zeroing the page's
    rotation via set_rotation(0) makes PyMuPDF report coordinates
    directly in raw MediaBox space instead, matching everything else
    in the engine; this was verified against a known reference
    rectangle rather than assumed.
    """
    try:
        original_rotation = fitz_page.rotation
        if original_rotation != 0:
            fitz_page.set_rotation(0)

        try:
            boxes: List[BBox] = []

            text_dict = fitz_page.get_text("dict")
            for block in text_dict.get("blocks", []):
                bbox = block.get("bbox")
                if bbox and _is_valid_bbox(bbox):
                    boxes.append(tuple(bbox))

            for drawing in fitz_page.get_drawings():
                rect = drawing.get("rect")
                if rect is not None:
                    bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                    if _is_valid_bbox(bbox):
                        boxes.append(bbox)

            for image_info in fitz_page.get_image_info():
                bbox = image_info.get("bbox")
                if bbox and _is_valid_bbox(bbox):
                    boxes.append(tuple(bbox))

            if not boxes:
                return None

            x0 = min(b[0] for b in boxes)
            y0 = min(b[1] for b in boxes)
            x1 = max(b[2] for b in boxes)
            y1 = max(b[3] for b in boxes)

            # PyMuPDF's text/drawing space has y increasing downward
            # from the top of the page; PDF page space (which the
            # rest of the engine works in) has y increasing upward
            # from the bottom. Flip here so callers always get
            # PDF-space coordinates. With rotation zeroed above,
            # page.rect now reflects the raw MediaBox height.
            page_height = fitz_page.rect.height
            pdf_y0 = page_height - y1
            pdf_y1 = page_height - y0

            return (x0, pdf_y0, x1, pdf_y1)
        finally:
            if original_rotation != 0:
                fitz_page.set_rotation(original_rotation)
    except Exception:  # noqa: BLE001 -- analysis is best-effort, never fatal
        return None


def _is_valid_bbox(bbox) -> bool:
    try:
        x0, y0, x1, y1 = bbox
        return x1 > x0 and y1 > y0
    except (TypeError, ValueError):
        return False
