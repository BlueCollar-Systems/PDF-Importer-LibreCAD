# -*- coding: utf-8 -*-
# gui.py -- Tkinter GUI for PDF to DXF conversion
# Copyright (c) 2024-2026 BlueCollar-Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
A straightforward, functional tkinter interface for the PDF-to-DXF
converter.  Uses *ttk* widgets for a modern look.
"""
from __future__ import annotations

import hashlib
import json
import os
import math
import re
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# BCS-ARCH-001: LC GUI uses Auto-only (strategy picked per page internally).
# CLI/batch retain vector | raster | hybrid for power users.
IMPORT_MODE_AUTO = "auto"

# Every requested representation is available in both GUI and CLI. Each item
# tries that type first; only item-specific, reported impossibility can advance
# it to the nearest verified visual representation.
TEXT_MODES = {
    "Text (may become outlines)": "text",
    "Labels (fallback reported)": "labels",
    "3D Text (LibreCAD is 2D)": "3d_text",
    "Glyphs (grouped outlines)": "glyphs",
    "Geometry (raw outlines)": "geometry",
    "Raster (exact item pixels)": "raster",
}

DXF_VERSIONS = ("R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018")
LIBRECAD_NOT_FOUND_TIP = (
    "LibreCAD was not found. Use Locate LibreCAD... to pick LibreCAD.exe once; "
    "it is remembered."
)
LIBRECAD_START_FAILED_TIP = (
    "LibreCAD could not be started. Use Locate LibreCAD... to pick the right "
    "LibreCAD.exe; it is remembered."
)
DEFAULT_TEXT_LABEL = next(label for label, mode in TEXT_MODES.items() if mode == "text")


@dataclass(frozen=True)
class ConversionOptions:
    """Validated values captured on the UI thread before conversion starts."""

    scale: float
    import_text: bool
    text_mode: str
    pages: tuple[int, ...] | None
    dxf_version: str
    launch_librecad: bool
    # The LibreCAD.exe picked with "Locate LibreCAD..." (None: normal lookup).
    librecad_executable: str | None = None


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_replace_reason(input_path: str, output_path: str) -> str | None:
    """Why converting would replace a drawing the user may want to keep.

    ``None`` when the output does not exist yet, or when it is the untouched
    result of importing this same PDF (Convert / Resume of that job stays one
    click). Otherwise a short plain reason that follows the file name, e.g.
    ``"EX101.dxf was made from a different PDF"``. The resume session sits next
    to the output exactly as dxf_import_engine names it.
    """
    try:
        output = Path(output_path).expanduser().resolve()
        if not output.is_file():
            return None
    except OSError:
        return None
    manifest_path = output.with_name(f"{output.stem}_resume") / "session.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "already exists"
    if not isinstance(manifest, dict):
        return "already exists"
    try:
        source_sha256 = _file_sha256(str(Path(input_path).expanduser().resolve()))
        output_sha256 = _file_sha256(str(output))
    except OSError:
        return "already exists"
    if manifest.get("source_sha256") != source_sha256:
        return "was made from a different PDF"
    assembled = manifest.get("assembled")
    if not isinstance(assembled, dict) or assembled.get("output_sha256") != output_sha256:
        return "was changed after it was imported"
    return None


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------
class Pdf2DxfApp(tk.Tk):
    """Main application window."""

    def __init__(self, handoff_path: str | None = None) -> None:
        super().__init__()
        # Set when LibreCAD's "Plugins > Import PDF (BlueCollar)..." started
        # this window: the finished DXF path is handed back to that LibreCAD.
        self._handoff_path = handoff_path
        self._handoff_delivered = False
        self.title(
            "PDF to DXF Converter - BlueCollar-Systems"
            + (" (for LibreCAD)" if handoff_path else "")
        )
        self.resizable(True, True)
        self.minsize(560, 620)

        # Try to set a reasonable starting size
        self.geometry("680x680")

        self._converting = False
        self._cancel_event = threading.Event()
        # "Locate LibreCAD..." choice, used even when it could not be saved.
        self._librecad_choice: str | None = None
        self._build_ui()
        if handoff_path:
            self.protocol("WM_DELETE_WINDOW", self._close_from_librecad_handoff)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # ---- Header label ----
        ttk.Label(
            frame,
            text="PDF to DXF Converter",
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, **pad)
        ttk.Label(
            frame,
            text="BlueCollar-Systems -- BUILT. NOT BOUGHT.",
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=8)
        tagline = ttk.Label(
            frame,
            text="Professional import — maximum fidelity; Auto picks vector, raster, or hybrid per page.",
            font=("Segoe UI", 9),
            wraplength=560,
        )
        tagline.grid(row=2, column=0, columnspan=3, sticky=tk.EW, padx=8, pady=(0, 4))

        # ---- Input file ----
        ttk.Label(frame, text="Input PDF:").grid(row=3, column=0, sticky=tk.W, **pad)
        self._var_input = tk.StringVar()
        self._ent_input = ttk.Entry(frame, textvariable=self._var_input, width=50)
        self._ent_input.grid(row=3, column=1, sticky=tk.EW, **pad)
        ttk.Button(frame, text="Browse...", command=self._browse_input).grid(
            row=3, column=2, **pad,
        )

        # ---- Output file ----
        ttk.Label(frame, text="Output DXF:").grid(row=4, column=0, sticky=tk.W, **pad)
        self._var_output = tk.StringVar()
        self._ent_output = ttk.Entry(frame, textvariable=self._var_output, width=50)
        self._ent_output.grid(row=4, column=1, sticky=tk.EW, **pad)
        ttk.Button(frame, text="Browse...", command=self._browse_output).grid(
            row=4, column=2, **pad,
        )

        # ---- Page range ----
        ttk.Label(frame, text="Pages:").grid(row=5, column=0, sticky=tk.W, **pad)
        pages_frame = ttk.Frame(frame)
        pages_frame.grid(row=5, column=1, columnspan=2, sticky=tk.EW, **pad)
        self._var_pages = tk.StringVar()
        ttk.Entry(pages_frame, textvariable=self._var_pages, width=16).pack(
            side=tk.LEFT,
        )
        ttk.Label(pages_frame, text="1,3-5; blank for all").pack(
            side=tk.LEFT, padx=(10, 0),
        )

        # ---- Scale ----
        ttk.Label(frame, text="Scale:").grid(row=6, column=0, sticky=tk.W, **pad)
        self._var_scale = tk.StringVar(value="1.0")
        scale_frame = ttk.Frame(frame)
        scale_frame.grid(row=6, column=1, columnspan=2, sticky=tk.EW, **pad)
        self._ent_scale = ttk.Entry(scale_frame, textvariable=self._var_scale, width=10)
        self._ent_scale.pack(side=tk.LEFT)
        ttk.Label(scale_frame, text="Multiplier: 1.0 = unchanged").pack(
            side=tk.LEFT, padx=(10, 0),
        )

        # ---- Requested text representation ----
        ttk.Label(frame, text="Text:").grid(row=7, column=0, sticky=tk.W, **pad)
        self._var_text_mode = tk.StringVar(value=DEFAULT_TEXT_LABEL)
        text_combo = ttk.Combobox(
            frame,
            textvariable=self._var_text_mode,
            values=list(TEXT_MODES.keys()),
            state="readonly",
            width=38,
        )
        text_combo.grid(row=7, column=1, columnspan=2, sticky=tk.EW, **pad)
        text_help = ttk.Label(
            frame,
            text=(
                "Visible Text normally becomes verified outlines because LibreCAD "
                "substitutes PDF fonts. Labels and 3D Text also have 2D host limits. "
                "Any fallback or unverified item is listed in the log and report."
            ),
            wraplength=620,
        )
        text_help.grid(row=8, column=0, columnspan=3, sticky=tk.EW, padx=8, pady=(0, 6))
        # Wrap explanations to the available width, including at larger UI scales.
        frame.bind("<Configure>", lambda event: [
            label.configure(wraplength=max(200, event.width - 36))
            for label in (tagline, text_help)
        ])

        # ---- DXF version ----
        ttk.Label(frame, text="DXF Version:").grid(row=9, column=0, sticky=tk.W, **pad)
        self._var_dxf_ver = tk.StringVar(value="R2010")
        ttk.Combobox(
            frame,
            textvariable=self._var_dxf_ver,
            values=list(DXF_VERSIONS),
            state="readonly",
            width=10,
        ).grid(row=9, column=1, sticky=tk.W, **pad)

        # ---- Option checkboxes ----
        # BCS-ARCH-001 Rule 5 sweep: only Import text and Open-in-LibreCAD
        # remain user-facing. Detect arcs / Map dash patterns / Make faces
        # were quality-tier dials and are now hardcoded True internally.
        opts_frame = ttk.LabelFrame(frame, text="Options", padding=6)
        opts_frame.grid(row=10, column=0, columnspan=3, sticky=tk.EW, **pad)

        self._var_import_text = tk.BooleanVar(value=True)
        self._var_launch_librecad = tk.BooleanVar(value=True)

        ttk.Checkbutton(opts_frame, text="Import text",
                        variable=self._var_import_text).pack(side=tk.LEFT, padx=6)
        launch_check = ttk.Checkbutton(opts_frame, text="Open in LibreCAD after convert",
                                       variable=self._var_launch_librecad)
        launch_check.pack(side=tk.LEFT, padx=6)
        if self._handoff_path:
            # The LibreCAD that started this window opens the DXF itself;
            # never start a second LibreCAD.
            self._var_launch_librecad.set(False)
            launch_check.configure(state=tk.DISABLED)
            ttk.Label(
                frame,
                text=(
                    "Started from LibreCAD: after a successful conversion the DXF\n"
                    "opens in that LibreCAD window and this window closes."
                ),
                font=("Segoe UI", 9, "bold"),
            ).grid(row=15, column=0, columnspan=3, sticky=tk.W, padx=8, pady=(4, 0))
        else:
            ttk.Button(
                opts_frame,
                text="Install LibreCAD menu entry...",
                command=self._install_librecad_menu,
            ).pack(side=tk.RIGHT, padx=6)

        # ---- Convert button ----
        action_frame = ttk.Frame(frame)
        action_frame.grid(row=11, column=0, columnspan=3, **pad)
        self._btn_convert = ttk.Button(
            action_frame, text="Convert / Resume", command=self._start_conversion,
        )
        self._btn_convert.pack(side=tk.LEFT, padx=4)
        self._btn_cancel = ttk.Button(
            action_frame,
            text="Cancel",
            command=self._request_cancel,
            state=tk.DISABLED,
        )
        self._btn_cancel.pack(side=tk.LEFT, padx=4)
        # Shown only after LibreCAD was not found or could not be started.
        self._btn_locate_librecad = ttk.Button(
            action_frame, text="Locate LibreCAD...", command=self._locate_librecad,
        )

        # ---- Progress bar ----
        self._progress = ttk.Progressbar(
            frame,
            mode="determinate",
            maximum=1,
            value=0,
            length=400,
        )
        self._progress.grid(row=12, column=0, columnspan=3, sticky=tk.EW, **pad)

        # ---- Status log ----
        ttk.Label(frame, text="Log:").grid(row=13, column=0, sticky=tk.NW, **pad)
        log_frame = ttk.Frame(frame)
        log_frame.grid(row=14, column=0, columnspan=3, sticky=tk.NSEW, **pad)
        self._log_text = tk.Text(log_frame, height=10, width=1, state=tk.DISABLED,
                                 wrap=tk.WORD, font=("Consolas", 9))
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self._log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.configure(yscrollcommand=log_scroll.set)

        # Let the log area expand when the window is resized
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(14, weight=1)

    # ------------------------------------------------------------------
    # Browse dialogs
    # ------------------------------------------------------------------
    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Select PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            old_input = self._var_input.get().strip()
            output = self._var_output.get().strip()
            self._var_input.set(path)
            # The output follows the PDF while it still holds the name filled in
            # for the previous PDF; a name the user picked or typed stays put.
            auto_output = (
                os.path.splitext(old_input)[0] + ".dxf" if old_input else ""
            )
            if not output or (
                auto_output
                and os.path.normcase(os.path.normpath(output))
                == os.path.normcase(os.path.normpath(auto_output))
            ):
                self._var_output.set(os.path.splitext(path)[0] + ".dxf")

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save DXF file as",
            defaultextension=".dxf",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
        )
        if path:
            self._var_output.set(path)

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        """Append a message to the log widget (thread-safe via after())."""
        def _append():
            # A page with a degraded text item is "exported ... NOT certified".
            progress = re.search(r"Page\s+(\d+)/(\d+)\s+(?:certified|exported)", msg)
            if progress:
                current, total = int(progress.group(1)), int(progress.group(2))
                self._progress.configure(maximum=max(1, total), value=current)
            self._log_text.configure(state=tk.NORMAL)
            self._log_text.insert(tk.END, msg + "\n")
            self._log_text.see(tk.END)
            self._log_text.configure(state=tk.DISABLED)
        self.after(0, _append)

    def _request_cancel(self) -> None:
        """Request a bounded, page-safe stop without discarding certified work."""
        if not self._converting or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self._btn_cancel.configure(state=tk.DISABLED)
        self._log("Cancel requested — finishing the active safe boundary...")

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
    def _capture_options(self) -> ConversionOptions:
        """Read Tk variables once, on the main thread, and reject invalid inputs."""
        from librecad_pdf_importer.launchers.librecad_launcher import (
            preferred_librecad_executable,
        )
        from page_selection import parse_page_selection

        try:
            scale = float(self._var_scale.get())
        except ValueError:
            raise ValueError("Scale must be a positive, finite number, such as 1.0 or 0.5.") from None
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("Scale must be a positive, finite number, such as 1.0 or 0.5.")
        raw_pages = self._var_pages.get().strip()
        pages = None
        if raw_pages:
            from pdf_open_guard import precheck_pdf

            page_count = precheck_pdf(self._var_input.get().strip())
            pages = parse_page_selection(raw_pages, page_count)
        return ConversionOptions(
            scale=scale,
            import_text=self._var_import_text.get(),
            text_mode=TEXT_MODES[self._var_text_mode.get()],
            pages=tuple(pages) if pages is not None else None,
            dxf_version=self._var_dxf_ver.get(),
            launch_librecad=self._var_launch_librecad.get(),
            librecad_executable=preferred_librecad_executable(
                getattr(self, "_librecad_choice", None)
            ),
        )

    def _start_conversion(self) -> None:
        if self._converting:
            return

        input_path = self._var_input.get().strip()
        output_path = self._var_output.get().strip()

        if not input_path:
            messagebox.showwarning("Missing input", "Please select an input PDF file.")
            return
        if not os.path.isfile(input_path):
            messagebox.showerror("File not found", f"Input file not found:\n{input_path}")
            return
        if not output_path:
            output_path = os.path.splitext(input_path)[0] + ".dxf"
            self._var_output.set(output_path)

        from pdf_open_guard import PdfOpenError

        try:
            options = self._capture_options()
        except (ValueError, PdfOpenError) as exc:
            messagebox.showwarning("Check conversion settings", str(exc))
            return

        # Never write over another drawing, or over edits saved into this one,
        # without asking first.
        replace_reason = output_replace_reason(input_path, output_path)
        if replace_reason and not messagebox.askyesno(
            "Replace drawing?",
            f"{os.path.basename(output_path)} {replace_reason}. Replace it?\n\n"
            "Choose No to keep it, then pick another name with the Browse... "
            "button next to Output DXF.",
        ):
            return

        self._converting = True
        self._cancel_event.clear()
        self._btn_convert.configure(state=tk.DISABLED)
        self._btn_cancel.configure(state=tk.NORMAL)
        self._progress.configure(maximum=1, value=0)

        # Clear log
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state=tk.DISABLED)

        # Run conversion in a background thread to keep the UI responsive
        thread = threading.Thread(
            target=self._run_conversion,
            args=(input_path, output_path, options),
            daemon=True,
        )
        thread.start()

    def _run_conversion(
        self, input_path: str, output_path: str, options: ConversionOptions,
    ) -> None:
        """Execute the conversion pipeline (runs in a worker thread)."""
        try:
            from pdfcadcore.import_config import ImportConfig
            from dxf_import_engine import convert

            # BCS-ARCH-001: GUI always uses Auto (strategy per page).
            config: ImportConfig = ImportConfig.auto()

            # The worker never reads live Tk values: edits belong to the next run.
            config.user_scale = options.scale
            config.import_text = options.import_text
            config.text_mode = options.text_mode
            config.verbose = True
            config.pages = list(options.pages) if options.pages is not None else None
            dxf_version = options.dxf_version

            t0 = time.perf_counter()
            self._log(f"Starting conversion: {os.path.basename(input_path)}")
            self._log("Import mode: Auto (per-page strategy)")
            self._log(
                f"Settings: scale={options.scale:g}; text="
                f"{options.text_mode if options.import_text else 'off'}; DXF={dxf_version}"
            )
            selection = (
                f"{len(config.pages)} selected page(s)"
                if config.pages is not None
                else "all pages in the PDF"
            )
            self._log(
                f"Work estimate: {selection}. Each completed page is checkpointed "
                "and resumable; a page with a degraded text item is never certified."
            )

            from pdf_open_guard import precheck_pdf
            precheck_pdf(input_path)  # clean reject for encrypted/empty/non-PDF (caught below)

            from librecad_pdf_importer.launchers.librecad_launcher import (
                find_librecad_executable,
            )

            resolved_librecad_executable = (
                find_librecad_executable(options.librecad_executable) or ""
            )
            if not resolved_librecad_executable:
                # Unbound call: tests drive this worker with a window-less namespace.
                self.after(0, lambda: Pdf2DxfApp._show_locate_librecad(self))
            stats = convert(
                input_path=input_path,
                output_path=output_path,
                config=config,
                dxf_version=dxf_version,
                progress_callback=self._log,
                resumable=True,
                cancel_requested=self._cancel_event.is_set,
                restart_on_resume_mismatch=True,
                librecad_executable=resolved_librecad_executable,
            )

            elapsed = time.perf_counter() - t0
            self._log("")
            self._log(f"Conversion complete in {elapsed:.2f}s")
            self._log(f"  Pages:    {stats.get('pages', '?')}")
            self._log(f"  Entities: {stats.get('entities', '?')}")
            self._log(f"  Text:     {stats.get('text_items', 0)}")
            self._log(f"  Output:   {output_path}")
            text_delivery = dict(stats.get("text_delivery") or {})
            self._log(
                "  Text delivery: requested={requested}; delivered={delivered}; "
                "fallback={fallback}; items={items}".format(
                    requested=text_delivery.get("requested", "none"),
                    delivered=text_delivery.get("delivered", "none"),
                    fallback=(
                        "yes" if text_delivery.get("fallback_used") else "no"
                    ),
                    items=text_delivery.get("item_count", 0),
                )
            )
            self._log(
                f"  Complete report: {text_delivery.get('report_path', '')}"
            )
            # The scale read from the title block: the DXF is paper size in mm
            # unless Scale says otherwise, so tell the fitter the multiplier.
            from librecad_pdf_importer.importer import drawing_scale_line

            scale_line = drawing_scale_line(stats.get("resolved_scale"), options.scale)
            if scale_line:
                self._log(scale_line)
            # Said once, at completion, pages certified by an earlier run included.
            clip_fill_warning = str(stats.get("clip_fill_warning") or "")
            if clip_fill_warning:
                self._log(clip_fill_warning)
            # Text a font delivered as raw glyph codes: recovered characters
            # came from an installed reference face, not from the PDF, and an
            # unproven span is still on the drawing as raw codes. Either way
            # the operator is the one who has to know.
            glyph_code_warning = str(stats.get("text_glyph_code_warning") or "")
            if glyph_code_warning:
                self._log(glyph_code_warning)
            # A lost hidden search-text companion is a warning; the drawing is unaffected.
            search_text_warning = str(stats.get("searchable_text_warning") or "")
            if search_text_warning:
                self._log(search_text_warning)
            # A degraded text item never costs the sheet, so it must be loud.
            degraded_count = int(text_delivery.get("degraded_item_count") or 0)
            if degraded_count:
                from librecad_pdf_importer.exporters.dxf_exporter import (
                    degraded_text_item_lines,
                )

                for line in degraded_text_item_lines(
                    text_delivery.get("degraded_items") or [], degraded_count
                ):
                    self._log(f"  {line}")

            launch_message = ""
            if options.launch_librecad and not getattr(self, "_handoff_path", None):
                from librecad_pdf_importer.launchers.librecad_launcher import launch_librecad
                launch_ok, launch_status = launch_librecad(
                    output_path,
                    executable=resolved_librecad_executable,
                )
                if launch_ok:
                    launch_message = launch_status
                    self._log(launch_status)
                else:
                    launch_message = (
                        LIBRECAD_START_FAILED_TIP
                        if resolved_librecad_executable
                        else LIBRECAD_NOT_FOUND_TIP
                    )
                    if resolved_librecad_executable:
                        self._log(launch_status)
                    self._log(launch_message)
                    self.after(0, lambda: Pdf2DxfApp._show_locate_librecad(self))

            # The sheet exported, so this is a warning, never an error box.
            show_done = messagebox.showwarning if degraded_count else messagebox.showinfo
            self.after(0, lambda: show_done(
                "Done with warnings" if degraded_count else "Done",
                (
                    f"Conversion complete, but {degraded_count} text item(s) could not "
                    "be verified and were degraded or dropped. Review them in the log "
                    "and the report before using this drawing.\n\n"
                    if degraded_count
                    else "Conversion complete.\n\n"
                )
                + f"Pages: {stats.get('pages', '?')}\n"
                 f"Entities: {stats.get('entities', '?')}\n"
                 f"Text requested: {text_delivery.get('requested', 'none')}\n"
                 f"Text delivered: {text_delivery.get('delivered', 'none')}\n"
                 f"Text fallback used: "
                 f"{'yes' if text_delivery.get('fallback_used') else 'no'}\n"
                 f"Complete report: {text_delivery.get('report_path', '')}\n"
                 f"Output: {output_path}"
                + (f"\n\n{scale_line}" if scale_line else "")
                + (f"\n\n{clip_fill_warning}" if clip_fill_warning else "")
                + (f"\n\n{glyph_code_warning}" if glyph_code_warning else "")
                + (f"\n\n{search_text_warning}" if search_text_warning else "")
                + (f"\n\n{launch_message}" if launch_message else ""),
            ))
            # Unbound call: tests drive this worker with a window-less namespace.
            Pdf2DxfApp._hand_off_to_librecad(
                self,
                output_path,
                degraded_count,
                str(text_delivery.get("report_path", "") or ""),
            )

        except Exception as exc:  # noqa: BLE001
            from dxf_import_engine import ConversionCancelled
            from pdfcadcore.fitz_loader import PdfOpenError

            if isinstance(exc, ConversionCancelled):
                self._log(f"\n{exc}")
                self.after(0, lambda e=exc: messagebox.showinfo(
                    "Import paused",
                    f"{e}\n\nCertified pages were kept in:\n{e.output_path}\n\n"
                    "Press Convert / Resume with the same PDF and settings to continue.",
                ))
            elif isinstance(exc, PdfOpenError):
                self._log(f"\nERROR: {exc}")
                self.after(0, lambda e=exc: messagebox.showerror("Conversion failed", str(e)))
            else:
                self._log(f"\nERROR: {exc}")
                # Like the console entry points: name the failure report the export
                # left. A deliberate stop already carries it in its message.
                detail = str(exc)
                failure_report = str(getattr(exc, "failure_report_path", "") or "")
                if failure_report and failure_report not in detail:
                    detail += f"\n\nComplete failure report: {failure_report}"
                self.after(0, lambda m=detail: messagebox.showerror(
                    "Conversion failed", m,
                ))

        finally:
            self.after(0, self._finish_conversion)

    def _finish_conversion(self) -> None:
        self._btn_convert.configure(state=tk.NORMAL)
        self._btn_cancel.configure(state=tk.DISABLED)
        self._converting = False
        if getattr(self, "_handoff_delivered", False):
            # Runs after the Done dialog was dismissed; LibreCAD already has
            # the drawing, so return the operator to it.
            self.destroy()

    # ------------------------------------------------------------------
    # LibreCAD menu integration
    # ------------------------------------------------------------------
    def _hand_off_to_librecad(
        self, output_path: str, degraded_count: int, report_path: str,
    ) -> None:
        """Tell the LibreCAD plugin which DXF to open (worker thread, after export)."""
        handoff_path = getattr(self, "_handoff_path", None)
        if not handoff_path:
            return
        from librecad_pdf_importer.librecad_handoff import write_handoff_result

        try:
            write_handoff_result(
                handoff_path,
                status="ok",
                output_path=output_path,
                degraded_text_items=degraded_count,
                report_path=report_path,
            )
        except OSError as exc:
            self._log(f"Could not hand the DXF back to LibreCAD: {exc}")
            return
        self._handoff_delivered = True
        self._log("Handed the DXF to LibreCAD; it opens there now.")

    def _close_from_librecad_handoff(self) -> None:
        """Window closed without a finished drawing: release the waiting plugin."""
        if not self._handoff_delivered and self._handoff_path:
            from librecad_pdf_importer.librecad_handoff import write_handoff_result

            try:
                write_handoff_result(self._handoff_path, status="closed")
            except OSError:
                pass  # the plugin also notices the process exit
        self.destroy()

    def _show_locate_librecad(self) -> None:
        """Offer "Locate LibreCAD..." once a lookup or a launch failed."""
        button = getattr(self, "_btn_locate_librecad", None)
        if button is not None and not button.winfo_manager():
            button.pack(side=tk.LEFT, padx=4)

    def _locate_librecad(self) -> None:
        """Let the user point at LibreCAD.exe once; the choice is remembered."""
        from librecad_pdf_importer.launchers.librecad_launcher import (
            find_librecad_executable,
            save_librecad_executable,
        )

        path = filedialog.askopenfilename(
            title="Locate LibreCAD.exe",
            filetypes=[
                ("LibreCAD program", "LibreCAD.exe"),
                ("Programs", "*.exe"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        found = find_librecad_executable(path)
        if not found:
            messagebox.showwarning(
                "Locate LibreCAD",
                f"That file could not be used as LibreCAD:\n{path}",
            )
            return
        self._librecad_choice = found
        if save_librecad_executable(found):
            self._log(f"LibreCAD set to {found}. It is remembered for next time.")
        else:
            self._log(
                f"LibreCAD set to {found} for this window. It could not be "
                "remembered for next time."
            )
        if os.environ.get("BCS_LIBRECAD_EXECUTABLE", "").strip():
            self._log(
                "Note: the BCS_LIBRECAD_EXECUTABLE setting on this PC still "
                "chooses LibreCAD while it is set."
            )
        self._btn_locate_librecad.pack_forget()

    def _install_librecad_menu(self) -> None:
        from librecad_pdf_importer.librecad_plugin_install import (
            TARGET_LIBRECAD,
            PluginInstallError,
            install_librecad_plugin,
        )

        try:
            result = install_librecad_plugin()
        except PluginInstallError as exc:
            messagebox.showerror("Install LibreCAD menu entry", str(exc))
            return
        messagebox.showinfo(
            "Install LibreCAD menu entry",
            "Installed the LibreCAD menu entry.\n\n"
            f"Plugin: {result.dll_path}\n"
            f"Starts: {result.launcher_path}\n\n"
            "Restart LibreCAD, then use:\n"
            "Plugins > Import PDF (BlueCollar)...\n\n"
            f"Built for {TARGET_LIBRECAD}.",
        )


# ---------------------------------------------------------------------------
# Public launcher (called from pdf2dxf.py --gui)
# ---------------------------------------------------------------------------
def launch_gui(handoff_path: str | None = None) -> None:
    """Create and run the Pdf2DxfApp main loop.

    *handoff_path* is the ``--librecad-handoff`` file given by the LibreCAD
    ``Plugins > Import PDF (BlueCollar)...`` menu entry.
    """
    app = Pdf2DxfApp(handoff_path=handoff_path)
    app.mainloop()


if __name__ == "__main__":
    from librecad_pdf_importer.librecad_handoff import handoff_path_from_argv

    launch_gui(handoff_path_from_argv(sys.argv[1:]))
