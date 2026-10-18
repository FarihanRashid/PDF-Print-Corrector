"""
constants.py

Central location for application-wide constants. Keeping these in one
place avoids magic numbers/strings scattered across the codebase and
makes the app easy to re-brand or re-tune.
"""

from __future__ import annotations

APP_NAME = "PDF Print Corrector"
APP_VERSION = "1.0.0"
ORG_NAME = "PDFPrintCorrector"
ORG_DOMAIN = "pdfoffsetcorrector.local"

# 1 inch = 25.4 mm ; PDF user space is 72 units per inch (points).
POINTS_PER_MM = 72.0 / 25.4

DEFAULT_HORIZONTAL_OFFSET_MM = 4.0
DEFAULT_VERTICAL_OFFSET_MM = 5.0
DEFAULT_ROTATION_DEGREES = 0.0

MIN_OFFSET_MM = -1000.0
MAX_OFFSET_MM = 1000.0
MIN_ROTATION_DEG = -360.0
MAX_ROTATION_DEG = 360.0
MIN_SCALE_PERCENT = 90.0
MAX_SCALE_PERCENT = 105.0
DEFAULT_SCALE_PERCENT = 100.0

OUTPUT_SUFFIX = "_corrected"

SETTINGS_FILE_NAME = "settings.json"
PROFILES_FILE_NAME = "profiles.json"
LOG_FILE_NAME = "log.txt"

SUPPORTED_EXTENSIONS = (".pdf",)

# Qt object names used for QSS styling hooks.
OBJ_DROP_ZONE = "dropZone"
OBJ_PRIMARY_BUTTON = "primaryButton"
OBJ_SECONDARY_BUTTON = "secondaryButton"
OBJ_DANGER_BUTTON = "dangerButton"
OBJ_CARD = "card"
OBJ_STATUS_BAR_LABEL = "statusBarLabel"

STATUS_READY = "Ready"
STATUS_CONVERTING = "Converting..."
STATUS_FINISHED = "Finished"
STATUS_ERRORS = "Completed with errors"
