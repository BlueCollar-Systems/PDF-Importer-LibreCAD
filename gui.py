# -*- coding: utf-8 -*-
# gui.py -- Tkinter GUI for PDF to DXF conversion
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
A straightforward, functional tkinter interface for the PDF-to-DXF
converter.  Uses *ttk* widgets for a modern look.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODES = {
    "Auto":   "auto",
    "Vector": "vector",
    "Raster": "raster",
    "Hybrid": "hybrid",
}

# BCS-ARCH-001: text rendering is orthogonal to mode. Four text options
# (Labels, 3D Text, Glyphs, Geometry) plus a separate "Import text" toggle.
TEXT_MODES = {
    "Labels":   "labels",
    "3D Text":  "3d_text",
    "Glyphs":   "glyphs",
    "Geometry": "geometry",
}

DXF_VERSIONS = ("R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018")


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------
class Pdf2DxfApp(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("PDF to DXF Converter - BlueCollar Systems")
        self.resizable(True, True)
        self.minsize(560, 520)

        # Try to set a reasonable starting size
        self.geometry("620x620")

        self._build_ui()
        self._converting = False

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
            text="BlueCollar Systems -- BUILT. NOT BOUGHT.",
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=8)

        # ---- Input file ----
        ttk.Label(frame, text="Input PDF:").grid(row=2, column=0, sticky=tk.W, **pad)
        self._var_input = tk.StringVar()
        self._ent_input = ttk.Entry(frame, textvariable=self._var_input, width=50)
        self._ent_input.grid(row=2, column=1, sticky=tk.EW, **pad)
        ttk.Button(frame, text="Browse...", command=self._browse_input).grid(
            row=2, column=2, **pad,
        )

        # ---- Output file ----
        ttk.Label(frame, text="Output DXF:").grid(row=3, column=0, sticky=tk.W, **pad)
        self._var_output = tk.StringVar()
        self._ent_output = ttk.Entry(frame, textvariable=self._var_output, width=50)
        self._ent_output.grid(row=3, column=1, sticky=tk.EW, **pad)
        ttk.Button(frame, text="Browse...", command=self._browse_output).grid(
            row=3, column=2, **pad,
        )

        # ---- Mode (BCS-ARCH-001) ----
        ttk.Label(frame, text="Mode:").grid(row=4, column=0, sticky=tk.W, **pad)
        self._var_mode = tk.StringVar(value="Auto")
        ttk.Combobox(
            frame,
            textvariable=self._var_mode,
            values=list(MODES.keys()),
            state="readonly",
            width=20,
        ).grid(row=4, column=1, sticky=tk.W, **pad)

        # ---- Page range ----
        ttk.Label(frame, text="Pages:").grid(row=5, column=0, sticky=tk.W, **pad)
        self._var_pages = tk.StringVar()
        ttk.Entry(frame, textvariable=self._var_pages, width=20).grid(
            row=5, column=1, sticky=tk.W, **pad,
        )
        ttk.Label(frame, text="(e.g. 1,2,5  or blank for all)").grid(
            row=5, column=2, sticky=tk.W, **pad,
        )

        # ---- Scale ----
        ttk.Label(frame, text="Scale:").grid(row=6, column=0, sticky=tk.W, **pad)
        self._var_scale = tk.StringVar(value="1.0")
        ttk.Entry(frame, textvariable=self._var_scale, width=10).grid(
            row=6, column=1, sticky=tk.W, **pad,
        )

        # ---- Text mode (BCS-ARCH-001, orthogonal to import mode) ----
        ttk.Label(frame, text="Text Mode:").grid(row=7, column=0, sticky=tk.W, **pad)
        self._var_text_mode = tk.StringVar(value="3D Text")
        ttk.Combobox(
            frame,
            textvariable=self._var_text_mode,
            values=list(TEXT_MODES.keys()),
            state="readonly",
            width=20,
        ).grid(row=7, column=1, sticky=tk.W, **pad)

        # ---- DXF version ----
        ttk.Label(frame, text="DXF Version:").grid(row=8, column=0, sticky=tk.W, **pad)
        self._var_dxf_ver = tk.StringVar(value="R2010")
        ttk.Combobox(
            frame,
            textvariable=self._var_dxf_ver,
            values=list(DXF_VERSIONS),
            state="readonly",
            width=10,
        ).grid(row=8, column=1, sticky=tk.W, **pad)

        # ---- Option checkboxes ----
        # BCS-ARCH-001 Rule 5 sweep: only Import text and Open-in-LibreCAD
        # remain user-facing. Detect arcs / Map dash patterns / Make faces
        # were quality-tier dials and are now hardcoded True internally.
        opts_frame = ttk.LabelFrame(frame, text="Options", padding=6)
        opts_frame.grid(row=9, column=0, columnspan=3, sticky=tk.EW, **pad)

        self._var_import_text = tk.BooleanVar(value=True)
        self._var_launch_librecad = tk.BooleanVar(value=True)

        ttk.Checkbutton(opts_frame, text="Import text",
                        variable=self._var_import_text).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(opts_frame, text="Open in LibreCAD after convert",
                        variable=self._var_launch_librecad).pack(side=tk.LEFT, padx=6)

        # ---- Convert button ----
        self._btn_convert = ttk.Button(
            frame, text="Convert", command=self._start_conversion,
        )
        self._btn_convert.grid(row=10, column=0, columnspan=3, **pad)

        # ---- Progress bar ----
        self._progress = ttk.Progressbar(frame, mode="indeterminate", length=400)
        self._progress.grid(row=11, column=0, columnspan=3, sticky=tk.EW, **pad)

        # ---- Status log ----
        ttk.Label(frame, text="Log:").grid(row=12, column=0, sticky=tk.NW, **pad)
        self._log_text = tk.Text(frame, height=10, width=70, state=tk.DISABLED,
                                 wrap=tk.WORD, font=("Consolas", 9))
        self._log_text.grid(row=13, column=0, columnspan=3, sticky=tk.NSEW, **pad)

        # Let the log area expand when the window is resized
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(13, weight=1)

    # ------------------------------------------------------------------
    # Browse dialogs
    # ------------------------------------------------------------------
    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Select PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._var_input.set(path)
            # Auto-populate output if empty
            if not self._var_output.get():
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
            self._log_text.configure(state=tk.NORMAL)
            self._log_text.insert(tk.END, msg + "\n")
            self._log_text.see(tk.END)
            self._log_text.configure(state=tk.DISABLED)
        self.after(0, _append)

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
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

        self._converting = True
        self._btn_convert.configure(state=tk.DISABLED)
        self._progress.start(10)

        # Clear log
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state=tk.DISABLED)

        # Run conversion in a background thread to keep the UI responsive
        thread = threading.Thread(
            target=self._run_conversion,
            args=(input_path, output_path),
            daemon=True,
        )
        thread.start()

    def _run_conversion(self, input_path: str, output_path: str) -> None:
        """Execute the conversion pipeline (runs in a worker thread)."""
        try:
            from pdfcadcore.import_config import ImportConfig
            from dxf_import_engine import convert

            # BCS-ARCH-001: direct mode -> classmethod dispatch. No preset map.
            mode_key = MODES.get(self._var_mode.get(), "auto")
            config: ImportConfig = getattr(ImportConfig, mode_key)()

            # Apply GUI overrides
            try:
                config.user_scale = float(self._var_scale.get())
            except ValueError:
                config.user_scale = 1.0

            config.import_text = self._var_import_text.get()
            config.text_mode = TEXT_MODES.get(self._var_text_mode.get(), "3d_text")
            config.verbose = True

            # Parse pages
            raw_pages = self._var_pages.get().strip()
            if raw_pages:
                pages = []
                for part in raw_pages.split(","):
                    part = part.strip()
                    if "-" in part:
                        lo, hi = part.split("-", 1)
                        pages.extend(range(int(lo), int(hi) + 1))
                    else:
                        pages.append(int(part))
                config.pages = [max(0, p - 1) for p in pages]

            dxf_version = self._var_dxf_ver.get()

            t0 = time.perf_counter()
            self._log(f"Starting conversion: {os.path.basename(input_path)}")

            stats = convert(
                input_path=input_path,
                output_path=output_path,
                config=config,
                dxf_version=dxf_version,
                progress_callback=self._log,
            )

            elapsed = time.perf_counter() - t0
            self._log("")
            self._log(f"Conversion complete in {elapsed:.2f}s")
            self._log(f"  Pages:    {stats.get('pages', '?')}")
            self._log(f"  Entities: {stats.get('entities', '?')}")
            self._log(f"  Text:     {stats.get('text_items', 0)}")
            self._log(f"  Output:   {output_path}")

            launch_message = ""
            if self._var_launch_librecad.get():
                from librecad_pdf_importer.launchers.librecad_launcher import launch_librecad
                launch_ok, launch_status = launch_librecad(output_path)
                launch_message = launch_status
                self._log(launch_status)
                if not launch_ok:
                    self._log(
                        "Tip: Install LibreCAD or set the executable path in "
                        "librecad_pdf_importer.launchers.librecad_launcher.",
                    )

            self.after(0, lambda: messagebox.showinfo(
                "Done",
                f"Conversion complete.\n\n"
                f"Pages: {stats.get('pages', '?')}\n"
                f"Entities: {stats.get('entities', '?')}\n"
                f"Output: {output_path}"
                + (f"\n\n{launch_message}" if launch_message else ""),
            ))

        except Exception as exc:  # noqa: BLE001
            self._log(f"\nERROR: {exc}")
            self.after(0, lambda e=exc: messagebox.showerror(
                "Conversion failed", str(e),
            ))

        finally:
            self.after(0, self._finish_conversion)

    def _finish_conversion(self) -> None:
        self._progress.stop()
        self._btn_convert.configure(state=tk.NORMAL)
        self._converting = False


# ---------------------------------------------------------------------------
# Public launcher (called from pdf2dxf.py --gui)
# ---------------------------------------------------------------------------
def launch_gui() -> None:
    """Create and run the Pdf2DxfApp main loop."""
    app = Pdf2DxfApp()
    app.mainloop()


if __name__ == "__main__":
    launch_gui()
