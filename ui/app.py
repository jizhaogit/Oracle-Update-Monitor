"""
ui/app.py — Tkinter desktop UI for Oracle OCI/OIC Monitor.

Layout
------
┌──────────────────────────────────────────────────────────────────┐
│  Menu bar                                                        │
├──────────────────────────────────────────────────────────────────┤
│  Toolbar: [search box] [Search] [Refresh] [Mark Seen] [API docs] │
├─────────────────┬────────────────────────────────────────────────┤
│  SIDEBAR        │  DETAIL PANEL                                  │
│  ─────────────  │  ─────────────────────────────────────────────│
│  Filter row     │  Title                                         │
│  Category tree  │  Metadata badges                               │
│  (OCI/OIC/svc)  │  Summary                                       │
│                 │  Full content (scrollable)                     │
│                 │  Tags                                          │
├─────────────────┴────────────────────────────────────────────────┤
│  Status bar:  N updates  |  Last crawl: …  |  [● Running]        │
└──────────────────────────────────────────────────────────────────┘
"""

import logging
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Optional

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger(__name__)

# ── Colour palette ─────────────────────────────────────────────────────────────
CLR = {
    "bg_dark":    "#1a1d2e",
    "bg_mid":     "#252840",
    "bg_light":   "#2e3250",
    "bg_card":    "#1e2135",
    "accent":     "#c74634",   # Oracle red
    "accent2":    "#4a9eff",   # blue highlight
    "text":       "#e8eaf6",
    "text_dim":   "#8892b0",
    "text_white": "#ffffff",
    "green":      "#4caf50",
    "orange":     "#ff9800",
    "red":        "#f44336",
    "yellow":     "#ffeb3b",
    "new_badge":  "#1565c0",
}

IMPACT_CLR = {
    "High":   CLR["red"],
    "Medium": CLR["orange"],
    "Low":    CLR["green"],
    None:     CLR["text_dim"],
}

CAT_ICON = {"OCI": "☁", "OIC": "🔗", "General": "📋"}
SVC_ICON = {
    "Compute": "🖥", "Networking": "🌐", "Database": "🗄",
    "Storage": "💾", "Security": "🔒", "Analytics": "📊",
    "Containers": "📦", "Integration": "🔗", "General": "📋",
}


# ── Main application window ────────────────────────────────────────────────────

