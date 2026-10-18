"""
pdf_engine.py

The heart of the application. Applies an exact horizontal/vertical
offset (and optional rotation) to every page of a PDF WITHOUT
rasterizing, re-encoding, or otherwise touching page content.

Technique
---------
Every PDF page's visible content is produced by executing a content
stream against a coordinate system. To shift that content, we do not
touch a single existing operator -- we simply wrap the *existing*,
byte-for-byte-unchanged content stream with:

    q
    a b c d e f cm
    <...original content, untouched...>
    Q

`cm` (concatenate matrix) is the standard PDF operator for applying an
affine transform to everything that follows, and `q`/`Q` save/restore
graphics state so the transform cannot leak into anything else. This
is exactly how professional PDF tools implement lossless page
transforms: fonts, images, vector paths, transparency groups, and
colour spaces are copied verbatim, because we never decode them.

Annotations (links, form field widgets, highlights, etc.) are NOT
part of the content stream and therefore are not moved by the `cm`
trick -- they live in their own coordinate entries (`/Rect`,
`/QuadPoints`, ...). Those are translated/rotated explicitly using the
same matrix so links and markup stay aligned with the shifted content.

Page size (`/MediaBox`, `/CropBox`, ...), `/Rotate`, fonts, images,
metadata, and the document outline are left completely untouched
unless the caller explicitly asks for metadata/bookmarks/etc. to be
stripped via the options below.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pikepdf
from pikepdf import Array, Name, Pdf

from engine.exceptions import (
    CorruptPDFError,
    EncryptedPDFError,
    OutputWriteError,
    UnsupportedPDFError,
)
from engine.geometry import (
    Transform,
    mm_to_points,
    normalize_landscape_transform,
    points_to_mm,
    rotate_vector,
    transform_point_list,
    transform_quad_points,
    transform_rect,
)
from engine.content_bounds import detect_content_bbox
from engine.smart_translate import SmartTranslateSettings, SmartTranslateResult, solve as solve_smart_translate

# Progress callback signature: (current_page, total_pages) -> None
ProgressCallback = Optional[Callable[[int, int], None]]


@dataclass
class TranslationOptions:
    """All user-configurable knobs for a single conversion job."""

    horizontal_offset_mm: float = 4.0
    vertical_offset_mm: float = 5.0
    rotation_degrees: float = 0.0
    scale_percent: float = 100.0

    preserve_metadata: bool = True
    preserve_bookmarks: bool = True
    preserve_hyperlinks: bool = True
    preserve_annotations: bool = True
    preserve_form_fields: bool = True

    # When True, the horizontal/vertical offset is treated as calibrated
    # in *physical paper* space (e.g. measured from a portrait test
    # print) and is automatically re-oriented for any page that renders
    # landscape, so the printed shift lands in the same physical spot
    # without the user having to manually flip signs per file.
    # landscape_direction controls which way the offset vector is
    # rotated: "cw" (clockwise) matches the common case where a
    # printer/driver rotates landscape content 90 degrees clockwise
    # relative to portrait before feeding it through the same physical
    # path. If a job comes out shifted the wrong way, flip to "ccw".
    landscape_compensation: bool = False
    landscape_direction: str = "cw"  # "cw" or "ccw"

    # Distinct from landscape_compensation above: this actually
    # ROTATES landscape page content and reshapes the MediaBox so the
    # page becomes portrait-shaped, rather than just re-orienting the
    # offset vector. Useful to visually confirm a mixed-orientation
    # document will print consistently, and as a prerequisite for
    # booklet imposition (which assumes uniform portrait pages).
    normalize_landscape_to_portrait: bool = False
    normalize_direction: str = "cw"  # "cw" or "ccw"

    # "strict" applies horizontal/vertical/rotation/scale exactly as
    # requested, even if that clips content off the page. "smart"
    # analyses each page's actual content bounds first and reduces
    # translation (and, if needed, scale) to the smallest extent that
    # avoids clipping -- see engine/smart_translate.py.
    translation_mode: str = "strict"  # "strict" or "smart" -- GUI opts in explicitly
    smart_settings: SmartTranslateSettings = field(default_factory=SmartTranslateSettings)

    password: Optional[str] = None


@dataclass
class PageReport:
    page_index: int
    requested_dx_mm: float
    requested_dy_mm: float
    requested_scale_percent: float
    applied_dx_mm: float
    applied_dy_mm: float
    applied_scale_percent: float
    was_adjusted: bool
    fully_avoided_clipping: bool
    note: Optional[str] = None


@dataclass
class TranslationResult:
    input_path: str
    output_path: str
    page_count: int
    warnings: List[str] = field(default_factory=list)
    smart_translation_used: bool = False
    page_reports: List[PageReport] = field(default_factory=list)


# Annotation subtypes whose geometry keys we know how to move safely.
_RECT_ONLY_SAFE = True  # /Rect exists on virtually every annotation subtype.


def _open_pdf(path: str, password: Optional[str]) -> Pdf:
    try:
        if password:
            return pikepdf.open(path, password=password)
        return pikepdf.open(path)
    except pikepdf.PasswordError as exc:
        raise EncryptedPDFError(
            f"'{os.path.basename(path)}' is password protected."
        ) from exc
    except pikepdf.PdfError as exc:
        raise CorruptPDFError(
            f"'{os.path.basename(path)}' could not be read (corrupt or invalid PDF)."
        ) from exc
    except FileNotFoundError as exc:
        raise CorruptPDFError(f"File not found: {path}") from exc


def _page_mediabox(page: pikepdf.Object) -> List[float]:
    box = page.MediaBox
    return [float(box[0]), float(box[1]), float(box[2]), float(box[3])]


def _effective_page_box(page: pikepdf.Object) -> List[float]:
    """The box that determines a page's effective visible/printed
    shape: CropBox if present, otherwise MediaBox.

    Many real-world PDFs -- scanned documents, InDesign/Illustrator
    output, print-shop production files -- set a CropBox distinct
    from MediaBox (e.g. a MediaBox with bleed plus a smaller, often
    differently-oriented CropBox marking what's actually meant to be
    seen/printed). Landscape detection based on MediaBox alone
    silently misses these pages: a page can be portrait-shaped by
    MediaBox but landscape by CropBox, or vice versa. Viewers and
    printers honour CropBox over MediaBox when both are present, so
    detection here does the same.
    """
    if "/CropBox" in page.obj:
        box = page.obj["/CropBox"]
        return [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
    return _page_mediabox(page)


def _wrap_content_stream(pdf: Pdf, page: pikepdf.Object, matrix) -> None:
    a, b, c, d, e, f = matrix
    prefix = f"q\n{a:.6f} {b:.6f} {c:.6f} {d:.6f} {e:.6f} {f:.6f} cm\n".encode("ascii")
    suffix = b"\nQ\n"

    prefix_stream = Pdf.make_stream(pdf, prefix)
    suffix_stream = Pdf.make_stream(pdf, suffix)

    existing = page.obj.get("/Contents")
    if existing is None:
        existing_list: List[pikepdf.Object] = []
    elif isinstance(existing, Array):
        existing_list = list(existing)
    else:
        existing_list = [existing]

    page.obj["/Contents"] = Array([prefix_stream, *existing_list, suffix_stream])


def _translate_annotations(page: pikepdf.Object, matrix, warnings: List[str]) -> None:
    if "/Annots" not in page.obj:
        return
    for annot in page.obj["/Annots"]:
        try:
            if "/Rect" in annot:
                rect = [float(v) for v in annot["/Rect"]]
                annot["/Rect"] = transform_rect(matrix, rect)
            if "/QuadPoints" in annot:
                quad = [float(v) for v in annot["/QuadPoints"]]
                annot["/QuadPoints"] = transform_quad_points(matrix, quad)
            if "/Vertices" in annot:
                verts = [float(v) for v in annot["/Vertices"]]
                annot["/Vertices"] = transform_point_list(matrix, verts)
            if "/L" in annot and annot.get("/Subtype") == Name("/Line"):
                line = [float(v) for v in annot["/L"]]
                annot["/L"] = transform_point_list(matrix, line)
        except Exception:  # noqa: BLE001 - one bad annotation must not abort the job
            warnings.append("One annotation could not be repositioned and was left as-is.")


def _strip_metadata(pdf: Pdf) -> None:
    with pdf.open_metadata() as meta:
        meta.clear()
    if pdf.docinfo is not None:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]


def _strip_bookmarks(pdf: Pdf) -> None:
    root = pdf.Root
    if "/Outlines" in root:
        del root["/Outlines"]


def _strip_hyperlinks(pdf: Pdf) -> None:
    for page in pdf.pages:
        if "/Annots" not in page.obj:
            continue
        kept = [a for a in page.obj["/Annots"] if a.get("/Subtype") != Name("/Link")]
        page.obj["/Annots"] = Array(kept)


def _strip_form_fields(pdf: Pdf) -> None:
    root = pdf.Root
    if "/AcroForm" in root:
        del root["/AcroForm"]
    for page in pdf.pages:
        if "/Annots" not in page.obj:
            continue
        kept = [a for a in page.obj["/Annots"] if a.get("/Subtype") != Name("/Widget")]
        page.obj["/Annots"] = Array(kept)


def _strip_all_annotations(pdf: Pdf) -> None:
    for page in pdf.pages:
        if "/Annots" in page.obj:
            del page.obj["/Annots"]


def _is_effectively_landscape(mediabox: List[float], rotate_attr: int) -> bool:
    """Whether a page renders landscape once its own /Rotate is applied.

    Covers both authoring conventions: a MediaBox that is itself wider
    than tall, and a portrait MediaBox combined with a 90/270 /Rotate
    that makes it render sideways.
    """
    width = mediabox[2] - mediabox[0]
    height = mediabox[3] - mediabox[1]
    if rotate_attr % 360 in (90, 270):
        width, height = height, width
    return width > height


def _try_open_fitz(path: str, password: Optional[str]):
    """Best-effort PyMuPDF open for Smart Translation's content analysis.

    Returns None on any failure -- this is purely an analysis aid, and
    the caller degrades gracefully to Strict-equivalent behaviour with
    a single warning rather than failing the whole conversion over it.
    """
    try:
        import fitz  # local import: only needed when Smart Translation runs

        doc = fitz.open(path)
        if doc.is_encrypted and password:
            doc.authenticate(password)
        if doc.is_encrypted:
            doc.close()
            return None
        return doc
    except Exception:  # noqa: BLE001
        return None


def translate_pdf(
    input_path: str,
    output_path: str,
    options: TranslationOptions,
    progress_cb: ProgressCallback = None,
) -> TranslationResult:
    """Apply the configured offset/rotation/scale to every page and save.

    Raises EncryptedPDFError, CorruptPDFError, UnsupportedPDFError, or
    OutputWriteError on failure; callers (the GUI worker thread) are
    expected to catch these and surface a friendly message.
    """
    warnings: List[str] = []
    page_reports: List[PageReport] = []
    dx = mm_to_points(options.horizontal_offset_mm)
    dy = mm_to_points(options.vertical_offset_mm)
    scale = options.scale_percent / 100.0

    smart_mode = options.translation_mode == "smart" and options.smart_settings.prevent_clipping
    fitz_doc = None
    if smart_mode:
        fitz_doc = _try_open_fitz(input_path, options.password)
        if fitz_doc is None:
            smart_mode = False
            warnings.append(
                "Smart Translation could not analyse this file's content; "
                "applied requested values as-is (Strict behaviour) for all pages."
            )

    pdf = _open_pdf(input_path, options.password)
    try:
        total = len(pdf.pages)
        if total == 0:
            raise UnsupportedPDFError(f"'{os.path.basename(input_path)}' has no pages.")

        if options.normalize_landscape_to_portrait and total > 0:
            landscape_count = 0
            for page in pdf.pages:
                check_box = _effective_page_box(page)
                check_rotate = int(page.obj.get("/Rotate", 0))
                if _is_effectively_landscape(check_box, check_rotate):
                    landscape_count += 1
            if landscape_count == total:
                warnings.append(
                    "Every page in this file is already landscape-shaped. Normalize to "
                    "Portrait will force-rotate all of them -- if this file was already "
                    "produced as a 2-Up or Booklet layout (where landscape sheets are "
                    "intentional, holding pages side by side), this will badly distort "
                    "it. Turn off Normalize to Portrait if you're re-processing an "
                    "already-composed layout file."
                )

        try:
            for index, page in enumerate(pdf.pages):
                try:
                    box = _page_mediabox(page)
                    normalization_matrix = None

                    if options.normalize_landscape_to_portrait:
                        detection_box = _effective_page_box(page)
                        rotate_attr = int(page.obj.get("/Rotate", 0))
                        if _is_effectively_landscape(detection_box, rotate_attr):
                            if rotate_attr == 0:
                                # Common case: the page is genuinely
                                # landscape-shaped. Reshape the box and
                                # bake a 90-degree rotation into the
                                # content so it fills the new portrait
                                # frame exactly -- correct under any
                                # viewer/printer/RIP, not dependent on
                                # /Rotate being honoured correctly.
                                # Normalizing against detection_box
                                # (CropBox when present) rather than the
                                # raw MediaBox means the VISIBLE region
                                # is what actually gets fitted to
                                # portrait, not any extra bleed/margin
                                # a production PDF's MediaBox may carry.
                                ccw = options.normalize_direction == "ccw"
                                new_box, norm_transform = normalize_landscape_transform(detection_box, ccw)
                                normalization_matrix = norm_transform.matrix()
                                _wrap_content_stream(pdf, page, normalization_matrix)
                                if options.preserve_annotations:
                                    _translate_annotations(page, normalization_matrix, warnings)
                                page.obj["/MediaBox"] = Array(new_box)
                                if "/CropBox" in page.obj:
                                    del page.obj["/CropBox"]
                                box = new_box
                            else:
                                # Rarer case: already landscape via an
                                # existing /Rotate flag. A further
                                # 90-degree bump (spec-compliant,
                                # honoured by every compliant viewer/
                                # printer) restores portrait display
                                # without touching content or
                                # annotation coordinates, which are
                                # unaffected by /Rotate.
                                new_rotate = (rotate_attr + 90) % 360
                                page.obj["/Rotate"] = new_rotate
                                warnings.append(
                                    f"Page {index + 1} was already rotated ({rotate_attr}\u00b0); "
                                    f"normalized to portrait via the page rotation flag rather than "
                                    f"re-baked content."
                                )

                    cx = (box[0] + box[2]) / 2.0
                    cy = (box[1] + box[3]) / 2.0

                    page_dx, page_dy = dx, dy
                    if options.landscape_compensation:
                        compensation_box = _effective_page_box(page)
                        rotate_attr = int(page.obj.get("/Rotate", 0))
                        if _is_effectively_landscape(compensation_box, rotate_attr):
                            angle = 90.0 if options.landscape_direction == "ccw" else -90.0
                            page_dx, page_dy = rotate_vector(dx, dy, angle)

                    page_scale = scale

                    if smart_mode and fitz_doc is not None and index < fitz_doc.page_count:
                        content_bbox = detect_content_bbox(fitz_doc[index])
                        if content_bbox is not None and normalization_matrix is not None:
                            # The fitz-derived content bbox reflects the
                            # ORIGINAL (pre-normalization) page; move it
                            # into the same post-normalization space the
                            # rest of this loop now operates in.
                            content_bbox = tuple(transform_rect(normalization_matrix, list(content_bbox)))
                        result = solve_smart_translate(
                            content_bbox=content_bbox,
                            page_box=tuple(box),
                            requested_dx=page_dx,
                            requested_dy=page_dy,
                            rotation_deg=options.rotation_degrees,
                            requested_scale=page_scale,
                            settings=options.smart_settings,
                        )
                        page_report = PageReport(
                            page_index=index,
                            requested_dx_mm=points_to_mm(page_dx),
                            requested_dy_mm=points_to_mm(page_dy),
                            requested_scale_percent=page_scale * 100.0,
                            applied_dx_mm=points_to_mm(result.applied_dx),
                            applied_dy_mm=points_to_mm(result.applied_dy),
                            applied_scale_percent=result.applied_scale * 100.0,
                            was_adjusted=result.was_adjusted,
                            fully_avoided_clipping=result.fully_avoided_clipping,
                            note=result.note,
                        )
                        page_reports.append(page_report)
                        if not result.fully_avoided_clipping:
                            warnings.append(
                                f"Page {index + 1} could not be fully translated without clipping.\n"
                                f"Requested: X = {page_report.requested_dx_mm:+.2f} mm, "
                                f"Y = {page_report.requested_dy_mm:+.2f} mm, "
                                f"Scale = {page_report.requested_scale_percent:.1f}%\n"
                                f"Applied: X = {page_report.applied_dx_mm:+.2f} mm, "
                                f"Y = {page_report.applied_dy_mm:+.2f} mm, "
                                f"Scale = {page_report.applied_scale_percent:.1f}%"
                            )
                        page_dx, page_dy, page_scale = result.applied_dx, result.applied_dy, result.applied_scale

                    transform = Transform(
                        dx=page_dx, dy=page_dy, rotation_deg=options.rotation_degrees,
                        pivot_x=cx, pivot_y=cy, scale=page_scale,
                    )
                    matrix = transform.matrix()

                    _wrap_content_stream(pdf, page, matrix)

                    if options.preserve_annotations:
                        _translate_annotations(page, matrix, warnings)
                except Exception as exc:  # noqa: BLE001
                    raise UnsupportedPDFError(
                        f"Page {index + 1} of '{os.path.basename(input_path)}' uses an "
                        f"unsupported feature and could not be translated ({exc})."
                    ) from exc

                if progress_cb:
                    progress_cb(index + 1, total)
        finally:
            if fitz_doc is not None:
                fitz_doc.close()

        if not options.preserve_annotations:
            _strip_all_annotations(pdf)
        else:
            if not options.preserve_hyperlinks:
                _strip_hyperlinks(pdf)
            if not options.preserve_form_fields:
                _strip_form_fields(pdf)

        if not options.preserve_bookmarks:
            _strip_bookmarks(pdf)
        if not options.preserve_metadata:
            _strip_metadata(pdf)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        try:
            pdf.save(output_path)
        except Exception as exc:  # noqa: BLE001
            raise OutputWriteError(f"Could not write output file: {exc}") from exc

        return TranslationResult(
            input_path=input_path,
            output_path=output_path,
            page_count=total,
            warnings=warnings,
            smart_translation_used=smart_mode,
            page_reports=page_reports,
        )
    finally:
        pdf.close()
