import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import os
import sys
import sqlite3
from datetime import datetime
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.worker import ScrapeWorker

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg":           "#0f0f17",
    "sidebar":      "#13131f",
    "card":         "#1a1a2e",
    "card2":        "#16213e",
    "border":       "#2a2a45",
    "accent":       "#4f8ef7",
    "accent_hover": "#6ba3ff",
    "success":      "#4ade80",
    "warning":      "#facc15",
    "danger":       "#f87171",
    "muted":        "#6b7280",
    "text":         "#e2e8f0",
    "text_dim":     "#94a3b8",
    "tree_bg":      "#12121e",
    "tree_sel":     "#1e3a5f",
    "tree_head":    "#0f1929",
}

COLUMNS = [
    ("name",            "Business Name",  260),
    ("phone_number",    "Phone",          140),
    ("website",         "Website",        200),
    ("address",         "Address",        260),
    ("reviews_average", "Rating",          70),
    ("reviews_count",   "Reviews",         80),
    ("place_type",      "Category",       150),
]


class GoogleMapsScraper(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Google Maps Business Scraper")
        self.geometry("1380x860")
        self.minsize(1100, 700)
        self.configure(fg_color=COLORS["bg"])

        self._places = []
        self._worker = None
        self._stop_event = threading.Event()
        self._queue = queue.Queue()
        self._total_expected = 0

        self._init_db()
        self._build_ui()
        self._poll_queue()

    def _init_db(self):
        db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "results.db")
        self._db_conn = sqlite3.connect(db_path, check_same_thread=False)
        self._db_conn.execute("""
            CREATE TABLE IF NOT EXISTS places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                name TEXT, address TEXT, website TEXT, phone_number TEXT,
                reviews_count INTEGER, reviews_average REAL,
                store_shopping TEXT, in_store_pickup TEXT, store_delivery TEXT,
                place_type TEXT, opens_at TEXT, introduction TEXT,
                scraped_at TEXT
            )
        """)
        self._db_conn.commit()
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, fg_color=COLORS["sidebar"], width=300, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(10, weight=1)

        ctk.CTkLabel(
            sidebar, text="🗺  Maps Scraper",
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
            text_color=COLORS["accent"],
        ).grid(row=0, column=0, padx=24, pady=(28, 4), sticky="w")

        ctk.CTkLabel(
            sidebar, text="Google Maps Business Intelligence",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=COLORS["muted"],
        ).grid(row=1, column=0, padx=24, pady=(0, 24), sticky="w")

        sep = ctk.CTkFrame(sidebar, height=1, fg_color=COLORS["border"])
        sep.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 20))

        ctk.CTkLabel(
            sidebar, text="SEARCH PARAMETERS",
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            text_color=COLORS["muted"],
        ).grid(row=3, column=0, padx=24, pady=(0, 10), sticky="w")

        self._build_input(sidebar, "Business Keyword", "e.g.  italian restaurant", 4)
        self._build_input(sidebar, "Location", "e.g.  Toronto, Canada", 5)
        self._build_input(sidebar, "Max Results", "e.g.  20", 6)

        sep2 = ctk.CTkFrame(sidebar, height=1, fg_color=COLORS["border"])
        sep2.grid(row=7, column=0, sticky="ew", padx=16, pady=20)

        self._build_buttons(sidebar, 8)
        self._build_stats(sidebar, 9)

    def _build_input(self, parent, label, placeholder, row):
        ctk.CTkLabel(
            parent, text=label,
            font=ctk.CTkFont("Segoe UI", 12),
            text_color=COLORS["text_dim"],
        ).grid(row=row, column=0, padx=24, pady=(0, 4), sticky="w")

        entry = ctk.CTkEntry(
            parent,
            placeholder_text=placeholder,
            font=ctk.CTkFont("Segoe UI", 12),
            height=38,
            fg_color=COLORS["card"],
            border_color=COLORS["border"],
            border_width=1,
            text_color=COLORS["text"],
            corner_radius=8,
        )
        entry.grid(row=row, column=0, padx=24, pady=(18, 12), sticky="ew")
        parent.grid_columnconfigure(0, weight=1)

        key = label.lower().replace(" ", "_")
        if not hasattr(self, "_entries"):
            self._entries = {}
        self._entries[key] = entry

    def _build_buttons(self, parent, row):
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.grid(row=row, column=0, padx=16, pady=4, sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        self._btn_start = ctk.CTkButton(
            btn_frame, text="▶  Start Search",
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            height=42, corner_radius=10,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._start_scrape,
        )
        self._btn_start.grid(row=0, column=0, columnspan=2, padx=4, pady=4, sticky="ew")

        self._btn_stop = ctk.CTkButton(
            btn_frame, text="■  Stop",
            font=ctk.CTkFont("Segoe UI", 12),
            height=36, corner_radius=10,
            fg_color="#3b1f2b", hover_color="#5a2d3e",
            border_color=COLORS["danger"], border_width=1,
            text_color=COLORS["danger"],
            state="disabled",
            command=self._stop_scrape,
        )
        self._btn_stop.grid(row=1, column=0, padx=4, pady=4, sticky="ew")

        self._btn_clear = ctk.CTkButton(
            btn_frame, text="✕  Clear",
            font=ctk.CTkFont("Segoe UI", 12),
            height=36, corner_radius=10,
            fg_color=COLORS["card"], hover_color=COLORS["border"],
            text_color=COLORS["text_dim"],
            command=self._clear_results,
        )
        self._btn_clear.grid(row=1, column=1, padx=4, pady=4, sticky="ew")

        sep = ctk.CTkFrame(btn_frame, height=1, fg_color=COLORS["border"])
        sep.grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)

        self._btn_csv = ctk.CTkButton(
            btn_frame, text="⬇  Export CSV",
            font=ctk.CTkFont("Segoe UI", 12),
            height=36, corner_radius=10,
            fg_color="#1a2e1a", hover_color="#243824",
            border_color=COLORS["success"], border_width=1,
            text_color=COLORS["success"],
            command=self._export_csv,
        )
        self._btn_csv.grid(row=3, column=0, padx=4, pady=4, sticky="ew")

        self._btn_xlsx = ctk.CTkButton(
            btn_frame, text="⬇  Export Excel",
            font=ctk.CTkFont("Segoe UI", 12),
            height=36, corner_radius=10,
            fg_color="#1a2e1a", hover_color="#243824",
            border_color=COLORS["success"], border_width=1,
            text_color=COLORS["success"],
            command=self._export_excel,
        )
        self._btn_xlsx.grid(row=3, column=1, padx=4, pady=4, sticky="ew")

    def _build_stats(self, parent, row):
        stats_frame = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12)
        stats_frame.grid(row=row, column=0, padx=16, pady=16, sticky="sew")
        stats_frame.grid_columnconfigure((0, 1), weight=1)
        parent.grid_rowconfigure(row, weight=1)

        ctk.CTkLabel(
            stats_frame, text="SESSION STATS",
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            text_color=COLORS["muted"],
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 8), sticky="w")

        self._lbl_found = self._stat_item(stats_frame, "Found", "0", 1, 0, COLORS["accent"])
        self._lbl_saved = self._stat_item(stats_frame, "Saved", "0", 1, 1, COLORS["success"])

    def _stat_item(self, parent, label, value, row, col, color):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row, column=col, padx=12, pady=(0, 14), sticky="nsew")
        num = ctk.CTkLabel(f, text=value, font=ctk.CTkFont("Segoe UI", 26, "bold"), text_color=color)
        num.pack(anchor="w")
        ctk.CTkLabel(f, text=label, font=ctk.CTkFont("Segoe UI", 11), text_color=COLORS["muted"]).pack(anchor="w")
        return num

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew", padx=(1, 0))
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self._build_progress_bar(main, 0)
        self._build_table(main, 1)
        self._build_log_panel(main, 2)

    def _build_progress_bar(self, parent, row):
        top = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=0, height=80)
        top.grid(row=row, column=0, sticky="ew", padx=0, pady=0)
        top.grid_propagate(False)
        top.grid_columnconfigure(1, weight=1)

        self._lbl_status = ctk.CTkLabel(
            top, text="Ready — enter a query and press Start Search",
            font=ctk.CTkFont("Segoe UI", 13),
            text_color=COLORS["text_dim"],
        )
        self._lbl_status.grid(row=0, column=0, columnspan=3, padx=20, pady=(14, 2), sticky="w")

        self._progress = ctk.CTkProgressBar(
            top, height=8, corner_radius=4,
            fg_color=COLORS["border"],
            progress_color=COLORS["accent"],
        )
        self._progress.set(0)
        self._progress.grid(row=1, column=0, columnspan=2, padx=20, pady=(4, 14), sticky="ew")

        self._lbl_count = ctk.CTkLabel(
            top, text="0 / 0",
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            text_color=COLORS["accent"],
            width=60,
        )
        self._lbl_count.grid(row=1, column=2, padx=(0, 20), pady=(4, 14), sticky="e")

    def _build_table(self, parent, row):
        frame = ctk.CTkFrame(parent, fg_color=COLORS["card2"], corner_radius=0)
        frame.grid(row=row, column=0, sticky="nsew", padx=0, pady=1)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Treeview",
            background=COLORS["tree_bg"],
            foreground=COLORS["text"],
            fieldbackground=COLORS["tree_bg"],
            rowheight=30,
            font=("Segoe UI", 10),
            borderwidth=0,
        )
        style.configure("Dark.Treeview.Heading",
            background=COLORS["tree_head"],
            foreground=COLORS["accent"],
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            borderwidth=0,
        )
        style.map("Dark.Treeview",
            background=[("selected", COLORS["tree_sel"])],
            foreground=[("selected", "#ffffff")],
        )
        style.map("Dark.Treeview.Heading",
            background=[("active", COLORS["card"])],
        )
        style.configure("Dark.Vertical.TScrollbar",
            background=COLORS["card"],
            troughcolor=COLORS["tree_bg"],
            bordercolor=COLORS["border"],
            arrowcolor=COLORS["muted"],
        )

        col_ids = [c[0] for c in COLUMNS]
        self._tree = ttk.Treeview(
            frame,
            columns=col_ids,
            show="headings",
            style="Dark.Treeview",
            selectmode="browse",
        )

        for col_id, col_label, col_width in COLUMNS:
            self._tree.heading(col_id, text=col_label, anchor="w")
            self._tree.column(col_id, width=col_width, minwidth=60, anchor="w")

        scrollbar_y = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview, style="Dark.Vertical.TScrollbar")
        scrollbar_x = ttk.Scrollbar(frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")

        self._tree.tag_configure("even", background="#14142a")
        self._tree.tag_configure("odd",  background=COLORS["tree_bg"])

    def _build_log_panel(self, parent, row):
        log_frame = ctk.CTkFrame(parent, fg_color=COLORS["sidebar"], corner_radius=0, height=180)
        log_frame.grid(row=row, column=0, sticky="ew", padx=0, pady=(1, 0))
        log_frame.grid_propagate(False)
        log_frame.grid_rowconfigure(1, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            log_frame, text="ACTIVITY LOG",
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            text_color=COLORS["muted"],
        ).grid(row=0, column=0, padx=16, pady=(10, 2), sticky="w")

        self._log_box = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont("Courier New", 11),
            fg_color=COLORS["tree_bg"],
            text_color=COLORS["text_dim"],
            border_width=0,
            corner_radius=0,
            wrap="word",
            state="disabled",
        )
        self._log_box.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]

                if kind == "log":
                    self._append_log(msg[1])

                elif kind == "progress":
                    _, current, total, place = msg
                    self._add_row(place)
                    pct = current / total if total else 0
                    self._progress.set(pct)
                    self._lbl_count.configure(text=f"{current} / {total}")
                    self._lbl_status.configure(
                        text=f"Scraping: {place.name}",
                        text_color=COLORS["text"],
                    )
                    self._lbl_found.configure(text=str(len(self._places)))
                    self._save_to_db(place)

                elif kind == "done":
                    _, places = msg
                    self._places = places
                    self._on_scrape_finished(stopped=False)

                elif kind == "stopped":
                    self._on_scrape_finished(stopped=True)

                elif kind == "error":
                    self._on_scrape_error(msg[1])

        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_queue)

    def _start_scrape(self):
        keyword  = self._entries.get("business_keyword", ctk.CTkEntry(self)).get().strip()
        location = self._entries.get("location", ctk.CTkEntry(self)).get().strip()
        max_res  = self._entries.get("max_results", ctk.CTkEntry(self)).get().strip()

        if not keyword:
            messagebox.showwarning("Missing Input", "Please enter a business keyword.")
            return

        try:
            total = int(max_res) if max_res else 10
            if total < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid Input", "Max Results must be a positive number.")
            return

        search_query = f"{keyword} in {location}" if location else keyword

        self._places = []
        self._total_expected = total
        self._stop_event.clear()
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        self._tree.delete(*self._tree.get_children())
        self._progress.set(0)
        self._lbl_count.configure(text=f"0 / {total}")
        self._lbl_found.configure(text="0")
        self._lbl_status.configure(text=f"Launching browser — searching for: {search_query}", text_color=COLORS["warning"])
        self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Starting scrape: '{search_query}' — up to {total} results")

        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")

        self._worker = ScrapeWorker(search_query, total, self._queue, self._stop_event)
        self._worker.start()

    def _stop_scrape(self):
        self._stop_event.set()
        self._lbl_status.configure(text="Stop requested — finishing current item…", text_color=COLORS["warning"])
        self._btn_stop.configure(state="disabled")
        self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Stop requested by user.")

    def _on_scrape_finished(self, stopped: bool):
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        count = len(self._places)
        if stopped:
            self._lbl_status.configure(text=f"Stopped — {count} businesses collected", text_color=COLORS["warning"])
            self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Scrape stopped. {count} results collected.")
        else:
            self._progress.set(1.0)
            self._lbl_status.configure(text=f"Complete — {count} businesses found", text_color=COLORS["success"])
            self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Scrape complete. {count} results collected.")
        self._lbl_found.configure(text=str(count))
        self._lbl_saved.configure(text=str(count))

    def _on_scrape_error(self, message: str):
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._lbl_status.configure(text=f"Error: {message[:80]}", text_color=COLORS["danger"])
        self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {message}")
        messagebox.showerror("Scraper Error", f"An error occurred:\n\n{message}")

    def _clear_results(self):
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("In Progress", "Cannot clear while scrape is running. Stop first.")
            return
        self._places = []
        self._tree.delete(*self._tree.get_children())
        self._progress.set(0)
        self._lbl_count.configure(text="0 / 0")
        self._lbl_found.configure(text="0")
        self._lbl_saved.configure(text="0")
        self._lbl_status.configure(text="Ready — enter a query and press Start Search", text_color=COLORS["text_dim"])
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    def _add_row(self, place):
        self._places.append(place)
        tag = "even" if len(self._places) % 2 == 0 else "odd"
        values = (
            place.name or "",
            place.phone_number or "",
            place.website or "",
            place.address or "",
            f"{place.reviews_average:.1f} ★" if place.reviews_average else "—",
            f"{place.reviews_count:,}" if place.reviews_count else "—",
            place.place_type or "",
        )
        iid = self._tree.insert("", "end", values=values, tags=(tag,))
        self._tree.see(iid)

    def _append_log(self, text: str):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", text + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _save_to_db(self, place):
        try:
            d = asdict(place)
            self._db_conn.execute("""
                INSERT INTO places
                  (session_id, name, address, website, phone_number,
                   reviews_count, reviews_average, store_shopping,
                   in_store_pickup, store_delivery, place_type,
                   opens_at, introduction, scraped_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                self._session_id,
                d["name"], d["address"], d["website"], d["phone_number"],
                d["reviews_count"], d["reviews_average"],
                d["store_shopping"], d["in_store_pickup"], d["store_delivery"],
                d["place_type"], d["opens_at"], d["introduction"],
                datetime.now().isoformat(),
            ))
            self._db_conn.commit()
        except Exception as e:
            self._append_log(f"DB warning: {e}")

    def _export_csv(self):
        if not self._places:
            messagebox.showwarning("No Data", "No results to export yet.")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"results_{ts}.csv"
        exports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports")
        path = filedialog.asksaveasfilename(
            initialdir=exports_dir,
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Save CSV Export",
        )
        if not path:
            return
        import pandas as pd
        from dataclasses import asdict as _asdict
        df = pd.DataFrame([_asdict(p) for p in self._places])
        df.to_csv(path, index=False)
        self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] CSV exported → {path}")
        messagebox.showinfo("Export Complete", f"CSV saved to:\n{path}")

    def _export_excel(self):
        if not self._places:
            messagebox.showwarning("No Data", "No results to export yet.")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"results_{ts}.xlsx"
        exports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports")
        path = filedialog.asksaveasfilename(
            initialdir=exports_dir,
            initialfile=default_name,
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            title="Save Excel Export",
        )
        if not path:
            return
        import pandas as pd
        from dataclasses import asdict as _asdict
        df = pd.DataFrame([_asdict(p) for p in self._places])
        df.to_excel(path, index=False, engine="openpyxl")
        self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Excel exported → {path}")
        messagebox.showinfo("Export Complete", f"Excel saved to:\n{path}")

    def on_close(self):
        if self._worker and self._worker.is_alive():
            self._stop_event.set()
        try:
            self._db_conn.close()
        except Exception:
            pass
        self.destroy()


def run():
    app = GoogleMapsScraper()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    run()