class OracleMonitorApp(tk.Tk):
    def __init__(self, api_port: int = 8000):
        super().__init__()

        self.api_port    = api_port
        self._updates    = []          # currently displayed list
        self._selected   = None        # selected record dict
        self._ui_queue   = queue.Queue()  # thread-safe UI updates

        self._configure_window()
        self._build_styles()
        self._build_menu()
        self._build_toolbar()
        self._build_paned()
        self._build_status_bar()

        # Kick off data load after UI is ready
        self.after(200, self._load_data)
        self.after(500, self._process_ui_queue)

    # ── Window setup ──────────────────────────────────────────────────────────

    def _configure_window(self):
        self.title("Oracle OCI/OIC Monitor")
        self.geometry("1400x820")
        self.minsize(900, 600)
        self.configure(bg=CLR["bg_dark"])
        try:
            self.state("zoomed")       # maximise on Windows
        except Exception:
            pass

    def _build_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".",
            background=CLR["bg_dark"],
            foreground=CLR["text"],
            fieldbackground=CLR["bg_mid"],
            troughcolor=CLR["bg_mid"],
            borderwidth=0,
        )
        style.configure("TFrame",  background=CLR["bg_dark"])
        style.configure("Sidebar.TFrame", background=CLR["bg_mid"])
        style.configure("Card.TFrame",    background=CLR["bg_card"])

        style.configure("TLabel",
            background=CLR["bg_dark"], foreground=CLR["text"], font=("Segoe UI", 10))
        style.configure("Title.TLabel",
            background=CLR["bg_card"], foreground=CLR["text_white"],
            font=("Segoe UI", 15, "bold"))
        style.configure("Sub.TLabel",
            background=CLR["bg_card"], foreground=CLR["text_dim"],
            font=("Segoe UI", 9))
        style.configure("Badge.TLabel",
            background=CLR["bg_mid"], foreground=CLR["text"],
            font=("Segoe UI", 9, "bold"), padding=(6, 2))
        style.configure("SideHeader.TLabel",
            background=CLR["bg_mid"], foreground=CLR["accent"],
            font=("Segoe UI", 11, "bold"))
        style.configure("Stat.TLabel",
            background=CLR["bg_dark"], foreground=CLR["text_dim"],
            font=("Segoe UI", 9))

        style.configure("TButton",
            background=CLR["accent"], foreground=CLR["text_white"],
            font=("Segoe UI", 9, "bold"), padding=(10, 4), relief="flat")
        style.map("TButton",
            background=[("active", "#a83626"), ("pressed", "#8c2c1e")])

        style.configure("Secondary.TButton",
            background=CLR["bg_light"], foreground=CLR["text"],
            font=("Segoe UI", 9), padding=(8, 4), relief="flat")
        style.map("Secondary.TButton",
            background=[("active", CLR["accent2"]), ("pressed", CLR["accent2"])])

        style.configure("TEntry",
            fieldbackground=CLR["bg_light"], foreground=CLR["text_white"],
            insertcolor=CLR["text_white"], font=("Segoe UI", 10), padding=(6, 4))

        style.configure("Treeview",
            background=CLR["bg_mid"], foreground=CLR["text"],
            fieldbackground=CLR["bg_mid"], rowheight=28,
            font=("Segoe UI", 9))
        style.configure("Treeview.Heading",
            background=CLR["bg_light"], foreground=CLR["accent"],
            font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview",
            background=[("selected", CLR["accent2"])],
            foreground=[("selected", CLR["text_white"])])

        style.configure("TCombobox",
            fieldbackground=CLR["bg_light"], background=CLR["bg_light"],
            foreground=CLR["text_white"], font=("Segoe UI", 9))

        style.configure("TScrollbar",
            background=CLR["bg_mid"], troughcolor=CLR["bg_dark"],
            arrowcolor=CLR["text_dim"])

        style.configure("TSeparator", background=CLR["bg_light"])

        style.configure("TNotebook", background=CLR["bg_dark"], tabmargins=[2, 4, 2, 0])
        style.configure("TNotebook.Tab",
            background=CLR["bg_mid"], foreground=CLR["text_dim"],
            font=("Segoe UI", 9), padding=(12, 5))
        style.map("TNotebook.Tab",
            background=[("selected", CLR["bg_card"])],
            foreground=[("selected", CLR["accent"])])

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self, bg=CLR["bg_mid"], fg=CLR["text"],
                          activebackground=CLR["accent"], activeforeground="white",
                          relief="flat")

        # File
        file_menu = tk.Menu(menubar, tearoff=0, bg=CLR["bg_mid"], fg=CLR["text"])
        file_menu.add_command(label="Refresh Updates",       command=self._load_data)
        file_menu.add_command(label="Trigger Crawl Now",     command=self._trigger_crawl)
        file_menu.add_command(label="Mark All as Seen",      command=self._mark_seen)
        file_menu.add_separator()
        file_menu.add_command(label="Exit",                  command=self.destroy)
        menubar.add_cascade(label="File",    menu=file_menu)

        # View
        view_menu = tk.Menu(menubar, tearoff=0, bg=CLR["bg_mid"], fg=CLR["text"])
        view_menu.add_command(label="All Updates",           command=lambda: self._filter_category("All"))
        view_menu.add_command(label="OCI Only",              command=lambda: self._filter_category("OCI"))
        view_menu.add_command(label="OIC Only",              command=lambda: self._filter_category("OIC"))
        view_menu.add_separator()
        view_menu.add_command(label="New Items Only",        command=self._show_new_only)
        view_menu.add_command(label="High Impact Only",      command=self._show_high_impact)
        menubar.add_cascade(label="View",    menu=view_menu)

        # Tools
        tools_menu = tk.Menu(menubar, tearoff=0, bg=CLR["bg_mid"], fg=CLR["text"])
        tools_menu.add_command(label="Open API Docs (browser)", command=self._open_api_docs)
        tools_menu.add_command(label="Ask AI a Question",       command=self._open_qa_dialog)
        menubar.add_cascade(label="Tools",   menu=tools_menu)

        # Help
        help_menu = tk.Menu(menubar, tearoff=0, bg=CLR["bg_mid"], fg=CLR["text"])
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help",    menu=help_menu)

        self.config(menu=menubar)

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        bar = ttk.Frame(self, style="Sidebar.TFrame", padding=(8, 6))
        bar.pack(side="top", fill="x")

        # Oracle branding
        tk.Label(bar, text="  ☁ Oracle OCI/OIC Monitor",
                 bg=CLR["bg_mid"], fg=CLR["accent"],
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=(4, 20))

        # Search box
        self._search_var = tk.StringVar()
        search_entry = ttk.Entry(bar, textvariable=self._search_var, width=36)
        search_entry.pack(side="left", padx=(0, 4))
        search_entry.bind("<Return>", lambda e: self._do_search())

        ttk.Button(bar, text="🔍 Search",
                   command=self._do_search).pack(side="left", padx=(0, 8))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)

        # Category filter
        tk.Label(bar, text="Category:", bg=CLR["bg_mid"],
                 fg=CLR["text_dim"]).pack(side="left")
        self._cat_var = tk.StringVar(value="All")
        cat_cb = ttk.Combobox(bar, textvariable=self._cat_var,
                              values=["All", "OCI", "OIC"], width=7, state="readonly")
        cat_cb.pack(side="left", padx=(4, 12))
        cat_cb.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())

        # Impact filter
        tk.Label(bar, text="Impact:", bg=CLR["bg_mid"],
                 fg=CLR["text_dim"]).pack(side="left")
        self._imp_var = tk.StringVar(value="All")
        imp_cb = ttk.Combobox(bar, textvariable=self._imp_var,
                              values=["All", "High", "Medium", "Low"], width=8, state="readonly")
        imp_cb.pack(side="left", padx=(4, 12))
        imp_cb.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(bar, text="↺ Refresh",
                   style="Secondary.TButton",
                   command=self._load_data).pack(side="left", padx=2)

        ttk.Button(bar, text="✓ Mark Seen",
                   style="Secondary.TButton",
                   command=self._mark_seen).pack(side="left", padx=2)

        ttk.Button(bar, text="▶ Crawl Now",
                   command=self._trigger_crawl).pack(side="left", padx=2)

        ttk.Button(bar, text="? Ask AI",
                   style="Secondary.TButton",
                   command=self._open_qa_dialog).pack(side="left", padx=2)

        ttk.Button(bar, text="🌐 API Docs",
                   style="Secondary.TButton",
                   command=self._open_api_docs).pack(side="right", padx=4)

    # ── Paned layout: sidebar + detail ────────────────────────────────────────

    def _build_paned(self):
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=0, pady=0)

        self._build_sidebar(paned)
        self._build_detail(paned)

    def _build_sidebar(self, paned):
        sidebar = ttk.Frame(paned, style="Sidebar.TFrame", width=300)
        paned.add(sidebar, weight=0)

        # Header
        ttk.Label(sidebar, text="  Update Subjects",
                  style="SideHeader.TLabel",
                  padding=(8, 8)).pack(fill="x")
        ttk.Separator(sidebar, orient="horizontal").pack(fill="x")

        # Stats row
        self._stats_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
        self._stats_frame.pack(fill="x", padx=8, pady=4)

        self._total_lbl = tk.Label(self._stats_frame, text="—",
            bg=CLR["bg_mid"], fg=CLR["text_dim"], font=("Segoe UI", 9))
        self._total_lbl.pack(side="left")

        self._new_lbl = tk.Label(self._stats_frame, text="",
            bg=CLR["bg_mid"], fg=CLR["accent2"], font=("Segoe UI", 9, "bold"))
        self._new_lbl.pack(side="right")

        # Search-within-tree
        tree_search_frame = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(6, 4))
        tree_search_frame.pack(fill="x")
        self._tree_search = tk.StringVar()
        e = ttk.Entry(tree_search_frame, textvariable=self._tree_search, width=28)
        e.pack(fill="x")
        e.bind("<KeyRelease>", lambda _: self._populate_tree())

        # Treeview
        tree_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
        tree_frame.pack(fill="both", expand=True, padx=4, pady=4)

        scroll = ttk.Scrollbar(tree_frame)
        scroll.pack(side="right", fill="y")

        self._tree = ttk.Treeview(tree_frame, show="tree",
                                  yscrollcommand=scroll.set, selectmode="browse")
        self._tree.pack(fill="both", expand=True)
        scroll.config(command=self._tree.yview)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_detail(self, paned):
        detail_outer = ttk.Frame(paned)
        paned.add(detail_outer, weight=1)

        notebook = ttk.Notebook(detail_outer)
        notebook.pack(fill="both", expand=True)

        # ── Tab 1: Detail view ─────────────────────────────────────────────
        detail_tab = ttk.Frame(notebook, style="Card.TFrame")
        notebook.add(detail_tab, text="  Detail View  ")

        # Title area
        title_bar = ttk.Frame(detail_tab, style="Card.TFrame", padding=(16, 12))
        title_bar.pack(fill="x")

        self._title_lbl = ttk.Label(title_bar, text="Select an item from the sidebar",
                                    style="Title.TLabel", wraplength=900)
        self._title_lbl.pack(anchor="w")

        # Metadata badges row
        meta_bar = ttk.Frame(detail_tab, style="Card.TFrame", padding=(16, 0, 16, 10))
        meta_bar.pack(fill="x")

        self._cat_badge   = tk.Label(meta_bar, text="", bg=CLR["accent"],  fg="white",
                                     font=("Segoe UI", 9, "bold"), padx=8, pady=2)
        self._svc_badge   = tk.Label(meta_bar, text="", bg=CLR["bg_light"], fg=CLR["text"],
                                     font=("Segoe UI", 9), padx=8, pady=2)
        self._imp_badge   = tk.Label(meta_bar, text="", bg=CLR["orange"],  fg="white",
                                     font=("Segoe UI", 9, "bold"), padx=8, pady=2)
        self._date_badge  = tk.Label(meta_bar, text="", bg=CLR["bg_mid"],  fg=CLR["text_dim"],
                                     font=("Segoe UI", 9), padx=8, pady=2)
        self._new_badge   = tk.Label(meta_bar, text="NEW", bg=CLR["new_badge"], fg="white",
                                     font=("Segoe UI", 9, "bold"), padx=8, pady=2)

        for badge in (self._cat_badge, self._svc_badge, self._imp_badge,
                      self._date_badge, self._new_badge):
            badge.pack(side="left", padx=(0, 6))

        ttk.Separator(detail_tab, orient="horizontal").pack(fill="x", padx=16)

        # Summary
        sum_frame = ttk.Frame(detail_tab, style="Card.TFrame", padding=(16, 10))
        sum_frame.pack(fill="x")
        ttk.Label(sum_frame, text="SUMMARY", style="Sub.TLabel").pack(anchor="w")
        self._summary_lbl = tk.Text(
            sum_frame, height=4, wrap="word",
            bg=CLR["bg_mid"], fg=CLR["text"], relief="flat",
            font=("Segoe UI", 10), state="disabled",
            insertbackground=CLR["text"], padx=8, pady=8,
        )
        self._summary_lbl.pack(fill="x")

        ttk.Separator(detail_tab, orient="horizontal").pack(fill="x", padx=16)

        # Full content (scrollable)
        content_frame = ttk.Frame(detail_tab, style="Card.TFrame", padding=(16, 8))
        content_frame.pack(fill="both", expand=True)
        ttk.Label(content_frame, text="FULL CONTENT", style="Sub.TLabel").pack(anchor="w")

        content_scroll = ttk.Scrollbar(content_frame)
        content_scroll.pack(side="right", fill="y")
        self._content_txt = tk.Text(
            content_frame, wrap="word",
            bg=CLR["bg_card"], fg=CLR["text"], relief="flat",
            font=("Segoe UI", 10), state="disabled",
            yscrollcommand=content_scroll.set,
            insertbackground=CLR["text"], padx=10, pady=10,
            spacing1=2, spacing3=4,
        )
        self._content_txt.pack(fill="both", expand=True)
        content_scroll.config(command=self._content_txt.yview)

        # Tags row
        tags_frame = ttk.Frame(detail_tab, style="Card.TFrame", padding=(16, 8))
        tags_frame.pack(fill="x")
        ttk.Label(tags_frame, text="TAGS: ", style="Sub.TLabel").pack(side="left")
        self._tags_frame_inner = ttk.Frame(tags_frame, style="Card.TFrame")
        self._tags_frame_inner.pack(side="left", fill="x")

        # Source link
        link_frame = ttk.Frame(detail_tab, style="Card.TFrame", padding=(16, 4, 16, 12))
        link_frame.pack(fill="x")
        self._source_link = tk.Label(link_frame, text="", bg=CLR["bg_card"],
                                     fg=CLR["accent2"], font=("Segoe UI", 9, "underline"),
                                     cursor="hand2")
        self._source_link.pack(anchor="w")
        self._source_link.bind("<Button-1>", self._open_source_url)

        # ── Tab 2: Updates list table ──────────────────────────────────────
        list_tab = ttk.Frame(notebook)
        notebook.add(list_tab, text="  All Updates  ")
        self._build_list_tab(list_tab)

        # ── Tab 3: Statistics ──────────────────────────────────────────────
        stats_tab = ttk.Frame(notebook)
        notebook.add(stats_tab, text="  Statistics  ")
        self._build_stats_tab(stats_tab)

    def _build_list_tab(self, parent):
        cols = ("title", "category", "service", "impact", "date", "new")
        self._list_tree = ttk.Treeview(parent, columns=cols, show="headings")

        self._list_tree.heading("title",    text="Title")
        self._list_tree.heading("category", text="Category")
        self._list_tree.heading("service",  text="Service")
        self._list_tree.heading("impact",   text="Impact")
        self._list_tree.heading("date",     text="Date")
        self._list_tree.heading("new",      text="New?")

        self._list_tree.column("title",    width=540, stretch=True)
        self._list_tree.column("category", width=70,  anchor="center")
        self._list_tree.column("service",  width=120, anchor="center")
        self._list_tree.column("impact",   width=80,  anchor="center")
        self._list_tree.column("date",     width=110, anchor="center")
        self._list_tree.column("new",      width=50,  anchor="center")

        vsb = ttk.Scrollbar(parent, orient="vertical",   command=self._list_tree.yview)
        hsb = ttk.Scrollbar(parent, orient="horizontal", command=self._list_tree.xview)
        self._list_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._list_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        self._list_tree.tag_configure("new",    background="#1a3a5c", foreground="#64b5f6")
        self._list_tree.tag_configure("high",   foreground=CLR["red"])
        self._list_tree.tag_configure("medium", foreground=CLR["orange"])
        self._list_tree.tag_configure("normal", foreground=CLR["text"])

        self._list_tree.bind("<<TreeviewSelect>>", self._on_list_select)

    def _build_stats_tab(self, parent):
        canvas = tk.Canvas(parent, bg=CLR["bg_dark"], highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)

        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._stats_content = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=self._stats_content, anchor="nw")
        self._stats_content.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self._stats_canvas = canvas

    def _build_status_bar(self):
        bar = tk.Frame(self, bg=CLR["bg_mid"], height=26)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)

        self._status_left = tk.Label(bar, text="  Initialising…",
            bg=CLR["bg_mid"], fg=CLR["text_dim"], font=("Segoe UI", 9), anchor="w")
        self._status_left.pack(side="left", padx=8)

        self._status_right = tk.Label(bar, text="",
            bg=CLR["bg_mid"], fg=CLR["accent2"], font=("Segoe UI", 9), anchor="e")
        self._status_right.pack(side="right", padx=8)

        self._crawl_indicator = tk.Label(bar, text="",
            bg=CLR["bg_mid"], fg=CLR["green"], font=("Segoe UI", 9))
        self._crawl_indicator.pack(side="right", padx=4)

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_data(self, *_):
        """Reload from DB in a background thread, push result to UI queue."""
        def _worker():
            try:
                from storage.database import get_stats, list_updates
                updates = list_updates(limit=500)
                stats   = get_stats()
                self._ui_queue.put(("data_loaded", updates, stats))
            except Exception as exc:
                log.error("Data load error: %s", exc)
                self._ui_queue.put(("error", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()
        self._set_status("Loading…")

    def _apply_filters(self, *_):
        """Re-filter _updates based on current toolbar dropdowns."""
        cat = self._cat_var.get()
        imp = self._imp_var.get()
        srch = self._search_var.get().strip().lower()

        filtered = self._updates
        if cat != "All":
            filtered = [u for u in filtered if u.get("category") == cat]
        if imp != "All":
            filtered = [u for u in filtered if u.get("impact_level") == imp]
        if srch:
            filtered = [u for u in filtered
                        if srch in (u.get("title", "") + u.get("content", "")
                                    + u.get("summary", "")).lower()]
        self._populate_tree(filtered)
        self._populate_list_tab(filtered)

    def _do_search(self):
        self._apply_filters()

    def _filter_category(self, cat: str):
        self._cat_var.set(cat)
        self._apply_filters()

    def _show_new_only(self):
        filtered = [u for u in self._updates if u.get("is_new")]
        self._populate_tree(filtered)
        self._populate_list_tab(filtered)

    def _show_high_impact(self):
        filtered = [u for u in self._updates if u.get("impact_level") == "High"]
        self._populate_tree(filtered)
        self._populate_list_tab(filtered)

    # ── Tree population ───────────────────────────────────────────────────────

    def _populate_tree(self, updates: Optional[list] = None):
        if updates is None:
            updates = self._updates

        # Filter by tree search box
        srch = self._tree_search.get().strip().lower()
        if srch:
            updates = [u for u in updates if srch in u.get("title", "").lower()]

        self._tree.delete(*self._tree.get_children())
        self._node_map = {}   # tree_iid → record dict

        # Group: Category → Service → items
        groups: dict[str, dict[str, list]] = {}
        for upd in updates:
            cat = upd.get("category", "Other")
            svc = upd.get("service",  "General")
            groups.setdefault(cat, {}).setdefault(svc, []).append(upd)

        for cat in sorted(groups):
            icon     = CAT_ICON.get(cat, "☁")
            svc_map  = groups[cat]
            total    = sum(len(v) for v in svc_map.values())
            cat_node = self._tree.insert(
                "", "end",
                text=f" {icon} {cat}  ({total})",
                open=True,
                tags=("category",),
            )
            self._tree.tag_configure("category",
                foreground=CLR["accent"], font=("Segoe UI", 10, "bold"))

            for svc in sorted(svc_map):
                items     = svc_map[svc]
                svc_icon  = SVC_ICON.get(svc, "📋")
                new_count = sum(1 for i in items if i.get("is_new"))
                new_txt   = f"  ✦ {new_count} new" if new_count else ""
                svc_node  = self._tree.insert(
                    cat_node, "end",
                    text=f"  {svc_icon} {svc}  ({len(items)}){new_txt}",
                    open=True,
                    tags=("service",),
                )
                self._tree.tag_configure("service",
                    foreground=CLR["accent2"], font=("Segoe UI", 9, "bold"))

                for item in sorted(items, key=lambda x: x.get("crawled_at", ""), reverse=True):
                    prefix = "● " if item.get("is_new") else "  "
                    impact = item.get("impact_level", "")
                    tag    = f"impact_{impact.lower()}" if impact else "item"

                    iid = self._tree.insert(
                        svc_node, "end",
                        text=f"    {prefix}{item['title'][:60]}",
                        tags=(tag,),
                    )
                    self._tree.tag_configure("impact_high",   foreground=CLR["red"])
                    self._tree.tag_configure("impact_medium", foreground=CLR["orange"])
                    self._tree.tag_configure("impact_low",    foreground=CLR["green"])
                    self._tree.tag_configure("item",          foreground=CLR["text"])
                    self._node_map[iid] = item

    def _populate_list_tab(self, updates: Optional[list] = None):
        if updates is None:
            updates = self._updates

        self._list_tree.delete(*self._list_tree.get_children())
        for upd in updates:
            date_str = ""
            if upd.get("release_date"):
                try:
                    d = datetime.fromisoformat(upd["release_date"])
                    date_str = d.strftime("%Y-%m-%d")
                except Exception:
                    date_str = str(upd["release_date"])[:10]

            tags = []
            if upd.get("is_new"):
                tags.append("new")
            impact = upd.get("impact_level", "")
            if impact == "High":
                tags.append("high")
            elif impact == "Medium":
                tags.append("medium")
            else:
                tags.append("normal")

            iid = self._list_tree.insert("", "end",
                values=(
                    upd["title"][:100],
                    upd.get("category", ""),
                    upd.get("service", ""),
                    impact or "—",
                    date_str or "—",
                    "✦" if upd.get("is_new") else "",
                ),
                tags=tags,
                iid=str(upd.get("id", "")),
            )

    def _populate_stats_tab(self, stats: dict):
        for w in self._stats_content.winfo_children():
            w.destroy()

        def section(title):
            tk.Label(self._stats_content, text=title,
                     bg=CLR["bg_dark"], fg=CLR["accent"],
                     font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
            ttk.Separator(self._stats_content).pack(fill="x", padx=12, pady=2)

        def row(label, value, color=None):
            f = tk.Frame(self._stats_content, bg=CLR["bg_dark"])
            f.pack(fill="x", padx=20, pady=2)
            tk.Label(f, text=label, bg=CLR["bg_dark"], fg=CLR["text_dim"],
                     font=("Segoe UI", 10), width=28, anchor="w").pack(side="left")
            tk.Label(f, text=str(value), bg=CLR["bg_dark"],
                     fg=color or CLR["text_white"],
                     font=("Segoe UI", 10, "bold")).pack(side="left")

        section("Overview")
        row("Total Updates",   stats.get("total", 0))
        row("New (unread)",    stats.get("new", 0),   CLR["accent2"])

        section("By Category")
        for cat, cnt in stats.get("by_category", {}).items():
            row(f"  {CAT_ICON.get(cat, '☁')} {cat}", cnt)

        section("By Service")
        for svc, cnt in sorted(stats.get("by_service", {}).items()):
            row(f"  {SVC_ICON.get(svc, '📋')} {svc}", cnt)

        section("By Impact Level")
        for lvl, cnt in stats.get("by_impact", {}).items():
            clr = IMPACT_CLR.get(lvl, CLR["text"])
            row(f"  {lvl or 'Unknown'}", cnt, clr)

        last = stats.get("last_run")
        if last:
            section("Last Crawl Run")
            row("Status",         last.get("status", "—"))
            row("Sources tried",  last.get("sources_tried", 0))
            row("Updates found",  last.get("updates_found", 0))
            row("New updates",    last.get("updates_new", 0))
            if last.get("completed_at"):
                try:
                    d = datetime.fromisoformat(last["completed_at"])
                    row("Completed at",   d.strftime("%Y-%m-%d %H:%M UTC"))
                except Exception:
                    row("Completed at",   last["completed_at"])

    # ── Detail view ───────────────────────────────────────────────────────────

    def _show_detail(self, record: dict):
        self._selected = record

        # Title
        self._title_lbl.config(text=record.get("title", "—"))

        # Badges
        cat    = record.get("category",     "")
        svc    = record.get("service",      "")
        impact = record.get("impact_level", "")
        is_new = record.get("is_new",       False)
        rdate  = record.get("release_date", "")

        self._cat_badge.config(text=f" {CAT_ICON.get(cat, '☁')} {cat} ",
                               bg=CLR["accent"] if cat == "OCI" else "#1b5e20")
        self._svc_badge.config(text=f" {SVC_ICON.get(svc, '📋')} {svc} ")

        imp_bg = IMPACT_CLR.get(impact, CLR["text_dim"])
        self._imp_badge.config(text=f" {impact or '—'} ", bg=imp_bg)

        date_str = "—"
        if rdate:
            try:
                d = datetime.fromisoformat(rdate)
                date_str = d.strftime("%b %d, %Y")
            except Exception:
                date_str = str(rdate)[:10]
        self._date_badge.config(text=f" 📅 {date_str} ")

        if is_new:
            self._new_badge.pack(side="left", padx=(0, 6))
        else:
            self._new_badge.pack_forget()

        # Summary
        summary = record.get("summary") or "No summary available."
        self._summary_lbl.config(state="normal")
        self._summary_lbl.delete("1.0", "end")
        self._summary_lbl.insert("end", summary)
        self._summary_lbl.config(state="disabled")

        # Full content
        content = record.get("content", "No content available.")
        self._content_txt.config(state="normal")
        self._content_txt.delete("1.0", "end")
        self._content_txt.insert("end", content)
        self._content_txt.config(state="disabled")
        self._content_txt.yview_moveto(0)

        # Tags
        for w in self._tags_frame_inner.winfo_children():
            w.destroy()
        tags = record.get("tags", [])
        for tag in tags:
            tk.Label(self._tags_frame_inner, text=f" {tag} ",
                     bg=CLR["bg_light"], fg=CLR["text"],
                     font=("Segoe UI", 8), relief="flat",
                     padx=4, pady=1).pack(side="left", padx=2)

        # Source link
        url = record.get("source_url", "")
        self._source_link.config(text=f"🔗 {url}")
        self._source_link._url = url

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_tree_select(self, event):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        record = self._node_map.get(iid)
        if record:
            self._show_detail(record)

    def _on_list_select(self, event):
        sel = self._list_tree.selection()
        if not sel:
            return
        try:
            rid = int(sel[0])
            for upd in self._updates:
                if upd.get("id") == rid:
                    self._show_detail(upd)
                    break
        except (ValueError, TypeError):
            pass

    def _open_source_url(self, event):
        url = getattr(self._source_link, "_url", "")
        if url and url.startswith("http"):
            webbrowser.open(url)

    def _trigger_crawl(self):
        self._crawl_indicator.config(text="● Crawling…", fg=CLR["orange"])
        self._set_status("Crawling Oracle documentation…")

        def _worker():
            try:
                from crawler.scheduler import run_crawl
                result = run_crawl(seed_mock=True)
                self._ui_queue.put(("crawl_done", result))
            except Exception as exc:
                log.error("Crawl error: %s", exc)
                self._ui_queue.put(("crawl_error", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()

    def _mark_seen(self):
        def _worker():
            try:
                from storage.database import mark_all_seen
                n = mark_all_seen()
                self._ui_queue.put(("marked_seen", n))
            except Exception as exc:
                self._ui_queue.put(("error", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()

    def _open_api_docs(self):
        webbrowser.open(f"http://127.0.0.1:{self.api_port}/docs")

    def _open_qa_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Ask AI about Oracle Updates")
        dialog.geometry("700x420")
        dialog.configure(bg=CLR["bg_dark"])
        dialog.grab_set()

        ttk.Label(dialog, text="Ask a question about Oracle OCI/OIC updates:",
                  padding=(16, 12)).pack(anchor="w")

        question_entry = ttk.Entry(dialog, font=("Segoe UI", 11), width=80)
        question_entry.pack(fill="x", padx=16, pady=(0, 8))
        question_entry.focus()

        answer_txt = tk.Text(dialog, height=14, wrap="word",
                             bg=CLR["bg_mid"], fg=CLR["text"],
                             font=("Segoe UI", 10), state="disabled",
                             relief="flat", padx=10, pady=10)
        answer_txt.pack(fill="both", expand=True, padx=16)

        btn_bar = ttk.Frame(dialog)
        btn_bar.pack(fill="x", padx=16, pady=8)

        def ask():
            q = question_entry.get().strip()
            if not q:
                return
            answer_txt.config(state="normal")
            answer_txt.delete("1.0", "end")
            answer_txt.insert("end", "Thinking…")
            answer_txt.config(state="disabled")

            def _worker():
                from processor.summarizer import ask as qa_ask
                ans = qa_ask(q)
                dialog.after(0, lambda: _set_answer(ans))

            threading.Thread(target=_worker, daemon=True).start()

        def _set_answer(ans: str):
            answer_txt.config(state="normal")
            answer_txt.delete("1.0", "end")
            answer_txt.insert("end", ans)
            answer_txt.config(state="disabled")

        ttk.Button(btn_bar, text="Ask", command=ask).pack(side="left", padx=(0, 8))
        ttk.Button(btn_bar, text="Close",
                   style="Secondary.TButton",
                   command=dialog.destroy).pack(side="left")

        question_entry.bind("<Return>", lambda e: ask())

    def _show_about(self):
        messagebox.showinfo(
            "About Oracle OCI/OIC Monitor",
            "Oracle OCI/OIC Monitor v1.0\n\n"
            "Monitors Oracle Cloud Infrastructure and Oracle Integration Cloud\n"
            "release notes and What's New pages.\n\n"
            "Stack: Python • LangChain • SQLite • FastAPI • Tkinter\n\n"
            "• Automatic crawling on configurable schedule\n"
            "• AI-powered classification and summarisation\n"
            "• Semantic search with local embeddings\n"
            "• REST API at http://127.0.0.1:8000/docs",
        )

    # ── Status helpers ────────────────────────────────────────────────────────

    def _set_status(self, msg: str, right: str = ""):
        self._status_left.config(text=f"  {msg}")
        if right:
            self._status_right.config(text=right)

    # ── UI queue processor (runs on main thread via .after) ───────────────────

    def _process_ui_queue(self):
        try:
            while True:
                msg = self._ui_queue.get_nowait()
                self._handle_ui_msg(msg)
        except queue.Empty:
            pass
        finally:
            self.after(300, self._process_ui_queue)

    def _handle_ui_msg(self, msg: tuple):
        kind = msg[0]

        if kind == "data_loaded":
            _, updates, stats = msg
            self._updates = updates
            self._populate_tree(updates)
            self._populate_list_tab(updates)
            self._populate_stats_tab(stats)

            total = stats.get("total", 0)
            new   = stats.get("new",   0)
            self._total_lbl.config(text=f"{total} updates")
            self._new_lbl.config(text=f"  ✦ {new} new" if new else "")
            self._set_status(
                f"Loaded {total} updates",
                f"New: {new}" if new else "",
            )
            self._crawl_indicator.config(text="● Ready", fg=CLR["green"])

        elif kind == "crawl_done":
            _, result = msg
            n   = result.get("updates_new", 0)
            tot = result.get("updates_found", 0)
            self._crawl_indicator.config(text="● Ready", fg=CLR["green"])
            self._set_status(
                f"Crawl complete — {tot} found, {n} new",
                datetime.now().strftime("%H:%M"),
            )
            self._load_data()

        elif kind == "crawl_error":
            _, err = msg
            self._crawl_indicator.config(text="● Error", fg=CLR["red"])
            self._set_status(f"Crawl error: {err[:80]}")

        elif kind == "marked_seen":
            _, n = msg
            self._set_status(f"Marked {n} updates as seen")
            self._load_data()

        elif kind == "error":
            _, err = msg
            self._set_status(f"Error: {err[:100]}")

        elif kind == "new_updates":
            _, n = msg
            self._crawl_indicator.config(text=f"● {n} new", fg=CLR["accent2"])
            self._load_data()


def launch_ui(api_port: int = 8000) -> None:
    """Create and run the Tkinter application (call from main thread)."""
    app = OracleMonitorApp(api_port=api_port)
    app.mainloop()
