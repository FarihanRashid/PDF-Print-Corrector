"""
booklet_worker.py

QThread wrapper that runs a layout job (booklet imposition or plain
2-up) per queued file off the GUI thread, matching how the main
conversion pipeline already avoids freezing the UI. Takes a plain
callable so it isn't tied to one specific layout engine function.
"""

from __future__ import annotations

from typing import Callable, List


from PySide6.QtCore import QThread, Signal


class BookletWorker(QThread):
    file_started = Signal(int)
    file_finished = Signal(int, list)   # row index, output_paths
    file_failed = Signal(int, str)      # row index, error message
    all_finished = Signal(int, int)     # succeeded, failed

    def __init__(
        self,
        input_paths: List[str],
        output_paths: List[str],
        job_fn: Callable[[str, str], List[str]],
        parent=None,
    ):
        """job_fn(input_path, output_path) -> list of actual output
        paths written (may differ from output_path, e.g. two-file
        modes append _fronts/_backs)."""
        super().__init__(parent)
        self._input_paths = input_paths
        self._output_paths = output_paths
        self._job_fn = job_fn

    def run(self) -> None:
        succeeded = 0
        failed = 0
        for index, (input_path, output_path) in enumerate(zip(self._input_paths, self._output_paths)):
            self.file_started.emit(index)
            try:
                actual_output_paths = self._job_fn(input_path, output_path)
                succeeded += 1
                self.file_finished.emit(index, actual_output_paths)
            except Exception as exc:  # noqa: BLE001 -- never crash
                failed += 1
                self.file_failed.emit(index, str(exc))
        self.all_finished.emit(succeeded, failed)
