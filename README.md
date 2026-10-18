# PDF Print Corrector

A portable Windows desktop app that shifts (and optionally rotates) every
page of a PDF by an exact amount, to compensate for printer alignment
issues — **without ever rasterizing a page**. Text stays selectable,
vectors stay vectors, images stay at full quality, and everything else
(fonts, links, bookmarks, form fields, metadata, page size, page
rotation) is preserved.

## Download

Prebuilt `PDFPrintCorrector.exe` files are attached to each entry on
the [Releases](../../releases) page — no Python install required, just
download and run. Every push to `main` also builds automatically via
GitHub Actions (see the "Actions" tab) so you can grab the latest
build artifact even between releases.

## How it works

Every PDF page's appearance comes from a *content stream* of drawing
instructions. Instead of decoding and re-encoding that stream, the app
wraps it, byte-for-byte unchanged, with a single PDF `cm` (concatenate
matrix) operator:

```
q
1 0 0 1 <dx> <dy> cm
... your original, completely untouched page content ...
Q
```

This is the same technique professional PDF tools use for lossless
page transforms. Annotations (links, highlights, form widgets) live
outside the content stream, so their `/Rect` / `/QuadPoints` entries
are translated by the same matrix to stay aligned with the shifted
content. Page size, rotation flag, fonts, images, and metadata are
left completely alone unless you explicitly ask to strip them.

The default preset (used the first time you run the app) is:

- Horizontal offset: **+4.00 mm**
- Vertical offset: **+5.00 mm**
- Rotation: **0°**

## Using the app

1. Drag one or more PDFs — or an entire folder — onto the drop zone,
   or click **Browse**.
2. Adjust **Horizontal Offset**, **Vertical Offset**, and **Rotation**
   (or pick a saved **Printer Profile**).
3. Optionally click **Preview Before / After** to sanity-check the
   shift on the first queued file.
4. Click **Convert**. Progress shows per-file and overall, with an ETA.
5. Use **Open Output Folder** / **Open Output PDF** to jump straight
   to the result.

By default, converting `Math.pdf` produces `Math_corrected.pdf` next
to the original. Originals are never overwritten unless you disable
the `_corrected` suffix **and** point the output folder at the same
location as the input.

### Printer Profiles

Save named offset/rotation presets per printer (e.g. "Samsung
ML-1860": +4mm / +5mm / 0°). Click **Save as Profile...** next to the
profile dropdown to save your current offsets under a new name, or use
**Manage...** for full create/rename/delete/default control. The
profile you last had selected — and its offsets — are restored
automatically the next time you open the app.

### Landscape auto-compensation

Offsets are normally calibrated by printing a portrait test page and
measuring how far off it lands. If your PDF has landscape pages (or
portrait pages rotated 90°), that same physical offset needs to be
re-oriented to still line up correctly — otherwise you end up mentally
flipping signs by hand for every landscape file.

Check **Auto-compensate for landscape pages** and the app does that
re-orientation for you automatically, per page: portrait pages use
your offset as entered, landscape pages get it rotated 90° so the
printed shift lands in the same physical spot either way. If a
landscape page comes out shifted the wrong direction, flip the
**Clockwise / Counter-clockwise** dropdown next to it — the right
choice depends on how your specific printer driver rotates landscape
content — and re-check with **Preview Before / After**.

### Batch / folder mode

Dropping a folder converts every PDF inside it (recursively) and
mirrors the folder structure under your chosen output folder.

### Logging

Every conversion (and every failure) is appended to `log.txt`, next
to the executable, with input/output paths, offsets, and timing.

## Project layout

```
PDFPrintCorrector/
  main.py                  Entry point
  gui/                     PySide6 UI: main window, dialogs, widgets, theme
  engine/                  Core PDF engine: geometry, translation, batch worker
  profiles/                Printer profile persistence
  settings/                App settings persistence
  utils/                   Constants, logging, file discovery helpers
  resources/icons/         App icon
  requirements.txt
  build.bat                One-command Windows build
  PDFPrintCorrector.spec  PyInstaller build spec
  version_info.txt         Windows exe version resource
```

The codebase follows a simple MVC-style separation: `engine/` has no
knowledge of Qt at all (it's pure PDF logic you could reuse in a CLI
or a different UI), `gui/` handles presentation and wires
user actions to the engine via a background `QThread` worker so the
UI never freezes, and `settings/` / `profiles/` handle persistence.

## Building the portable .exe (Windows)

Requirements: Python 3.12+ on `PATH`.

```
build.bat
```

This creates a virtual environment, installs dependencies, and
produces `dist\PDFPrintCorrector.exe` — a single portable file with
no installer. Settings, profiles, and the log file are written next
to wherever you place the `.exe`.

## Running from source (development / any OS)

```
pip install -r requirements.txt
python main.py
```

## Notes on precision

- Offsets are entered in millimetres and converted to PDF points
  (1 mm = 72/25.4 pt) with full floating-point precision — no
  rounding to whole points.
- Rotation is applied about each page's own center, in the page's
  existing coordinate system, independent of the page's `/MediaBox`
  or `/Rotate` flag (both of which are preserved unchanged).
- The **Preserve vector quality** checkbox is permanently on: this
  application has no code path that rasterizes a page during
  conversion. The optional Preview dialog does rasterize a thumbnail
  purely for on-screen display — that never touches the saved output.

## License

MIT — see [LICENSE](LICENSE).
