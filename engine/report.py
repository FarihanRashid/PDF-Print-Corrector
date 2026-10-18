"""
report.py

Builds the plain-text conversion_report.txt summary written after a
batch run: for every file, what was requested vs what was actually
applied, whether Smart Translation adjusted anything, and any
warnings. Kept separate from batch_worker.py so the report format can
change without touching threading logic, and so it's independently
testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from engine.pdf_engine import TranslationOptions, TranslationResult
from utils.constants import APP_NAME


@dataclass
class JobRecord:
    """One file's outcome, collected during a batch run for reporting."""

    input_path: str
    output_path: Optional[str]
    result: Optional[TranslationResult]
    error: Optional[str] = None


def _summarize_applied(options: TranslationOptions, result: TranslationResult) -> str:
    """One representative applied-values line for a file.

    Smart Translation can apply different values per page, which
    would be unreadable to dump in full for a 1000-page document. If
    every page ended up with the same applied values (the common
    case), show that. Otherwise show the range and how many pages
    were touched.
    """
    if options.translation_mode != "smart" or not result.page_reports:
        return (
            f"  X = {options.horizontal_offset_mm:+.2f} mm\n"
            f"  Y = {options.vertical_offset_mm:+.2f} mm\n"
            f"  Rotation = {options.rotation_degrees:.2f}\u00b0\n"
            f"  Scale = {options.scale_percent:.1f}%"
        )

    adjusted = [p for p in result.page_reports if p.was_adjusted]
    if not adjusted:
        return (
            f"  X = {options.horizontal_offset_mm:+.2f} mm\n"
            f"  Y = {options.vertical_offset_mm:+.2f} mm\n"
            f"  Rotation = {options.rotation_degrees:.2f}\u00b0\n"
            f"  Scale = {options.scale_percent:.1f}%\n"
            f"  (no pages required adjustment)"
        )

    dx_values = {round(p.applied_dx_mm, 3) for p in result.page_reports}
    dy_values = {round(p.applied_dy_mm, 3) for p in result.page_reports}
    scale_values = {round(p.applied_scale_percent, 2) for p in result.page_reports}

    if len(dx_values) == 1 and len(dy_values) == 1 and len(scale_values) == 1:
        p = result.page_reports[0]
        return (
            f"  X = {p.applied_dx_mm:+.2f} mm\n"
            f"  Y = {p.applied_dy_mm:+.2f} mm\n"
            f"  Rotation = {options.rotation_degrees:.2f}\u00b0\n"
            f"  Scale = {p.applied_scale_percent:.1f}%\n"
            f"  ({len(adjusted)} of {len(result.page_reports)} page(s) were adjusted)"
        )

    # Values genuinely varied per page -- show the range rather than
    # picking one arbitrarily.
    return (
        f"  X = {min(dx_values):+.2f} to {max(dx_values):+.2f} mm (varies by page)\n"
        f"  Y = {min(dy_values):+.2f} to {max(dy_values):+.2f} mm (varies by page)\n"
        f"  Rotation = {options.rotation_degrees:.2f}\u00b0\n"
        f"  Scale = {min(scale_values):.1f}% to {max(scale_values):.1f}%\n"
        f"  ({len(adjusted)} of {len(result.page_reports)} page(s) were adjusted)"
    )


def build_report_text(
    jobs: List["JobRecord"],
    options: TranslationOptions,
) -> str:
    lines = [
        f"{APP_NAME} - Conversion Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Translation Mode: {'Smart' if options.translation_mode == 'smart' else 'Strict'}",
        "=" * 60,
        "",
    ]

    for job in jobs:
        lines.append(f"File: {os.path.basename(job.input_path)}")
        if job.error:
            lines.append(f"  FAILED: {job.error}")
            lines.append("")
            continue

        result = job.result
        lines.append(f"  Output: {os.path.basename(job.output_path) if job.output_path else '(not written)'}")
        lines.append(f"  Pages: {result.page_count if result else '?'}")
        lines.append("")
        lines.append("  Requested:")
        lines.append(f"    X = {options.horizontal_offset_mm:+.2f} mm")
        lines.append(f"    Y = {options.vertical_offset_mm:+.2f} mm")
        lines.append(f"    Rotation = {options.rotation_degrees:.2f}\u00b0")
        lines.append(f"    Scale = {options.scale_percent:.1f}%")
        lines.append("")
        lines.append("  Applied:")
        if result:
            for line in _summarize_applied(options, result).splitlines():
                lines.append(f"  {line}")
        lines.append("")
        smart_used = bool(result and result.smart_translation_used)
        lines.append(f"  Smart Translation: {'YES' if smart_used else 'NO'}")

        warnings = result.warnings if result else []
        if warnings:
            lines.append("  Warnings:")
            for w in warnings:
                for i, wline in enumerate(w.splitlines()):
                    prefix = "    - " if i == 0 else "      "
                    lines.append(f"{prefix}{wline}")
        else:
            lines.append("  Warnings: None")

        lines.append("")
        lines.append("-" * 60)
        lines.append("")

    return "\n".join(lines)


def write_report(path: str, jobs: List["JobRecord"], options: TranslationOptions) -> Optional[str]:
    """Write the report; returns the path on success, None on failure
    (best-effort, matching the app's other file-write error handling)."""
    try:
        text = build_report_text(jobs, options)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path
    except OSError:
        return None
