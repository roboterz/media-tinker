import os
import sys
import subprocess
import re

def _ensure_requirements():
    try:
        import imageio_ffmpeg
    except ImportError:
        req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'requirements.txt')
        if os.path.exists(req_file):
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            try:
                subprocess.check_call(
                    [sys.executable, '-m', 'pip', 'install', '-q', '-r', req_file],
                    startupinfo=startupinfo
                )
            except Exception:
                pass

_ensure_requirements()

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import queue
import imageio_ffmpeg

from i18n import i18n, t

try:
    import windnd
except ImportError:
    windnd = None

__version__ = "1.0.051"


class AudioRemoverApp:
    VERSION = __version__

    def __init__(self, root):
        self.root = root
        self.i18n = i18n
        self.root.title(t("app.title", version=__version__))
        self.root.geometry("880x680")
        self.root.minsize(820, 600)

        self.ui_queue = queue.Queue()
        self._check_ui_queue()

        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        self.file_queue = {}  # item_id -> dict(path, name, status, size, duration, media_info)
        self.current_selected_item_id = None
        self.current_selected_path = None
        self.current_media_info = None
        self.has_video = False
        self.is_processing = False
        self._cancel_event = threading.Event()
        self._current_process = None
        self.file_path_var = tk.StringVar()
        self._detected_hw_results = None

        # Serialized probe queue to prevent concurrent subprocess/GIL clashes
        self.probe_queue = queue.Queue()
        self._probing_paths = set()
        self._ffmpeg_probe_lock = threading.Lock()
        self._start_probe_worker()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        if windnd:
            try:
                windnd.hook_dropfiles(self.root, func=self.on_drop_files)
            except Exception:
                pass

        # Style
        style = ttk.Style()
        style.configure("TButton", padding=5)
        style.configure("TLabel", padding=3)

        # Top Menu Bar
        self._create_menu_bar()

        # Main Layout Container (Left: Controls, Right: Media Info Sidebar)
        main_container = ttk.Frame(root, padding=8)
        main_container.pack(fill="both", expand=True)

        left_container = ttk.Frame(main_container)
        left_container.pack(side="left", fill="both", expand=True, padx=(0, 5))

        # --- Right Sidebar: Source Media Info ---
        self.sidebar_frame = ttk.LabelFrame(main_container, text=t("sidebar.title"), padding=8)
        self.sidebar_frame.pack(side="right", fill="both", expand=False, padx=(5, 0))
        self.sidebar_frame.config(width=260)

        self._build_sidebar(self.sidebar_frame)

        # --- Left Container Controls ---
        # File Queue Frame
        self.files_frame = ttk.LabelFrame(left_container, text=t("queue.title"), padding=8)
        self.files_frame.pack(fill="both", expand=True, pady=(0, 6))

        # Treeview + Scrollbar container
        tree_container = ttk.Frame(self.files_frame)
        tree_container.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            tree_container,
            columns=("name", "size", "duration", "status"),
            show="headings",
            selectmode="extended",
            height=5
        )
        self.tree.heading("name", text=t("queue.col_name"))
        self.tree.heading("size", text=t("queue.col_size"))
        self.tree.heading("duration", text=t("queue.col_duration"))
        self.tree.heading("status", text=t("queue.col_status"))

        self.tree.column("name", width=250, minwidth=140, anchor="w")
        self.tree.column("size", width=80, minwidth=60, anchor="center")
        self.tree.column("duration", width=80, minwidth=60, anchor="center")
        self.tree.column("status", width=110, minwidth=90, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # Toolbar below treeview
        toolbar_frame = ttk.Frame(self.files_frame)
        toolbar_frame.pack(fill="x", pady=(6, 0))

        self.btn_add = ttk.Button(toolbar_frame, text=t("queue.btn_add"), command=self.browse_files)
        self.btn_add.pack(side="left", padx=(0, 4))
        self.btn_browse = self.btn_add  # compatibility alias

        self.btn_remove = ttk.Button(toolbar_frame, text=t("queue.btn_remove"), command=self.remove_selected_files)
        self.btn_remove.pack(side="left", padx=4)

        self.btn_clear = ttk.Button(toolbar_frame, text=t("queue.btn_clear"), command=self.clear_file_queue)
        self.btn_clear.pack(side="left", padx=4)

        # Language dropdown selector in UI
        self.cbo_lang = ttk.Combobox(
            toolbar_frame,
            values=list(self.i18n.SUPPORTED_LOCALES.values()),
            state="readonly",
            width=9,
            font=("Segoe UI", 8)
        )
        self.cbo_lang.set(self.i18n.SUPPORTED_LOCALES.get(self.i18n.get_locale(), "简体中文"))
        self.cbo_lang.bind("<<ComboboxSelected>>", self._on_lang_combo_selected)
        self.cbo_lang.pack(side="right", padx=(2, 0))

        self.lbl_lang_icon = ttk.Label(toolbar_frame, text="🌐", font=("Segoe UI", 9))
        self.lbl_lang_icon.pack(side="right", padx=(4, 0))

        self.lbl_queue_count = ttk.Label(toolbar_frame, text=t("queue.count_empty"), foreground="#666666", font=("Segoe UI", 8))
        self.lbl_queue_count.pack(side="right", padx=(4, 6))

        # Context Menu & Keybindings for Treeview
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selection_changed)
        self.tree.bind("<Delete>", lambda e: self.remove_selected_files())
        self.tree.bind("<BackSpace>", lambda e: self.remove_selected_files())

        self.tree_menu = tk.Menu(self.root, tearoff=0)
        self.tree_menu.add_command(label=t("menu.remove_selected"), command=self.remove_selected_files)
        self.tree_menu.add_command(label=t("menu.clear_all"), command=self.clear_file_queue)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label=t("menu.reset_status"), command=self.reset_selected_status)
        self.tree_menu.add_command(label=t("menu.reset_all"), command=self.reset_all_status)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label=t("menu.open_folder"), command=self._open_selected_file_folder)

        def show_context_menu(event):
            row_id = self.tree.identify_row(event.y)
            if row_id and row_id not in self.tree.selection():
                self.tree.selection_set(row_id)
                self._on_tree_selection_changed()
            has_sel = bool(self.tree.selection())
            has_items = bool(self.tree.get_children())
            state_sel = "normal" if has_sel and not self.is_processing else "disabled"
            state_items = "normal" if has_items and not self.is_processing else "disabled"

            self.tree_menu.entryconfig(0, state=state_sel)
            self.tree_menu.entryconfig(1, state=state_items)
            self.tree_menu.entryconfig(3, state=state_sel)
            self.tree_menu.entryconfig(4, state=state_items)
            self.tree_menu.entryconfig(6, state=state_sel)
            self.tree_menu.post(event.x_root, event.y_root)

        self.tree.bind("<Button-3>", show_context_menu)

        # Options Frame
        self.opts_frame = ttk.LabelFrame(left_container, text=t("options.title"), padding=10)
        self.opts_frame.pack(fill="x", pady=5)

        # Convert Options
        self.convert_var = tk.StringVar(value="None")
        self.convert_var.trace_add("write", lambda *args: self._update_resolution_state())

        self.convert_frame = ttk.Frame(self.opts_frame)
        self.convert_frame.pack(fill="x", pady=(0, 10))

        self.lbl_convert_to = ttk.Label(self.convert_frame, text=t("options.convert_to"))
        self.lbl_convert_to.pack(side="left")
        ttk.Radiobutton(self.convert_frame, text="None", variable=self.convert_var, value="None").pack(side="left", padx=5)
        ttk.Radiobutton(self.convert_frame, text="MP4", variable=self.convert_var, value="MP4").pack(side="left", padx=5)
        ttk.Radiobutton(self.convert_frame, text="MP3", variable=self.convert_var, value="MP3").pack(side="left", padx=5)
        ttk.Radiobutton(self.convert_frame, text="FLAC", variable=self.convert_var, value="FLAC").pack(side="left", padx=5)

        # Video/Audio Options (Resolution & Bitrate)
        self.res_frame = ttk.Frame(self.opts_frame)
        self.res_frame.pack(fill="x", pady=(0, 10))

        self.lbl_resolution = ttk.Label(self.res_frame, text=t("options.resolution"))
        self.lbl_resolution.pack(side="left")
        self.resolution_var = tk.StringVar(value="Original")
        self.cbo_resolution = ttk.Combobox(
            self.res_frame,
            textvariable=self.resolution_var,
            values=["Original", "144p", "240p", "360p", "480p", "720p", "1080p", "1440p"],
            state="disabled",
            width=10
        )
        self.cbo_resolution.pack(side="left", padx=(5, 15))

        self.lbl_bitrate = ttk.Label(self.res_frame, text=t("options.bitrate"))
        self.lbl_bitrate.pack(side="left")
        self.bitrate_var = tk.StringVar(value="Auto")
        self.cbo_bitrate = ttk.Combobox(
            self.res_frame,
            textvariable=self.bitrate_var,
            values=["Auto", "150k", "300k", "500k", "800k", "1M", "1.5M", "2M", "3M", "5M", "8M"],
            state="disabled",
            width=10
        )
        self.cbo_bitrate.pack(side="left", padx=5)

        # Encoder Options (Hardware Acceleration)
        self.enc_frame = ttk.Frame(self.opts_frame)
        self.enc_frame.pack(fill="x", pady=(0, 10))

        self.lbl_encoder = ttk.Label(self.enc_frame, text=t("options.encoder"))
        self.lbl_encoder.pack(side="left")
        self.encoder_var = tk.StringVar(value=t("options.encoder_auto"))
        self.cbo_encoder = ttk.Combobox(
            self.enc_frame,
            textvariable=self.encoder_var,
            values=[t("options.encoder_auto"), t("options.encoder_cpu")],
            state="disabled",
            width=22
        )
        self.cbo_encoder.pack(side="left", padx=5)

        self.lbl_gpu_status = ttk.Label(self.enc_frame, text=t("options.detecting_gpu"), foreground="#666666", font=("Segoe UI", 8))
        self.lbl_gpu_status.pack(side="left", padx=(5, 0))

        # Initialize hardware encoder state and detect
        self.available_hw_encoders = []
        self._detect_hw_encoders_async()

        # Mute Option
        self.mute_var = tk.BooleanVar(value=False)
        self.chk_mute = ttk.Checkbutton(self.opts_frame, text=t("options.mute"), variable=self.mute_var)
        self.chk_mute.pack(anchor="w", pady=(0, 5))

        # Trim Option
        self.trim_var = tk.BooleanVar(value=False)
        self.chk_trim = ttk.Checkbutton(self.opts_frame, text=t("options.trim"), variable=self.trim_var, command=self.toggle_trim)
        self.chk_trim.pack(anchor="w", pady=(0, 5))

        self.time_frame = ttk.Frame(self.opts_frame)
        self.time_frame.pack(fill="x", padx=20)

        self.lbl_start_time = ttk.Label(self.time_frame, text=t("options.start_time"))
        self.lbl_start_time.pack(side="left")
        self.start_time_var = tk.StringVar(value="00:00:00")
        self.entry_start = ttk.Entry(self.time_frame, textvariable=self.start_time_var, width=10, state="disabled")
        self.entry_start.pack(side="left", padx=(5, 20))

        self.lbl_end_time = ttk.Label(self.time_frame, text=t("options.end_time"))
        self.lbl_end_time.pack(side="left")
        self.end_time_var = tk.StringVar(value="00:00:10")
        self.entry_end = ttk.Entry(self.time_frame, textvariable=self.end_time_var, width=10, state="disabled")
        self.entry_end.pack(side="left", padx=5)

        # Target Output Estimation Preview
        self.preview_frame = ttk.Frame(self.opts_frame)
        self.preview_frame.pack(fill="x", pady=(8, 2))
        self.lbl_target_preview = ttk.Label(
            self.preview_frame,
            text="",
            font=("Segoe UI", 9),
            foreground="#0066cc",
            wraplength=480
        )
        self.lbl_target_preview.pack(anchor="w")

        # Traces for real-time target feedback
        self.resolution_var.trace_add("write", lambda *args: self._update_target_preview())
        self.bitrate_var.trace_add("write", lambda *args: self._update_target_preview())
        self.mute_var.trace_add("write", lambda *args: self._update_target_preview())
        self.encoder_var.trace_add("write", lambda *args: self._update_target_preview())

        # Operations Frame
        self.ops_frame = ttk.Frame(left_container, padding=6)
        self.ops_frame.pack(fill="x", expand=False, pady=4)

        self.status_var = tk.StringVar(value=t("ops.ready"))
        self.lbl_status = ttk.Label(self.ops_frame, textvariable=self.status_var, font=("Segoe UI", 10), wraplength=520)
        self.lbl_status.pack(pady=6)

        self.progress = ttk.Progressbar(self.ops_frame, mode='determinate', maximum=100)
        self.progress.pack(fill="x", pady=6)

        self.btn_frame = ttk.Frame(self.ops_frame)
        self.btn_frame.pack(pady=6)

        self.btn_process = ttk.Button(self.btn_frame, text=t("ops.process"), command=self.start_batch_processing)
        self.btn_process.pack(side="left", padx=5)

        self.btn_cancel = ttk.Button(self.btn_frame, text=t("ops.cancel"), command=self.cancel_processing, state="disabled")
        self.btn_cancel.pack(side="left", padx=5)

        # Footer
        self.lbl_footer = ttk.Label(root, text=t("ops.footer"), font=("Segoe UI", 8))
        self.lbl_footer.pack(side="bottom", pady=5)

        # Register i18n callback
        self.i18n.register_callback(self._on_locale_changed)

    def _create_menu_bar(self):
        self.menubar = tk.Menu(self.root)

        # File Menu
        self.file_menu = tk.Menu(self.menubar, tearoff=0)
        self.file_menu.add_command(label=t("menu.add_files"), command=self.browse_files)
        self.file_menu.add_command(label=t("menu.clear_queue"), command=self.clear_file_queue)
        self.file_menu.add_separator()
        self.file_menu.add_command(label=t("menu.exit"), command=self.on_closing)
        self.menubar.add_cascade(label=t("menu.file"), menu=self.file_menu)

        # Language Menu
        self.lang_menu = tk.Menu(self.menubar, tearoff=0)
        self.lang_var = tk.StringVar(value=self.i18n.get_locale())
        for code, name in self.i18n.SUPPORTED_LOCALES.items():
            self.lang_menu.add_radiobutton(
                label=name,
                variable=self.lang_var,
                value=code,
                command=lambda c=code: self.change_language(c)
            )
        self.menubar.add_cascade(label=t("menu.language"), menu=self.lang_menu)

        self.root.config(menu=self.menubar)

    def _on_lang_combo_selected(self, event=None):
        selected_display = self.cbo_lang.get()
        for code, name in self.i18n.SUPPORTED_LOCALES.items():
            if name == selected_display:
                self.change_language(code)
                break

    def change_language(self, locale_code):
        if locale_code != self.i18n.get_locale():
            self.i18n.set_locale(locale_code)

    def _on_locale_changed(self, locale_code):
        self.lang_var.set(locale_code)
        display_name = self.i18n.SUPPORTED_LOCALES.get(locale_code, "English")
        self.cbo_lang.set(display_name)
        self._update_ui_language()

    def _update_ui_language(self):
        # Window title
        self.root.title(t("app.title", version=self.VERSION))

        # Menubar
        try:
            self.menubar.entryconfig(1, label=t("menu.file"))
            self.menubar.entryconfig(2, label=t("menu.language"))
            self.file_menu.entryconfig(0, label=t("menu.add_files"))
            self.file_menu.entryconfig(1, label=t("menu.clear_queue"))
            self.file_menu.entryconfig(3, label=t("menu.exit"))
        except Exception:
            pass

        # Sidebar
        self.sidebar_frame.config(text=t("sidebar.title"))
        self.lbl_sec_general.config(text=t("sidebar.general"))
        self.lbl_title_name.config(text=t("sidebar.name"))
        self.lbl_title_size.config(text=t("sidebar.size"))
        self.lbl_title_dur.config(text=t("sidebar.duration"))
        self.lbl_title_br.config(text=t("sidebar.bitrate"))

        self.lbl_sec_video.config(text=t("sidebar.video"))
        self.lbl_title_vcodec.config(text=t("sidebar.codec"))
        self.lbl_title_res.config(text=t("sidebar.resolution"))
        self.lbl_title_fps.config(text=t("sidebar.fps"))

        self.lbl_sec_audio.config(text=t("sidebar.audio"))
        self.lbl_title_acodec.config(text=t("sidebar.codec"))
        self.lbl_title_sr.config(text=t("sidebar.sample_rate"))
        self.lbl_title_ch.config(text=t("sidebar.channels"))

        if not self.current_media_info:
            self._clear_media_info()
        else:
            self._display_media_info(self.current_media_info)

        # File Queue
        self.files_frame.config(text=t("queue.title"))
        self.tree.heading("name", text=t("queue.col_name"))
        self.tree.heading("size", text=t("queue.col_size"))
        self.tree.heading("duration", text=t("queue.col_duration"))
        self.tree.heading("status", text=t("queue.col_status"))

        self.btn_add.config(text=t("queue.btn_add"))
        self.btn_remove.config(text=t("queue.btn_remove"))
        self.btn_clear.config(text=t("queue.btn_clear"))
        self._update_queue_summary()

        # Context Menu
        try:
            self.tree_menu.entryconfig(0, label=t("menu.remove_selected"))
            self.tree_menu.entryconfig(1, label=t("menu.clear_all"))
            self.tree_menu.entryconfig(3, label=t("menu.reset_status"))
            self.tree_menu.entryconfig(4, label=t("menu.reset_all"))
            self.tree_menu.entryconfig(6, label=t("menu.open_folder"))
        except Exception:
            pass

        # Update status in tree for existing items
        for item_id, data in self.file_queue.items():
            st = data.get("status", "")
            if "Pending" in st or "待处理" in st:
                data["status"] = "Pending"
                try:
                    self.tree.set(item_id, "status", t("queue.status_pending"))
                except Exception:
                    pass
            elif "Done" in st or "完成" in st:
                data["status"] = "Done"
                try:
                    self.tree.set(item_id, "status", t("queue.status_done"))
                except Exception:
                    pass
            elif "Failed" in st or "失败" in st:
                data["status"] = "Failed"
                try:
                    self.tree.set(item_id, "status", t("queue.status_failed"))
                except Exception:
                    pass
            elif "Cancelled" in st or "取消" in st:
                data["status"] = "Cancelled"
                try:
                    self.tree.set(item_id, "status", t("queue.status_cancelled"))
                except Exception:
                    pass

        # Options Frame
        self.opts_frame.config(text=t("options.title"))
        self.lbl_convert_to.config(text=t("options.convert_to"))
        self.lbl_resolution.config(text=t("options.resolution"))
        self.lbl_bitrate.config(text=t("options.bitrate"))
        self.lbl_encoder.config(text=t("options.encoder"))
        self.chk_mute.config(text=t("options.mute"))
        self.chk_trim.config(text=t("options.trim"))
        self.lbl_start_time.config(text=t("options.start_time"))
        self.lbl_end_time.config(text=t("options.end_time"))

        self._update_encoder_display()
        self._update_target_preview()

        # Operations
        self.btn_process.config(text=t("ops.process"))
        self.btn_cancel.config(text=t("ops.cancel"))
        self.lbl_footer.config(text=t("ops.footer"))

        if not self.is_processing and ("Ready" in self.status_var.get() or "就绪" in self.status_var.get()):
            self.status_var.set(t("ops.ready"))

    def _build_sidebar(self, parent):
        info_inner = ttk.Frame(parent)
        info_inner.pack(fill="both", expand=True)

        def add_row(row_idx, label_text):
            lbl_title = ttk.Label(info_inner, text=label_text, font=("Segoe UI", 9, "bold"))
            lbl_title.grid(row=row_idx, column=0, sticky="nw", pady=2)
            lbl_val = ttk.Label(info_inner, text="-", font=("Segoe UI", 9), wraplength=160)
            lbl_val.grid(row=row_idx, column=1, sticky="nw", padx=(5, 0), pady=2)
            return lbl_title, lbl_val

        # General Section
        self.lbl_sec_general = ttk.Label(info_inner, text=t("sidebar.general"), font=("Segoe UI", 9, "bold"), foreground="#0066cc")
        self.lbl_sec_general.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.lbl_title_name, self.lbl_info_name = add_row(1, t("sidebar.name"))
        self.lbl_title_size, self.lbl_info_size = add_row(2, t("sidebar.size"))
        self.lbl_title_dur, self.lbl_info_dur = add_row(3, t("sidebar.duration"))
        self.lbl_title_br, self.lbl_info_br = add_row(4, t("sidebar.bitrate"))

        # Separator
        ttk.Separator(info_inner, orient="horizontal").grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)

        # Video Section
        self.lbl_sec_video = ttk.Label(info_inner, text=t("sidebar.video"), font=("Segoe UI", 9, "bold"), foreground="#0066cc")
        self.lbl_sec_video.grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.lbl_title_vcodec, self.lbl_info_vcodec = add_row(7, t("sidebar.codec"))
        self.lbl_title_res, self.lbl_info_res = add_row(8, t("sidebar.resolution"))
        self.lbl_title_fps, self.lbl_info_fps = add_row(9, t("sidebar.fps"))

        # Separator
        ttk.Separator(info_inner, orient="horizontal").grid(row=10, column=0, columnspan=2, sticky="ew", pady=8)

        # Audio Section
        self.lbl_sec_audio = ttk.Label(info_inner, text=t("sidebar.audio"), font=("Segoe UI", 9, "bold"), foreground="#0066cc")
        self.lbl_sec_audio.grid(row=11, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.lbl_title_acodec, self.lbl_info_acodec = add_row(12, t("sidebar.codec"))
        self.lbl_title_sr, self.lbl_info_sr = add_row(13, t("sidebar.sample_rate"))
        self.lbl_title_ch, self.lbl_info_ch = add_row(14, t("sidebar.channels"))

    def _clear_media_info(self):
        self.lbl_info_name.config(text="-")
        self.lbl_info_size.config(text="-")
        self.lbl_info_dur.config(text="-")
        self.lbl_info_br.config(text="-")
        self.lbl_info_vcodec.config(text="-")
        self.lbl_info_res.config(text="-")
        self.lbl_info_fps.config(text="-")
        self.lbl_info_acodec.config(text="-")
        self.lbl_info_sr.config(text="-")
        self.lbl_info_ch.config(text="-")
        self.has_video = False
        self.current_media_info = None
        self._update_resolution_state()
        self._update_target_preview()

    def _display_media_info(self, info):
        if not info:
            return
        if self.current_selected_path and info.get("filepath") != self.current_selected_path:
            return

        self.current_media_info = info
        self.lbl_info_name.config(text=info.get("filename", "-"))
        self.lbl_info_size.config(text=info.get("filesize", "-"))
        self.lbl_info_dur.config(text=info.get("duration", "-"))
        self.lbl_info_br.config(text=info.get("bitrate", "-"))

        none_txt = t("sidebar.none")
        if info.get("has_video"):
            self.lbl_info_vcodec.config(text=info.get("video_codec", "-"))
            self.lbl_info_res.config(text=info.get("resolution", "-"))
            self.lbl_info_fps.config(text=info.get("fps", "-"))
        else:
            self.lbl_info_vcodec.config(text=none_txt)
            self.lbl_info_res.config(text=none_txt)
            self.lbl_info_fps.config(text=none_txt)

        if info.get("has_audio"):
            self.lbl_info_acodec.config(text=info.get("audio_codec", "-"))
            self.lbl_info_sr.config(text=info.get("sample_rate", "-"))
            self.lbl_info_ch.config(text=info.get("channels", "-"))
        else:
            self.lbl_info_acodec.config(text=none_txt)
            self.lbl_info_sr.config(text=none_txt)
            self.lbl_info_ch.config(text=none_txt)

        self.has_video = info.get("has_video", False)
        self._update_resolution_state()
        self._update_target_preview()

        if self.trim_var.get() and info.get("duration") and info.get("duration") != "-":
            self.end_time_var.set(info.get("duration"))

    def _detect_hw_encoders_async(self):
        def worker():
            candidates = [
                ("h264_nvenc", "NVIDIA NVENC"),
                ("h264_qsv", "Intel QSV"),
                ("h264_amf", "AMD AMF"),
            ]
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            def probe(enc_info):
                enc_name, display_name = enc_info
                try:
                    cmd = [
                        self.ffmpeg_exe, "-y", "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1:r=25",
                        "-c:v", enc_name, "-f", "null", "-"
                    ]
                    with self._ffmpeg_probe_lock:
                        res = subprocess.run(
                            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            startupinfo=startupinfo, timeout=2.5
                        )
                    if res.returncode == 0:
                        return (enc_name, display_name)
                except Exception:
                    pass
                return None

            results = []
            for cand in candidates:
                results.append(probe(cand))

            available = [r for r in results if r is not None]
            self.available_hw_encoders = [x[0] for x in available]
            self._detected_hw_results = available

            def update_ui():
                self._update_encoder_display(available)

            self.dispatch_ui(update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _update_encoder_display(self, available=None):
        if available is not None:
            self._detected_hw_results = available
        available = getattr(self, '_detected_hw_results', None)
        try:
            enc_list = [t("options.encoder_auto")]
            if available:
                for enc_name, disp in available:
                    enc_list.append(f"{disp} ({enc_name})")
            enc_list.append(t("options.encoder_cpu"))
            self.cbo_encoder['values'] = enc_list

            curr_val = self.encoder_var.get()
            if not curr_val or "auto" in curr_val.lower() or "自动" in curr_val:
                self.encoder_var.set(t("options.encoder_auto"))
            elif "libx264" in curr_val or "cpu" in curr_val.lower():
                self.encoder_var.set(t("options.encoder_cpu"))

            if available is not None:
                if available:
                    names = ", ".join([x[1] for x in available])
                    self.lbl_gpu_status.config(text=t("options.gpu_ready", names=names), foreground="#008000")
                else:
                    self.lbl_gpu_status.config(text=t("options.gpu_none"), foreground="#666666")
        except Exception:
            pass

    def dispatch_ui(self, fn, *args):
        self.ui_queue.put((fn, args))

    def _check_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                fn, args = self.ui_queue.get_nowait()
                fn(*args)
        except Exception:
            pass
        try:
            self.root.after(40, self._check_ui_queue)
        except Exception:
            pass

    def _resolve_encoder(self, encoder_choice, has_custom_bitrate=False):
        choice_lower = (encoder_choice or "").strip().lower()
        if choice_lower.startswith("auto") or "自动" in choice_lower or "gpu" in choice_lower:
            # When custom video bitrate is set and only AMD AMF is detected, route to libx264
            # because AMF VBR/CBR driver has known issues adhering to target bitrate
            if has_custom_bitrate and self.available_hw_encoders and "h264_amf" in self.available_hw_encoders and len(self.available_hw_encoders) == 1:
                return "libx264"
            if self.available_hw_encoders:
                return self.available_hw_encoders[0]
            return "libx264"

        if "nvenc" in choice_lower:
            return "h264_nvenc"
        if "qsv" in choice_lower:
            return "h264_qsv"
        if "amf" in choice_lower:
            return "h264_amf"
        if "libx264" in choice_lower or "cpu" in choice_lower:
            return "libx264"

        if self.available_hw_encoders:
            return self.available_hw_encoders[0]
        return "libx264"

    def _update_resolution_state(self):
        convert_fmt = self.convert_var.get()
        video_bitrate_values = ["Auto", "150k", "300k", "500k", "800k", "1M", "1.5M", "2M", "3M", "5M", "8M"]
        audio_bitrate_values = ["Auto", "96k", "128k", "160k", "192k", "256k", "320k"]

        if self.has_video and convert_fmt not in ["MP3", "FLAC"]:
            self.cbo_resolution.config(state="readonly")
            self.cbo_encoder.config(state="readonly")
            self.cbo_bitrate.config(state="normal")
            if list(self.cbo_bitrate['values']) != video_bitrate_values:
                self.cbo_bitrate['values'] = video_bitrate_values
                if self.bitrate_var.get() not in video_bitrate_values:
                    self.bitrate_var.set("Auto")
        elif convert_fmt == "MP3":
            self.cbo_resolution.config(state="disabled")
            self.resolution_var.set("Original")
            self.cbo_encoder.config(state="disabled")
            self.cbo_bitrate.config(state="normal")
            if list(self.cbo_bitrate['values']) != audio_bitrate_values:
                self.cbo_bitrate['values'] = audio_bitrate_values
                if self.bitrate_var.get() not in audio_bitrate_values:
                    self.bitrate_var.set("Auto")
        else:
            self.cbo_resolution.config(state="disabled")
            self.resolution_var.set("Original")
            self.cbo_bitrate.config(state="disabled")
            self.bitrate_var.set("Auto")
            self.cbo_encoder.config(state="disabled")

        self._update_target_preview()

    def _update_target_preview(self):
        if not hasattr(self, 'lbl_target_preview'):
            return
        if not getattr(self, 'current_selected_path', None) or not getattr(self, 'current_media_info', None):
            self.lbl_target_preview.config(text="")
            return

        info = self.current_media_info
        dur_secs = info.get("duration_secs", 0.0)
        convert_fmt = self.convert_var.get()
        res_choice = self.resolution_var.get()
        br_str = self.bitrate_var.get()
        target_br = self._parse_custom_bitrate_kbps(br_str)
        is_muted = self.mute_var.get()

        if convert_fmt == "FLAC":
            self.lbl_target_preview.config(
                text=t("options.preview_flac"),
                foreground="#0066cc"
            )
            return

        if convert_fmt == "MP3":
            abr = target_br if target_br else 192
            est_txt = ""
            if dur_secs > 0:
                est_mb = (abr * dur_secs) / (8 * 1024)
                est_txt = t("options.est_size", size=est_mb)
            self.lbl_target_preview.config(
                text=t("options.preview_mp3", abr=abr, est_txt=est_txt),
                foreground="#0066cc"
            )
            return

        # Video format (None or MP4)
        if not self.has_video:
            self.lbl_target_preview.config(text="")
            return

        src_abr = info.get("audio_bitrate_kbps") or 128
        if target_br:
            vbr = target_br
            abr = 0 if is_muted else (src_abr if convert_fmt == "None" else 128)
            total_kbps = vbr + abr
            est_txt = ""
            if dur_secs > 0:
                est_mb = (total_kbps * dur_secs) / (8 * 1024)
                orig_sz = info.get("filesize", "")
                orig_txt = t("options.est_orig_size", size=orig_sz) if orig_sz and orig_sz != "-" else ""
                est_txt = t("options.est_size", size=est_mb) + orig_txt
            self.lbl_target_preview.config(
                text=t("options.preview_video", res=res_choice, vbr=vbr, est_txt=est_txt),
                foreground="#007700"
            )
        else:
            if res_choice in ["Original", "保持原分辨率", t("options.res_original")] and convert_fmt == "None" and not is_muted and not self.trim_var.get():
                self.lbl_target_preview.config(
                    text=t("options.preview_original"),
                    foreground="#666666"
                )
            else:
                res_configs = {
                    "144p": "~100-160k", "240p": "~200-350k", "360p": "~400-700k",
                    "480p": "~800-1200k", "720p": "~1.5-2.5M", "1080p": "~3-5M", "1440p": "~6-9M"
                }
                typical_br = res_configs.get(res_choice, "Auto CRF")
                self.lbl_target_preview.config(
                    text=t("options.preview_auto_bitrate", res=res_choice, typical_br=typical_br),
                    foreground="#0066cc"
                )

    def _on_file_path_changed(self, *args):
        path = self.file_path_var.get().strip()
        if path and os.path.exists(path):
            if path != self.current_selected_path:
                self.current_selected_path = path
                self._queue_probe_file(self.current_selected_item_id, path)
        elif not self.file_queue:
            self.current_selected_path = None
            self._clear_media_info()

    def _start_probe_worker(self):
        def worker():
            while True:
                item = self.probe_queue.get()
                if item is None:
                    break
                item_id, path = item
                try:
                    if os.path.exists(path):
                        info = self._parse_media_info(path)
                        def update():
                            if item_id and item_id in self.file_queue:
                                self.file_queue[item_id]["media_info"] = info
                                self.file_queue[item_id]["size"] = info.get("filesize", "-")
                                self.file_queue[item_id]["duration"] = info.get("duration", "-")
                                try:
                                    self.tree.set(item_id, "size", info.get("filesize", "-"))
                                    self.tree.set(item_id, "duration", info.get("duration", "-"))
                                except Exception:
                                    pass
                            if self.current_selected_path == path:
                                self._display_media_info(info)
                        self.dispatch_ui(update)
                except Exception:
                    pass
                finally:
                    self._probing_paths.discard(path)
                    self.probe_queue.task_done()

        threading.Thread(target=worker, daemon=True).start()

    def _queue_probe_file(self, item_id, path):
        if not path or not os.path.exists(path):
            return
        if path in self._probing_paths:
            return
        self._probing_paths.add(path)
        self.probe_queue.put((item_id, path))

    def _display_loading_media_info(self, filename):
        load_txt = t("sidebar.loading")
        self.lbl_info_name.config(text=filename)
        self.lbl_info_size.config(text=load_txt)
        self.lbl_info_dur.config(text=load_txt)
        self.lbl_info_br.config(text="-")
        self.lbl_info_vcodec.config(text="-")
        self.lbl_info_res.config(text="-")
        self.lbl_info_fps.config(text="-")
        self.lbl_info_acodec.config(text="-")
        self.lbl_info_sr.config(text="-")
        self.lbl_info_ch.config(text="-")
        self.has_video = False
        self.current_media_info = None
        self._update_resolution_state()
        self._update_target_preview()

    def _parse_media_info(self, input_path):
        info = {
            "filename": os.path.basename(input_path),
            "filepath": input_path,
            "filesize": "-",
            "filesize_bytes": 0,
            "duration": "-",
            "duration_secs": 0.0,
            "bitrate": "-",
            "total_bitrate_kbps": None,
            "has_video": False,
            "video_codec": "-",
            "video_bitrate_kbps": None,
            "resolution": "-",
            "fps": "-",
            "has_audio": False,
            "audio_codec": "-",
            "audio_bitrate_kbps": None,
            "sample_rate": "-",
            "channels": "-",
        }

        try:
            if os.path.exists(input_path):
                size_bytes = os.path.getsize(input_path)
                info["filesize_bytes"] = size_bytes
                if size_bytes >= 1024 * 1024 * 1024:
                    info["filesize"] = f"{size_bytes / (1024**3):.2f} GB"
                elif size_bytes >= 1024 * 1024:
                    info["filesize"] = f"{size_bytes / (1024**2):.2f} MB"
                else:
                    info["filesize"] = f"{size_bytes / 1024:.1f} KB"
        except OSError:
            pass

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            with self._ffmpeg_probe_lock:
                result = subprocess.run(
                    [self.ffmpeg_exe, "-i", input_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                    encoding='utf-8',
                    errors='replace'
                )
            stderr_txt = result.stderr

            dur_match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", stderr_txt)
            if dur_match:
                h, m, s = dur_match.groups()
                info["duration"] = f"{h}:{m}:{s.split('.')[0]}"
                try:
                    info["duration_secs"] = int(h) * 3600 + int(m) * 60 + float(s)
                except Exception:
                    pass

            br_match = re.search(r"bitrate:\s*(\d+)\s*k?b/s", stderr_txt, re.IGNORECASE)
            if br_match:
                info["bitrate"] = f"{br_match.group(1)} kb/s"
                info["total_bitrate_kbps"] = int(br_match.group(1))
            elif info["duration_secs"] > 0 and info["filesize_bytes"] > 0:
                calc_kbps = int((info["filesize_bytes"] * 8) / (info["duration_secs"] * 1000))
                info["total_bitrate_kbps"] = calc_kbps
                info["bitrate"] = f"{calc_kbps} kb/s"

            video_line = re.search(r"Stream #\d+:\d+.*?: Video: (.*)", stderr_txt)
            if video_line:
                v_info = video_line.group(1)
                info["has_video"] = True
                parts = [p.strip() for p in v_info.split(',')]
                if parts:
                    info["video_codec"] = parts[0].split()[0]
                res_m = re.search(r"(\d{2,5}x\d{2,5})", v_info)
                if res_m:
                    info["resolution"] = res_m.group(1)
                fps_m = re.search(r"(\d+(?:\.\d+)?)\s*fps", v_info)
                if fps_m:
                    info["fps"] = f"{fps_m.group(1)} fps"
                vbr_m = re.search(r"(\d+)\s*kb/s", v_info)
                if vbr_m:
                    info["video_bitrate_kbps"] = int(vbr_m.group(1))

            audio_line = re.search(r"Stream #\d+:\d+.*?: Audio: (.*)", stderr_txt)
            if audio_line:
                a_info = audio_line.group(1)
                info["has_audio"] = True
                parts = [p.strip() for p in a_info.split(',')]
                if parts:
                    info["audio_codec"] = parts[0].split()[0]
                sr_m = re.search(r"(\d+\s*Hz)", a_info)
                if sr_m:
                    info["sample_rate"] = sr_m.group(1)
                ch_m = re.search(r"\b(mono|stereo|5\.1|7\.1|\d+\s*channels?)\b", a_info, re.IGNORECASE)
                if ch_m:
                    info["channels"] = ch_m.group(1)
                abr_m = re.search(r"(\d+)\s*kb/s", a_info)
                if abr_m:
                    info["audio_bitrate_kbps"] = int(abr_m.group(1))

        except Exception:
            pass

        return info

    def on_drop_files(self, files):
        if not files:
            return
        # Escape the windnd ctypes callback by scheduling on Tkinter's event loop
        self.root.after(20, self._handle_dropped_files, files)

    def _handle_dropped_files(self, files):
        valid_paths = []
        for f in files:
            try:
                if isinstance(f, bytes):
                    try:
                        path_str = f.decode('gbk')
                    except UnicodeDecodeError:
                        path_str = f.decode('utf-8', errors='ignore')
                else:
                    path_str = str(f)

                path_str = path_str.strip().strip('"').strip("'")
                if os.path.exists(path_str):
                    if os.path.isfile(path_str):
                        valid_paths.append(path_str)
                    elif os.path.isdir(path_str):
                        for root_dir, _, fnames in os.walk(path_str):
                            for fname in fnames:
                                ext = os.path.splitext(fname)[1].lower()
                                if ext in ['.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv', '.webm', '.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.ts', '.m4v']:
                                    valid_paths.append(os.path.join(root_dir, fname))
            except Exception:
                continue

        if valid_paths:
            self.add_files_to_queue(valid_paths)
        else:
            messagebox.showinfo(t("dialogs.info_title"), t("dialogs.no_media_in_drop"))

    def browse_files(self):
        filenames = filedialog.askopenfilenames(
            title=t("dialogs.select_files_title"),
            filetypes=[
                (t("dialogs.file_filter_media"), "*.mp4 *.avi *.mkv *.mov *.flv *.wmv *.webm *.mp3 *.wav *.flac *.m4a *.aac *.ogg *.ts *.m4v"),
                (t("dialogs.file_filter_all"), "*.*")
            ]
        )
        if filenames:
            self.add_files_to_queue(list(filenames))

    def browse_file(self):
        self.browse_files()

    def add_files_to_queue(self, paths):
        added_ids = []
        for p in paths:
            abs_p = os.path.abspath(p)
            # Check duplicate
            already_exists = False
            for item_id, data in self.file_queue.items():
                if os.path.normpath(data["path"]) == os.path.normpath(abs_p):
                    already_exists = True
                    break
            if already_exists:
                continue

            fname = os.path.basename(abs_p)
            item_id = self.tree.insert("", "end", values=(fname, t("queue.status_calculating"), t("queue.status_calculating"), t("queue.status_pending")))
            self.file_queue[item_id] = {
                "path": abs_p,
                "name": fname,
                "status": "Pending",
                "size": "-",
                "duration": "-",
                "media_info": None
            }
            added_ids.append(item_id)
            self._queue_probe_file(item_id, abs_p)

        self._update_queue_summary()

        # If nothing was selected before, select the first newly added item
        if not self.tree.selection() and added_ids:
            self.tree.selection_set(added_ids[0])
            self._on_tree_selection_changed()

    def remove_selected_files(self):
        if self.is_processing:
            messagebox.showwarning(t("dialogs.warning_title"), t("dialogs.cannot_remove_in_progress"))
            return

        selected = list(self.tree.selection())
        if not selected:
            return

        for item_id in selected:
            if item_id in self.file_queue:
                del self.file_queue[item_id]
            try:
                self.tree.delete(item_id)
            except Exception:
                pass

        self._update_queue_summary()

        remaining = self.tree.get_children()
        if remaining:
            self.tree.selection_set(remaining[0])
            self._on_tree_selection_changed()
        else:
            self.current_selected_item_id = None
            self.current_selected_path = None
            self.file_path_var.set("")
            self._clear_media_info()

    def clear_file_queue(self):
        if self.is_processing:
            messagebox.showwarning(t("dialogs.warning_title"), t("dialogs.cannot_clear_in_progress"))
            return

        for item_id in list(self.file_queue.keys()):
            try:
                self.tree.delete(item_id)
            except Exception:
                pass
        self.file_queue.clear()
        self.current_selected_item_id = None
        self.current_selected_path = None
        self.file_path_var.set("")
        self._clear_media_info()
        self._update_queue_summary()

    def _update_queue_summary(self):
        count = len(self.file_queue)
        if count == 0:
            self.lbl_queue_count.config(text=t("queue.count_empty"))
        else:
            self.lbl_queue_count.config(text=t("queue.count_files", count=count))

    def _on_tree_selection_changed(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        item_id = selected[0]
        if item_id not in self.file_queue:
            return

        self.current_selected_item_id = item_id
        item_data = self.file_queue[item_id]
        self.current_selected_path = item_data["path"]
        self.file_path_var.set(item_data["path"])

        if item_data.get("media_info"):
            self._display_media_info(item_data["media_info"])
        else:
            self._display_loading_media_info(item_data["name"])
            self._queue_probe_file(item_id, item_data["path"])

    def _open_selected_file_folder(self):
        if self.current_selected_path and os.path.exists(self.current_selected_path):
            folder = os.path.dirname(self.current_selected_path)
            try:
                if os.name == 'nt':
                    os.startfile(folder)
                else:
                    subprocess.Popen(['xdg-open', folder])
            except Exception:
                pass

    def _is_item_done(self, item_id):
        if item_id not in self.file_queue:
            return False
        status_str = str(self.file_queue[item_id].get("status", ""))
        return "Done" in status_str or "完成" in status_str

    def reset_selected_status(self):
        if self.is_processing:
            return
        selected = list(self.tree.selection())
        for item_id in selected:
            if item_id in self.file_queue:
                self.file_queue[item_id]["status"] = "Pending"
                try:
                    self.tree.set(item_id, "status", t("queue.status_pending"))
                except Exception:
                    pass

    def reset_all_status(self):
        if self.is_processing:
            return
        for item_id in self.tree.get_children():
            if item_id in self.file_queue:
                self.file_queue[item_id]["status"] = "Pending"
                try:
                    self.tree.set(item_id, "status", t("queue.status_pending"))
                except Exception:
                    pass

    def cancel_processing(self):
        if not self.is_processing:
            return
        self._cancel_event.set()
        self.btn_cancel.config(state="disabled")
        self.status_var.set(t("ops.cancelling"))
        proc = self._current_process
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def on_closing(self):
        if self.is_processing:
            if messagebox.askyesno(t("dialogs.exit_title"), t("dialogs.confirm_exit_processing")):
                self.cancel_processing()
                self.root.destroy()
        else:
            self.root.destroy()

    def toggle_trim(self):
        state = "normal" if self.trim_var.get() else "disabled"
        self.entry_start.config(state=state)
        self.entry_end.config(state=state)

        if self.trim_var.get():
            if self.current_selected_path and os.path.exists(self.current_selected_path):
                self._queue_probe_file(self.current_selected_item_id, self.current_selected_path)

    def start_batch_processing(self):
        if not self.file_queue:
            messagebox.showwarning(t("dialogs.warning_title"), t("dialogs.queue_empty"))
            return

        should_mute = self.mute_var.get()
        convert_format = self.convert_var.get()
        res_choice = self.resolution_var.get()
        bitrate_choice = self.bitrate_var.get().strip()
        encoder_choice = self.encoder_var.get().strip()

        trim_args = None
        if self.trim_var.get():
            start = self.start_time_var.get().strip()
            end = self.end_time_var.get().strip()
            if not start or not end:
                messagebox.showwarning(t("dialogs.warning_title"), t("dialogs.invalid_trim_time"))
                return
            trim_args = (start, end)

        is_custom_bitrate = bool(self._parse_custom_bitrate_kbps(bitrate_choice))
        if not should_mute and not trim_args and convert_format == "None" and res_choice in ["Original", "保持原分辨率", t("options.res_original")] and not is_custom_bitrate:
            messagebox.showinfo(t("dialogs.info_title"), t("dialogs.no_action_selected"))
            return

        # Check completed vs pending items (Skip any files that are already Done)
        items_to_process = []
        for item_id in self.tree.get_children():
            if item_id in self.file_queue:
                if not self._is_item_done(item_id):
                    items_to_process.append((item_id, self.file_queue[item_id]))

        if not items_to_process:
            messagebox.showinfo(t("dialogs.info_title"), t("dialogs.all_completed"))
            return

        self._cancel_event.clear()
        self.is_processing = True

        self.btn_process.config(state="disabled")
        self.btn_add.config(state="disabled")
        self.btn_remove.config(state="disabled")
        self.btn_clear.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress.config(mode='determinate')
        self.progress['value'] = 0
        self.status_var.set(t("ops.batch_starting", total=len(items_to_process)))

        threading.Thread(
            target=self._batch_worker,
            args=(items_to_process, should_mute, convert_format, trim_args, res_choice, bitrate_choice, encoder_choice),
            daemon=True
        ).start()

    def start_processing(self):
        self.start_batch_processing()

    def update_progress(self, percent):
        self.progress['value'] = percent
        self.status_var.set(f"{t('ops.process')}... {percent:.1f}%")

    def _parse_custom_bitrate_kbps(self, br_str):
        if not br_str or br_str.strip().lower() in ["auto", "自动", "none", "default", "-", "original", "保持原分辨率"]:
            return None
        s = br_str.strip().lower().replace(" ", "").replace("/s", "").replace("ps", "")
        m = re.match(r"^([\d.]+)\s*(k|m|kb|mb)?$", s)
        if not m:
            return None
        val_str, unit = m.groups()
        try:
            val = float(val_str)
            if unit in ["m", "mb"]:
                return int(val * 1000)
            else:
                return int(val)
        except Exception:
            return None

    def _get_video_encode_args(self, res_choice, media_info, bitrate_choice="Auto", encoder="libx264"):
        target_vbr = self._parse_custom_bitrate_kbps(bitrate_choice)
        res_configs = {
            "144p": {"crf": 28, "maxrate": 160},
            "240p": {"crf": 26, "maxrate": 350},
            "360p": {"crf": 25, "maxrate": 700},
            "480p": {"crf": 24, "maxrate": 1200},
            "720p": {"crf": 23, "maxrate": 2500},
            "1080p": {"crf": 23, "maxrate": 5000},
            "1440p": {"crf": 23, "maxrate": 9000},
        }

        cfg = res_configs.get(res_choice, {"crf": 23, "maxrate": None})
        crf = cfg["crf"]
        maxrate = cfg["maxrate"]

        # Prevent bitrate inflation when downscaling low-bitrate sources
        src_vbr = media_info.get("video_bitrate_kbps")
        if not src_vbr and media_info.get("total_bitrate_kbps"):
            src_vbr = max(int(media_info["total_bitrate_kbps"] * 0.8), 40)

        if src_vbr and maxrate:
            if res_choice in ["144p", "240p"]:
                maxrate = min(maxrate, max(int(src_vbr * 0.85), 50))
            else:
                maxrate = min(maxrate, max(int(src_vbr * 1.1), 80))

        if target_vbr:
            maxrate = int(target_vbr * 1.5)
            bufsize = target_vbr * 2
        else:
            bufsize = maxrate * 2 if maxrate else None

        if encoder == "h264_nvenc":
            args = ["-c:v", "h264_nvenc", "-preset", "p4"]
            if target_vbr:
                args.extend(["-rc", "vbr", "-b:v", f"{target_vbr}k", "-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"])
            else:
                args.extend(["-cq", str(crf)])
                if maxrate:
                    args.extend(["-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"])
            args.extend(["-pix_fmt", "yuv420p"])
            return args

        elif encoder == "h264_qsv":
            args = ["-c:v", "h264_qsv", "-preset", "medium"]
            if target_vbr:
                args.extend(["-b:v", f"{target_vbr}k", "-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"])
            else:
                args.extend(["-global_quality", str(crf)])
                if maxrate:
                    args.extend(["-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"])
            args.extend(["-pix_fmt", "nv12"])
            return args

        elif encoder == "h264_amf":
            args = ["-c:v", "h264_amf", "-quality", "balanced"]
            if target_vbr:
                args.extend(["-rc", "vbr_peak", "-b:v", f"{target_vbr}k", "-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"])
            else:
                args.extend(["-rc", "cqp", "-qp_p", str(crf), "-qp_i", str(crf)])
                if maxrate:
                    args.extend(["-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"])
            args.extend(["-pix_fmt", "yuv420p"])
            return args

        else:  # libx264
            args = ["-c:v", "libx264", "-preset", "medium"]
            if target_vbr:
                args.extend(["-b:v", f"{target_vbr}k", "-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"])
            else:
                args.extend(["-crf", str(crf)])
                if maxrate:
                    args.extend(["-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"])
            args.extend(["-pix_fmt", "yuv420p"])
            return args

    def _get_audio_encode_args(self, convert_format, res_choice, media_info, should_mute, bitrate_choice="Auto"):
        if should_mute:
            return ["-an"]

        if convert_format in ["MP3", "FLAC"]:
            if convert_format == "MP3":
                target_abr = self._parse_custom_bitrate_kbps(bitrate_choice)
                if target_abr:
                    return ["-c:a", "libmp3lame", "-b:a", f"{target_abr}k"]
                return ["-c:a", "libmp3lame", "-q:a", "2"]
            else:
                return ["-c:a", "flac"]

        if convert_format == "None":
            return ["-c:a", "copy"]

        if convert_format == "MP4":
            src_acodec = (media_info.get("audio_codec") or "").lower()
            if "aac" in src_acodec:
                return ["-c:a", "copy"]

            target_abr = 128
            if res_choice in ["144p", "240p"]:
                target_abr = 48
            elif res_choice in ["360p", "480p"]:
                target_abr = 96

            src_abr = media_info.get("audio_bitrate_kbps")
            if src_abr:
                target_abr = min(target_abr, max(src_abr, 32))

            return ["-c:a", "aac", "-b:a", f"{target_abr}k"]

        return ["-c:a", "copy"]

    def _update_item_status(self, item_id, status_text):
        if item_id in self.file_queue:
            if "Done" in status_text or "完成" in status_text:
                self.file_queue[item_id]["status"] = "Done"
            elif "Failed" in status_text or "失败" in status_text:
                self.file_queue[item_id]["status"] = "Failed"
            elif "Cancelled" in status_text or "取消" in status_text:
                self.file_queue[item_id]["status"] = "Cancelled"
            else:
                self.file_queue[item_id]["status"] = status_text
        try:
            self.tree.set(item_id, "status", status_text)
        except Exception:
            pass

    def _set_tree_active_item(self, item_id):
        try:
            self.tree.selection_set(item_id)
            self.tree.see(item_id)
            self._on_tree_selection_changed()
        except Exception:
            pass

    def _batch_worker(self, items_to_process, should_mute, convert_format, trim_args, res_choice, bitrate_choice, encoder_choice):
        total = len(items_to_process)
        success_count = 0
        fail_count = 0

        for idx, (item_id, item_data) in enumerate(items_to_process, start=1):
            if self._cancel_event.is_set():
                self.dispatch_ui(self._update_item_status, item_id, t("queue.status_cancelled"))
                continue

            file_path = item_data["path"]
            file_name = item_data["name"]

            # Select and bring into view
            self.dispatch_ui(self._set_tree_active_item, item_id)
            self.dispatch_ui(self.status_var.set, t("ops.processing_file", idx=idx, total=total, filename=file_name, percent=0.0))
            self.dispatch_ui(self.update_progress, 0)
            self.dispatch_ui(self._update_item_status, item_id, "🔄 0%")

            def file_progress(percent):
                self.dispatch_ui(self.update_progress, percent)
                self.dispatch_ui(self._update_item_status, item_id, f"🔄 {percent:.0f}%")
                self.dispatch_ui(self.status_var.set, t("ops.processing_file", idx=idx, total=total, filename=file_name, percent=percent))

            success, msg, status_code = self.process_single_file(
                file_path, should_mute, convert_format, trim_args, res_choice, bitrate_choice, encoder_choice,
                progress_callback=file_progress
            )

            if status_code == "cancelled":
                self.dispatch_ui(self._update_item_status, item_id, t("queue.status_cancelled"))
                # Mark remaining items as Cancelled
                for rem_id, _ in items_to_process[idx:]:
                    self.dispatch_ui(self._update_item_status, rem_id, t("queue.status_cancelled"))
                break
            elif success:
                success_count += 1
                self.dispatch_ui(self._update_item_status, item_id, t("queue.status_done"))
            else:
                fail_count += 1
                self.dispatch_ui(self._update_item_status, item_id, t("queue.status_failed"))

        self.dispatch_ui(self.finish_batch, success_count, fail_count, total)

    def finish_batch(self, success_count, fail_count, total):
        self.is_processing = False
        self.btn_process.config(state="normal")
        self.btn_add.config(state="normal")
        self.btn_remove.config(state="normal")
        self.btn_clear.config(state="normal")
        self.btn_cancel.config(state="disabled")

        if self._cancel_event.is_set():
            rem = max(total - success_count - fail_count, 0)
            self.status_var.set(t("ops.batch_cancelled", success=success_count, rem=rem))
            messagebox.showinfo(t("dialogs.cancelled_title"), t("dialogs.batch_cancelled_msg", success=success_count, rem=rem))
        else:
            self.progress['value'] = 100.0
            self.status_var.set(t("ops.batch_complete", success=success_count, fail=fail_count, total=total))
            if fail_count == 0:
                messagebox.showinfo(
                    t("dialogs.success_title"),
                    t("dialogs.all_success_msg", count=success_count)
                )
            else:
                messagebox.showwarning(
                    t("dialogs.finished_errors_title"),
                    t("dialogs.batch_error_msg", success=success_count, fail=fail_count)
                )

    def process_video(self, input_path, should_mute, convert_format, trim_args=None, res_choice="Original", bitrate_choice="Auto", encoder_choice="Auto"):
        def cb(p):
            self.dispatch_ui(self.update_progress, p)
        return self.process_single_file(input_path, should_mute, convert_format, trim_args, res_choice, bitrate_choice, encoder_choice, progress_callback=cb)

    def process_single_file(self, input_path, should_mute, convert_format, trim_args=None, res_choice="Original", bitrate_choice="Auto", encoder_choice="Auto", progress_callback=None):
        try:
            folder = os.path.dirname(input_path)
            filename = os.path.basename(input_path)
            name, ext = os.path.splitext(filename)

            if convert_format != "None":
                ext = f".{convert_format.lower()}"

            res_map = {
                "144p": 144, "240p": 240, "360p": 360, "480p": 480,
                "720p": 720, "1080p": 1080, "1440p": 1440
            }
            target_h = res_map.get(res_choice)
            target_vbr = self._parse_custom_bitrate_kbps(bitrate_choice)

            suffix = ""
            if should_mute and convert_format not in ["MP3", "FLAC"]:
                suffix += "_muted"
            if trim_args:
                start_str = trim_args[0].replace(":", "-")
                end_str = trim_args[1].replace(":", "-")
                suffix += f"_{start_str}_to_{end_str}"
            if target_h and convert_format not in ["MP3", "FLAC"]:
                suffix += f"_{res_choice}"
            if target_vbr:
                suffix += f"_{bitrate_choice.strip().replace(' ', '')}"
            if convert_format != "None":
                suffix += f"_converted_{convert_format.lower()}"

            if not suffix:
                suffix = "_processed"

            output_path = os.path.join(folder, f"{name}{suffix}{ext}")
            media_info = self._parse_media_info(input_path)

            resolved_encoder = self._resolve_encoder(encoder_choice, has_custom_bitrate=bool(target_vbr))

            def build_cmd(enc):
                cmd = [self.ffmpeg_exe, "-y"]
                if trim_args:
                    start_t, end_t = trim_args
                    cmd.extend(["-ss", start_t, "-to", end_t])

                cmd.extend(["-i", input_path])

                if target_h and convert_format not in ["MP3", "FLAC"]:
                    cmd.extend(["-vf", f"scale=-2:{target_h}"])

                if convert_format in ["MP3", "FLAC"]:
                    cmd.append("-vn")
                    cmd.extend(self._get_audio_encode_args(convert_format, res_choice, media_info, should_mute, bitrate_choice))
                elif convert_format == "None":
                    if target_h or target_vbr:
                        cmd.extend(self._get_video_encode_args(res_choice, media_info, bitrate_choice, encoder=enc))
                        cmd.extend(self._get_audio_encode_args("None", res_choice, media_info, should_mute, bitrate_choice))
                    else:
                        if should_mute:
                            cmd.extend(["-c:v", "copy", "-an"])
                        else:
                            cmd.extend(["-c", "copy"])
                elif convert_format == "MP4":
                    src_vcodec = (media_info.get("video_codec") or "").lower()
                    if not target_h and not target_vbr and "h264" in src_vcodec:
                        cmd.extend(["-c:v", "copy"])
                    else:
                        cmd.extend(self._get_video_encode_args(res_choice, media_info, bitrate_choice, encoder=enc))
                    cmd.extend(self._get_audio_encode_args("MP4", res_choice, media_info, should_mute, bitrate_choice))

                if output_path.lower().endswith(".mp4"):
                    cmd.extend(["-movflags", "+faststart"])

                cmd.append(output_path)
                return cmd

            def _cleanup_output():
                try:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                except Exception:
                    pass

            def execute_ffmpeg(enc):
                if self._cancel_event.is_set():
                    return -1, "Cancelled by user"

                cmd = build_cmd(enc)
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                try:
                    self._current_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        startupinfo=startupinfo,
                        encoding='utf-8',
                        errors='replace'
                    )
                    process = self._current_process
                except Exception as e:
                    self._current_process = None
                    return -1, str(e)

                duration_secs = 0.0
                error_output = []
                duration_re = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
                time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

                try:
                    for line in process.stderr:
                        if self._cancel_event.is_set():
                            try:
                                process.kill()
                            except Exception:
                                pass
                            break

                        error_output.append(line)

                        if duration_secs == 0.0:
                            match = duration_re.search(line)
                            if match:
                                h, m, s = match.groups()
                                duration_secs = int(h) * 3600 + int(m) * 60 + float(s)
                                if trim_args:
                                    try:
                                        start_t, end_t = trim_args
                                        def parse_time(t_str):
                                            parts = t_str.split(':')
                                            return int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
                                        s_sec = parse_time(start_t)
                                        e_sec = parse_time(end_t)
                                        trim_dur = e_sec - s_sec
                                        if trim_dur < duration_secs:
                                            duration_secs = trim_dur
                                    except Exception:
                                        pass

                        if duration_secs > 0:
                            match = time_re.search(line)
                            if match:
                                h, m, s = match.groups()
                                current_secs = int(h) * 3600 + int(m) * 60 + float(s)
                                percent = (current_secs / duration_secs) * 100
                                if percent > 100:
                                    percent = 100
                                if progress_callback:
                                    progress_callback(percent)
                except Exception:
                    pass

                process.wait()
                try:
                    if process.stderr:
                        process.stderr.close()
                except Exception:
                    pass
                self._current_process = None
                return process.returncode, "".join(error_output)

            # First attempt with resolved encoder
            returncode, error_msg = execute_ffmpeg(resolved_encoder)

            if self._cancel_event.is_set():
                _cleanup_output()
                return False, "Cancelled", "cancelled"

            # Fallback to libx264 if GPU encoding failed
            if returncode != 0 and resolved_encoder != "libx264" and convert_format not in ["MP3", "FLAC"]:
                self.dispatch_ui(self.status_var.set, t("dialogs.gpu_error_fallback", filename=filename))
                _cleanup_output()
                returncode, error_msg = execute_ffmpeg("libx264")

                if self._cancel_event.is_set():
                    _cleanup_output()
                    return False, "Cancelled", "cancelled"

            if returncode == 0:
                if progress_callback:
                    progress_callback(100.0)
                return True, output_path, "done"
            else:
                return False, error_msg, "failed"

        except Exception as e:
            return False, str(e), "failed"


MediaTinkerApp = AudioRemoverApp

if __name__ == "__main__":
    root = tk.Tk()

    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = AudioRemoverApp(root)
    root.mainloop()
