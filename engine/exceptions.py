"""
exceptions.py

Custom exception hierarchy for the PDF engine. The GUI layer catches
these and shows friendly dialogs instead of letting the app crash, per
the "never crash" requirement.
"""

from __future__ import annotations


class PDFEngineError(Exception):
    """Base class for all engine-raised errors."""


class EncryptedPDFError(PDFEngineError):
    """Raised when a PDF is encrypted / password protected."""


class CorruptPDFError(PDFEngineError):
    """Raised when a PDF cannot be parsed at all."""


class UnsupportedPDFError(PDFEngineError):
    """Raised when a PDF uses a feature the engine cannot safely handle."""


class OutputWriteError(PDFEngineError):
    """Raised when the corrected PDF cannot be written to disk."""
