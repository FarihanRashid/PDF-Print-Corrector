"""
batch_worker.py

QThread-based worker that converts a queue of PDFs without blocking the
UI. Emits Qt signals so the GUI can update per-file progress, overall
progress, and final status without any polling.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from engine.exceptions import PDFEngineError
from engine.pdf_engine import TranslationOptions, translate_pdf
from engine.report import JobRecord, write_report
from utils.constants import OUTPUT_SUFFIX


@dataclass
class QueueItem:
    input_path: str
    output_path: str
    base_dir: str  # root folder the item was dropped from, for structure preservation
    page_count: int = 0
    status: str = "Queued"
    error: Optional[str] = None
    # The intended output path BEFORE duplicate-collision resolution.
    # Used to tell "the user changed a filename-affecting setting" apart
    # from "this item's own previous output now exists on disk" -- only
    # the former should trigger re-resolving to a new _1/_2/... path.
    base_output_path: Optional[str] = None


def build_output_path(
    input_path: str,
    output_folder: Optional[str],
    base_dir: Optional[str],
    keep_original_filename: bool,
    add_suffix: bool,
) -> str:
    """Compute where a converted file should be written.

    If output_folder is None, the file is written alongside the input.
    If base_dir is provided (batch/folder mode) the relative folder
    structure under base_dir is preserved inside output_folder.
    """
    directory, filename = os.path.split(input_path)
    name, ext = os.path.splitext(filename)

    if add_suffix and not keep_original_filename:
        name = f"{name}{OUTPUT_SUFFIX}"
    elif add_suffix and keep_original_filename:
        # "Keep original filename" wins visually, but we still must not
        # silently overwrite the source unless the user placed output
        # in a different folder. If same folder, force suffix to avoid
        # destructive overwrite.
        same_folder = output_folder is None or os.path.abspath(output_folder) == os.path.abspath(directory)
        if same_folder:
            name = f"{name}{OUTPUT_SUFFIX}"

    out_name = f"{name}{ext}"

    if output_folder is None:
        return os.path.join(directory, out_name)

    if base_dir:
        rel = os.path.relpath(directory, base_dir)
        if rel == ".":
            target_dir = output_folder
        else:
            target_dir = os.path.join(output_folder, rel)
    else:
        target_dir = output_folder

    return os.path.join(target_dir, out_name)


def resolve_unique_output_path(path: str, reserved: set) -> str:
    """Avoid overwriting an existing file (or another item in the same
    batch) by appending _1, _2, _3... before the extension.

    e.g. Math_corrected.pdf -> Math_corrected_1.pdf -> Math_corrected_2.pdf
    if a file by that name already exists on disk, or another queued
    item already resolved to the same path this run. `reserved` is
    shared across the whole batch by the caller so two queue items
    can never collide with each other, not just with what's already
    on disk.
    """
    if not os.path.exists(path) and path not in reserved:
        reserved.add(path)
        return path

    base, ext = os.path.splitext(path)
    counter = 1
    while True:
        candidate = f"{base}_{counter}{ext}"
        if not os.path.exists(candidate) and candidate not in reserved:
            reserved.add(candidate)
            return candidate
        counter += 1


class BatchWorker(QThread):
    """Runs one or more conversions sequentially on a background thread."""

    file_started = Signal(int)          # row index
    file_progress = Signal(int, int, int)  # row index, current page, total pages
    file_finished = Signal(int, str)    # row index, output_path
    file_failed = Signal(int, str)      # row index, error message
    file_warning = Signal(int, str)     # row index, warning message
    overall_progress = Signal(int, int)  # completed, total
    time_remaining = Signal(str)        # human readable ETA
    all_finished = Signal(int, int)     # succeeded, failed
    report_ready = Signal(str)          # path to conversion_report.txt (empty string if not written)

    def __init__(self, items: List[QueueItem], options: TranslationOptions, parent=None):
        super().__init__(parent)
        self._items = items
        self._options = options
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._items)
        succeeded = 0
        failed = 0
        start_time = time.monotonic()
        job_records: List[JobRecord] = []

        for index, item in enumerate(self._items):
            if self._cancelled:
                break

            self.file_started.emit(index)

            def progress_cb(current: int, total_pages: int, _index=index) -> None:
                self.file_progress.emit(_index, current, total_pages)

            try:
                result = translate_pdf(item.input_path, item.output_path, self._options, progress_cb)
                item.page_count = result.page_count
                item.status = "Done"
                succeeded += 1
                for warning in result.warnings:
                    self.file_warning.emit(index, warning)
                self.file_finished.emit(index, result.output_path)
                job_records.append(JobRecord(input_path=item.input_path, output_path=item.output_path, result=result))
            except PDFEngineError as exc:
                item.status = "Error"
                item.error = str(exc)
                failed += 1
                self.file_failed.emit(index, str(exc))
                job_records.append(
                    JobRecord(input_path=item.input_path, output_path=None, result=None, error=str(exc))
                )
            except Exception as exc:  # noqa: BLE001 - guarantee "never crash"
                item.status = "Error"
                item.error = f"Unexpected error: {exc}"
                failed += 1
                self.file_failed.emit(index, item.error)
                job_records.append(
                    JobRecord(input_path=item.input_path, output_path=None, result=None, error=item.error)
                )

            completed = index + 1
            self.overall_progress.emit(completed, total)

            elapsed = time.monotonic() - start_time
            if completed > 0 and completed < total:
                avg = elapsed / completed
                remaining = avg * (total - completed)
                self.time_remaining.emit(_format_eta(remaining))
            elif completed == total:
                self.time_remaining.emit("0s")

        report_path = self._write_report(job_records)
        self.report_ready.emit(report_path or "")
        self.all_finished.emit(succeeded, failed)

    def _write_report(self, job_records: List[JobRecord]) -> Optional[str]:
        if not job_records:
            return None
        # One report per run, placed next to the first successfully
        # written output (falling back to its parent folder even for
        # a failed-only run so there's still somewhere sensible to put
        # it) so it sits right where the person will actually look.
        target_dir = None
        for job in job_records:
            if job.output_path:
                target_dir = os.path.dirname(job.output_path)
                break
        if target_dir is None:
            target_dir = os.path.dirname(job_records[0].input_path)
        report_path = os.path.join(target_dir, "conversion_report.txt")
        return write_report(report_path, job_records, self._options)


def _format_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
