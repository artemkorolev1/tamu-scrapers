#!/usr/bin/env python3
"""
TAMU Scraper GUI — tkinter desktop app.
Opens, click Start, scrapes everything. No command-line needed.
"""

import datetime
import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from howdy_portal_scraper import discover_all_departments, run_howdy_scrape
from simple_syllabus_scraper import run_simple_syllabus_scrape

# ── Constants ────────────────────────────────────────────────────────────────

TERM_CHOICES = ["Spring 2026", "Summer 2026", "Fall 2026"]

TERM_DISPLAY_TO_CODE = {
    "Spring 2025": "202511",
    "Summer 2025": "202521",
    "Fall 2025": "202531",
    "Spring 2026": "202611",
    "Summer 2026": "202621",
    "Fall 2026": "202631",
}

# ── GUI ──────────────────────────────────────────────────────────────────────


class ScraperGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("TAMU Scraper")
        self.root.geometry("900x680")
        self.root.minsize(700, 500)

        self._running = False
        self._cancel_flag = threading.Event()
        self._thread = None
        self._departments_count = "?"

        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        # Main container
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # Left panel
        left = ttk.Frame(main, width=260)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left.pack_propagate(False)

        # Right panel
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_left_panel(left)
        self._build_log_panel(right)

    def _build_left_panel(self, parent):
        # ── Source ──
        ttk.Label(parent, text="Source", font=("", 10, "bold")).pack(anchor=tk.W, pady=(5, 2))
        self.chk_howdy = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Howdy Portal (sections + PDFs)", variable=self.chk_howdy).pack(anchor=tk.W)
        self.chk_syllabus = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Simple Syllabus (PDFs only)", variable=self.chk_syllabus).pack(anchor=tk.W)

        # ── Departments ──
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(parent, text="Departments", font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 2))
        self.chk_all_depts = tk.BooleanVar(value=True)
        self._dept_cb = ttk.Checkbutton(
            parent, text="All departments", variable=self.chk_all_depts,
            command=self._on_dept_toggle
        )
        self._dept_cb.pack(anchor=tk.W)
        self._dept_count_label = ttk.Label(parent, text="(auto-discovered on start)", foreground="gray")
        self._dept_count_label.pack(anchor=tk.W, padx=(25, 0))
        # Department entry (disabled when "all" is checked)
        self._dept_entry_var = tk.StringVar(value="CSCE,ISEN,STAT,ECEN")
        self._dept_entry = ttk.Entry(parent, textvariable=self._dept_entry_var, state=tk.DISABLED)
        self._dept_entry.pack(anchor=tk.W, fill=tk.X, padx=(25, 0), pady=(2, 0))

        # ── Course Level ──
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(parent, text="Course Level", font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 2))
        self.chk_grad = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Graduate (600+)", variable=self.chk_grad,
                        command=self._validate_level).pack(anchor=tk.W)
        self.chk_undergrad = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Undergraduate (<600)", variable=self.chk_undergrad,
                        command=self._validate_level).pack(anchor=tk.W)

        # ── Terms ──
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(parent, text="Terms", font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 2))
        self.term_vars: dict[str, tk.BooleanVar] = {}
        for t in TERM_CHOICES:
            v = tk.BooleanVar(value=True)
            self.term_vars[t] = v
            ttk.Checkbutton(parent, text=t, variable=v).pack(anchor=tk.W)

        # ── Output ──
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(parent, text="Output Directory", font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 2))
        out_frame = ttk.Frame(parent)
        out_frame.pack(fill=tk.X)
        self.out_dir_var = tk.StringVar(value=os.path.abspath("./output"))
        self._out_entry = ttk.Entry(out_frame, textvariable=self.out_dir_var)
        self._out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(out_frame, text="...", width=3, command=self._browse_out).pack(side=tk.RIGHT, padx=(5, 0))

        # ── Start button ──
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        self._start_btn = ttk.Button(parent, text="Start Scraping", command=self._on_start)
        self._start_btn.pack(fill=tk.X, pady=(10, 0))

        # ── Status ──
        self._status_var = tk.StringVar(value="Ready — check your settings and click Start.")
        ttk.Label(parent, textvariable=self._status_var, foreground="gray",
                  wraplength=240).pack(fill=tk.X, pady=(10, 0))

    def _build_log_panel(self, parent):
        ttk.Label(parent, text="Output Log", font=("", 10, "bold")).pack(anchor=tk.W)
        self._log = scrolledtext.ScrolledText(
            parent, wrap=tk.WORD, bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="#d4d4d4", font=("Consolas", 10),
            state=tk.DISABLED
        )
        self._log.pack(fill=tk.BOTH, expand=True)

        # Color tags
        self._log.tag_config("success", foreground="#4ec9b0")
        self._log.tag_config("warning", foreground="#ce9178")
        self._log.tag_config("error", foreground="#f44747")
        self._log.tag_config("info", foreground="#d4d4d4")
        self._log.tag_config("header", foreground="#569cd6", font=("Consolas", 10, "bold"))

        # Redirect stdout to log widget
        self._stdout_queue = []

    def _on_dept_toggle(self):
        if self.chk_all_depts.get():
            self._dept_entry.configure(state=tk.DISABLED)
            self._dept_count_label.configure(text="(auto-discovered on start)")
        else:
            self._dept_entry.configure(state=tk.NORMAL)
            self._dept_count_label.configure(text="")

    def _validate_level(self):
        if not self.chk_grad.get() and not self.chk_undergrad.get():
            messagebox.showwarning("No Level", "Select at least one course level.")
            self.chk_grad.set(True)

    def _browse_out(self):
        d = filedialog.askdirectory(title="Select Output Directory")
        if d:
            self.out_dir_var.set(d)

    # ── Logging ──────────────────────────────────────────────────────────

    def _log_write(self, text: str, tag: str = "info"):
        """Thread-safe log write via queue polling."""
        self._log.configure(state=tk.NORMAL)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log.insert(tk.END, f"[{ts}] ", "info")
        self._log.insert(tk.END, f"{text}\n", tag)
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def _log_callback(self, msg: str):
        """Called from scraper thread — schedule UI update."""
        self.root.after(0, self._log_write, msg, "info")

    def _log_header(self, text: str):
        self._log_write(f"═══ {text} ═══", "header")

    def _log_success(self, text: str):
        self._log_write(text, "success")

    def _log_warning(self, text: str):
        self._log_write(text, "warning")

    def _log_error(self, text: str):
        self._log_write(text, "error")

    # ── Scraping thread ──────────────────────────────────────────────────

    def _on_start(self):
        if self._running:
            return

        # Validate
        if not self.chk_howdy.get() and not self.chk_syllabus.get():
            messagebox.showwarning("No Source", "Select at least one source to scrape.")
            return

        terms = [t for t in TERM_CHOICES if self.term_vars[t].get()]
        if not terms:
            messagebox.showwarning("No Terms", "Select at least one term.")
            return

        if not self.chk_grad.get() and not self.chk_undergrad.get():
            messagebox.showwarning("No Level", "Select at least one course level.")
            return

        # Lock UI
        self._running = True
        self._cancel_flag.clear()
        self._start_btn.configure(text="Running…", state=tk.DISABLED)
        self._status_var.set("Starting…")

        # Clear log
        self._log.configure(state=tk.NORMAL)
        self._log.delete("1.0", tk.END)
        self._log.configure(state=tk.DISABLED)

        self._log_header("TAMU Scraper")
        self._log_write(f"Sources: {self._selected_sources()}")
        self._log_write(f"Terms: {terms}")
        self._log_write(f"Output: {self.out_dir_var.get()}")

        self._thread = threading.Thread(target=self._run_scrape, args=(terms,), daemon=True)
        self._thread.start()

        # Poll thread
        self._poll_thread()

    def _selected_sources(self) -> str:
        parts = []
        if self.chk_howdy.get():
            parts.append("Howdy Portal")
        if self.chk_syllabus.get():
            parts.append("Simple Syllabus")
        return ", ".join(parts)

    def _poll_thread(self):
        if self._thread is None:
            return
        if self._thread.is_alive():
            self.root.after(200, self._poll_thread)
        else:
            self._finish()

    def _finish(self):
        self._running = False
        self._start_btn.configure(text="Start Scraping", state=tk.NORMAL)
        self._status_var.set("Done — check the Output Log above for results.")
        self._log_header("Done")
        self._log_success(f"Output saved to: {self.out_dir_var.get()}")

    def _run_scrape(self, terms: list[str]):
        """Background thread entry point."""
        output_dir = self.out_dir_var.get()
        all_depts = self.chk_all_depts.get()
        graduate_only = not self.chk_undergrad.get()

        # Resolve departments
        if all_depts:
            department_list = []  # will be discovered
        else:
            department_list = [d.strip() for d in self._dept_entry_var.get().split(",") if d.strip()]

        # ── Phase 1: Discover departments if needed ──
        discovered_depts = None
        if all_depts:
            self.root.after(0, self._log_write, "Auto-discovering departments from Howdy Portal…", "info")
            self.root.after(0, self._status_var.set, "Discovering departments…")
            try:
                term_codes = [TERM_DISPLAY_TO_CODE[t] for t in terms if t in TERM_DISPLAY_TO_CODE]
                discovered_depts = discover_all_departments(term_codes)
                self.root.after(0, self._log_write,
                                f"Found {len(discovered_depts)} departments: {', '.join(sorted(discovered_depts))}", "success")
                self._departments_count = str(len(discovered_depts))
                self.root.after(0, self._dept_count_label.configure,
                                {"text": f"({len(discovered_depts)} departments found)"})
                department_list = sorted(discovered_depts)
            except Exception as e:
                self.root.after(0, self._log_error, f"Department discovery failed: {e}")
                self.root.after(0, self._finish)
                return

        # ── Phase 2: Howdy Portal ──
        if self.chk_howdy.get():
            self.root.after(0, self._log_header, "Howdy Portal")
            self.root.after(0, self._status_var.set, "Scraping Howdy Portal…")
            try:
                result = run_howdy_scrape(
                    output_dir=output_dir,
                    departments=department_list,
                    terms=[TERM_DISPLAY_TO_CODE.get(t, t) for t in terms],
                    graduate_only=graduate_only,
                    delay=2.0,
                    all_departments=all_depts,
                    log_callback=self._log_callback,
                )
                self.root.after(0, self._log_success,
                                f"Howdy Portal done: {result['total_sections']} sections, {result['total_pdfs']} PDFs")
            except Exception as e:
                self.root.after(0, self._log_error, f"Howdy Portal error: {e}")

        # ── Phase 3: Simple Syllabus ──
        if self.chk_syllabus.get():
            self.root.after(0, self._log_header, "Simple Syllabus")
            self.root.after(0, self._status_var.set, "Scraping Simple Syllabus…")
            try:
                result = run_simple_syllabus_scrape(
                    output_dir=output_dir,
                    departments=department_list,
                    terms=terms,
                    graduate_only=graduate_only,
                    delay=1.0,
                    max_retries=5,
                    max_mb=0,
                    all_departments=all_depts,
                    log_callback=self._log_callback,
                )
                self.root.after(0, self._log_success,
                                f"Simple Syllabus done: {result['downloaded']} downloaded, "
                                f"{result['skipped']} skipped, {result['failed']} failed")
            except Exception as e:
                self.root.after(0, self._log_error, f"Simple Syllabus error: {e}")

        # ── Summary ──
        self.root.after(0, self._log_write, "")
        self.root.after(0, self._log_success, "All scraping complete!")
        self.root.after(0, self._log_write, f"Output directory: {os.path.abspath(output_dir)}")


def main():
    root = tk.Tk()
    gui = ScraperGUI(root)

    def on_close():
        if gui._running:
            if messagebox.askyesno("Scraping in progress", "Scraping is still running. Stop and exit?"):
                gui._cancel_flag.set()
                root.destroy()
        else:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
