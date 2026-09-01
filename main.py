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

try:
    import windnd
except ImportError:
    windnd = None


class AudioRemoverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MediaTinker")
        self.root.geometry("820x620")
        self.root.minsize(780, 580)

        self.ui_queue = queue.Queue()
        self._check_ui_queue()

        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        self.has_video = False
        self._last_loaded_file = None
        self.current_media_info = None
        self._cancel_event = threading.Event()
        self._current_process = None

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        if windnd:
            try:
                windnd.hook_dropfiles(self.root, func=self.on_drop_files)
            except Exception:
                pass

        # Style
        style = ttk.Style()
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=4)

        # Main Layout Container (Left: Controls, Right: Media Info Sidebar)
        main_container = ttk.Frame(root, padding=10)
        main_container.pack(fill="both", expand=True)

        left_container = ttk.Frame(main_container)
        left_container.pack(side="left", fill="both", expand=True, padx=(0, 5))

        # --- Right Sidebar: Source Media Info ---
        self.sidebar_frame = ttk.LabelFrame(main_container, text="Source Media Info (源文件信息)", padding=10)
        self.sidebar_frame.pack(side="right", fill="both", expand=False, padx=(5, 0))
        self.sidebar_frame.config(width=260)

        self._build_sidebar(self.sidebar_frame)

        # --- Left Container Controls ---
        # File Selection Frame
        self.file_frame = ttk.LabelFrame(left_container, text="Source File", padding=10)
        self.file_frame.pack(fill="x", pady=(0, 10))

        self.file_path_var = tk.StringVar()
        self.file_path_var.trace_add("write", self._on_file_path_changed)

        self.entry_path = ttk.Entry(self.file_frame, textvariable=self.file_path_var)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_browse = ttk.Button(self.file_frame, text="Browse", command=self.browse_file)
        self.btn_browse.pack(side="right")

        # Options Frame
        self.opts_frame = ttk.LabelFrame(left_container, text="Options", padding=10)
        self.opts_frame.pack(fill="x", pady=5)

        # Convert Options
        self.convert_var = tk.StringVar(value="None")
        self.convert_var.trace_add("write", lambda *args: self._update_resolution_state())

        self.convert_frame = ttk.Frame(self.opts_frame)
        self.convert_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(self.convert_frame, text="Convert to:").pack(side="left")
        ttk.Radiobutton(self.convert_frame, text="None", variable=self.convert_var, value="None").pack(side="left", padx=5)
        ttk.Radiobutton(self.convert_frame, text="MP4", variable=self.convert_var, value="MP4").pack(side="left", padx=5)
        ttk.Radiobutton(self.convert_frame, text="MP3", variable=self.convert_var, value="MP3").pack(side="left", padx=5)
        ttk.Radiobutton(self.convert_frame, text="FLAC", variable=self.convert_var, value="FLAC").pack(side="left", padx=5)

        # Video/Audio Options (Resolution & Bitrate)
        self.res_frame = ttk.Frame(self.opts_frame)
        self.res_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(self.res_frame, text="Resolution (分辨率):").pack(side="left")
        self.resolution_var = tk.StringVar(value="Original")
        self.cbo_resolution = ttk.Combobox(
            self.res_frame,
            textvariable=self.resolution_var,
            values=["Original", "144p", "240p", "360p", "480p", "720p", "1080p", "1440p"],
            state="disabled",
            width=10
        )
        self.cbo_resolution.pack(side="left", padx=(5, 15))

        ttk.Label(self.res_frame, text="Bitrate (码率):").pack(side="left")
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

        ttk.Label(self.enc_frame, text="Encoder (编码器):").pack(side="left")
        self.encoder_var = tk.StringVar(value="Auto (GPU > CPU)")
        self.cbo_encoder = ttk.Combobox(
            self.enc_frame,
            textvariable=self.encoder_var,
            values=["Auto (GPU > CPU)", "CPU (libx264)"],
            state="disabled",
            width=22
        )
        self.cbo_encoder.pack(side="left", padx=5)

        self.lbl_gpu_status = ttk.Label(self.enc_frame, text="[Detecting GPU...]", foreground="#666666", font=("Segoe UI", 8))
        self.lbl_gpu_status.pack(side="left", padx=(5, 0))

        # Initialize hardware encoder state and detect
        self.available_hw_encoders = []
        self._detect_hw_encoders_async()

        # Mute Option
        self.mute_var = tk.BooleanVar(value=False)
        self.chk_mute = ttk.Checkbutton(self.opts_frame, text="Remove Audio", variable=self.mute_var)
        self.chk_mute.pack(anchor="w", pady=(0, 5))

        # Trim Option
        self.trim_var = tk.BooleanVar(value=False)
        self.chk_trim = ttk.Checkbutton(self.opts_frame, text="Trim Media", variable=self.trim_var, command=self.toggle_trim)
        self.chk_trim.pack(anchor="w", pady=(0, 5))

        self.time_frame = ttk.Frame(self.opts_frame)
        self.time_frame.pack(fill="x", padx=20)

        ttk.Label(self.time_frame, text="Start Time (HH:MM:SS):").pack(side="left")
        self.start_time_var = tk.StringVar(value="00:00:00")
        self.entry_start = ttk.Entry(self.time_frame, textvariable=self.start_time_var, width=10, state="disabled")
        self.entry_start.pack(side="left", padx=(5, 20))

        ttk.Label(self.time_frame, text="End Time (HH:MM:SS):").pack(side="left")
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
        self.ops_frame = ttk.Frame(left_container, padding=10)
        self.ops_frame.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Ready")
        self.lbl_status = ttk.Label(self.ops_frame, textvariable=self.status_var, font=("Segoe UI", 10), wraplength=450)
        self.lbl_status.pack(pady=15)

        self.progress = ttk.Progressbar(self.ops_frame, mode='determinate', maximum=100)
        self.progress.pack(fill="x", pady=10)

        self.btn_frame = ttk.Frame(self.ops_frame)
        self.btn_frame.pack(pady=10)

        self.btn_process = ttk.Button(self.btn_frame, text="Process", command=self.start_processing)
        self.btn_process.pack(side="left", padx=5)

        self.btn_cancel = ttk.Button(self.btn_frame, text="Cancel", command=self.cancel_processing, state="disabled")
        self.btn_cancel.pack(side="left", padx=5)

        # Footer
        ttk.Label(root, text="Uses imageio-ffmpeg", font=("Segoe UI", 8)).pack(side="bottom", pady=5)

    def _build_sidebar(self, parent):
        info_inner = ttk.Frame(parent)
        info_inner.pack(fill="both", expand=True)

        def add_row(row_idx, label_text):
            lbl_title = ttk.Label(info_inner, text=label_text, font=("Segoe UI", 9, "bold"))
            lbl_title.grid(row=row_idx, column=0, sticky="nw", pady=2)
            lbl_val = ttk.Label(info_inner, text="-", font=("Segoe UI", 9), wraplength=160)
            lbl_val.grid(row=row_idx, column=1, sticky="nw", padx=(5, 0), pady=2)
            return lbl_val

        # General Section
        ttk.Label(info_inner, text="[ General ]", font=("Segoe UI", 9, "bold"), foreground="#0066cc").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.lbl_info_name = add_row(1, "Name:")
        self.lbl_info_size = add_row(2, "Size:")
        self.lbl_info_dur = add_row(3, "Duration:")
        self.lbl_info_br = add_row(4, "Bitrate:")

        # Separator
        ttk.Separator(info_inner, orient="horizontal").grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)

        # Video Section
        ttk.Label(info_inner, text="[ Video ]", font=("Segoe UI", 9, "bold"), foreground="#0066cc").grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.lbl_info_vcodec = add_row(7, "Codec:")
        self.lbl_info_res = add_row(8, "Resolution:")
        self.lbl_info_fps = add_row(9, "FPS:")

        # Separator
        ttk.Separator(info_inner, orient="horizontal").grid(row=10, column=0, columnspan=2, sticky="ew", pady=8)

        # Audio Section
        ttk.Label(info_inner, text="[ Audio ]", font=("Segoe UI", 9, "bold"), foreground="#0066cc").grid(row=11, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.lbl_info_acodec = add_row(12, "Codec:")
        self.lbl_info_sr = add_row(13, "Sample Rate:")
        self.lbl_info_ch = add_row(14, "Channels:")

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
        if info.get("filepath") != self.file_path_var.get().strip():
            return

        self.current_media_info = info
        self.lbl_info_name.config(text=info.get("filename", "-"))
        self.lbl_info_size.config(text=info.get("filesize", "-"))
        self.lbl_info_dur.config(text=info.get("duration", "-"))
        self.lbl_info_br.config(text=info.get("bitrate", "-"))

        if info.get("has_video"):
            self.lbl_info_vcodec.config(text=info.get("video_codec", "-"))
            self.lbl_info_res.config(text=info.get("resolution", "-"))
            self.lbl_info_fps.config(text=info.get("fps", "-"))
        else:
            self.lbl_info_vcodec.config(text="None")
            self.lbl_info_res.config(text="None")
            self.lbl_info_fps.config(text="None")

        if info.get("has_audio"):
            self.lbl_info_acodec.config(text=info.get("audio_codec", "-"))
            self.lbl_info_sr.config(text=info.get("sample_rate", "-"))
            self.lbl_info_ch.config(text=info.get("channels", "-"))
        else:
            self.lbl_info_acodec.config(text="None")
            self.lbl_info_sr.config(text="None")
            self.lbl_info_ch.config(text="None")

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
                    res = subprocess.run(
                        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        startupinfo=startupinfo, timeout=2.5
                    )
                    if res.returncode == 0:
                        return (enc_name, display_name)
                except Exception:
                    pass
                return None

            threads = []
            results = [None] * len(candidates)

            def run_probe(idx, cand):
                results[idx] = probe(cand)

            for i, cand in enumerate(candidates):
                t = threading.Thread(target=run_probe, args=(i, cand), daemon=True)
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            available = [r for r in results if r is not None]
            self.available_hw_encoders = [x[0] for x in available]

            def update_ui():
                try:
                    enc_list = ["Auto (GPU > CPU)"]
                    for enc_name, disp in available:
                        enc_list.append(f"{disp} ({enc_name})")
                    enc_list.append("CPU (libx264)")
                    self.cbo_encoder['values'] = enc_list

                    if available:
                        names = ", ".join([x[1] for x in available])
                        self.lbl_gpu_status.config(text=f"[{names} Ready]", foreground="#008000")
                    else:
                        self.lbl_gpu_status.config(text="[GPU not detected, CPU only]", foreground="#666666")
                except Exception:
                    pass

            self.dispatch_ui(update_ui)

        threading.Thread(target=worker, daemon=True).start()

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
        if choice_lower.startswith("auto"):
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
        if not self.file_path_var.get().strip() or not getattr(self, 'current_media_info', None):
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
                text="[Target / 预估] Format: FLAC (Lossless Audio / 无损音频) | Encoder: flac",
                foreground="#0066cc"
            )
            return

        if convert_fmt == "MP3":
            abr = target_br if target_br else 192
            est_txt = ""
            if dur_secs > 0:
                est_mb = (abr * dur_secs) / (8 * 1024)
                est_txt = f" | Est. Size (预估大小): ~{est_mb:.2f} MB"
            self.lbl_target_preview.config(
                text=f"[Target / 预估] Format: MP3 | Audio Bitrate: {abr} kb/s{est_txt}",
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
                orig_txt = f" (Original: {orig_sz})" if orig_sz and orig_sz != "-" else ""
                est_txt = f" | Est. Size (预估大小): ~{est_mb:.2f} MB{orig_txt}"
            self.lbl_target_preview.config(
                text=f"[Target / 预估] Resolution: {res_choice} | Video Bitrate: {vbr} kb/s{est_txt}",
                foreground="#007700"
            )
        else:
            if res_choice == "Original" and convert_fmt == "None" and not is_muted and not self.trim_var.get():
                self.lbl_target_preview.config(
                    text="[Target / 预估] Keep Original Quality (Stream Copy / 无损流复制)",
                    foreground="#666666"
                )
            else:
                res_configs = {
                    "144p": "~100-160k", "240p": "~200-350k", "360p": "~400-700k",
                    "480p": "~800-1200k", "720p": "~1.5-2.5M", "1080p": "~3-5M", "1440p": "~6-9M"
                }
                typical_br = res_configs.get(res_choice, "Auto CRF")
                self.lbl_target_preview.config(
                    text=f"[Target / 预估] Resolution: {res_choice} | Bitrate: Auto ({typical_br})",
                    foreground="#0066cc"
                )

    def _on_file_path_changed(self, *args):
        path = self.file_path_var.get().strip()
        if path and os.path.exists(path):
            if path != self._last_loaded_file:
                self._last_loaded_file = path
                self.status_var.set("Ready")
                self._load_media_info_async(path)
        else:
            self._last_loaded_file = None
            self._clear_media_info()

    def _load_media_info_async(self, file_path):
        def worker():
            info = self._parse_media_info(file_path)
            self.dispatch_ui(self._display_media_info, info)

        threading.Thread(target=worker, daemon=True).start()

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

        if os.path.exists(input_path):
            size_bytes = os.path.getsize(input_path)
            info["filesize_bytes"] = size_bytes
            if size_bytes >= 1024 * 1024 * 1024:
                info["filesize"] = f"{size_bytes / (1024**3):.2f} GB"
            elif size_bytes >= 1024 * 1024:
                info["filesize"] = f"{size_bytes / (1024**2):.2f} MB"
            else:
                info["filesize"] = f"{size_bytes / 1024:.1f} KB"

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
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
        try:
            try:
                filename = files[0].decode('gbk')
            except UnicodeDecodeError:
                filename = files[0].decode('utf-8', errors='ignore')

            filename = filename.strip()
            if os.path.exists(filename):
                self.file_path_var.set(filename)
                self.status_var.set("Ready")
            else:
                messagebox.showerror("Error", f"Dropped file not found:\n{filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load dropped file: {e}")

    def cancel_processing(self):
        self._cancel_event.set()
        self.btn_cancel.config(state="disabled")
        self.status_var.set("Cancelling...")
        proc = self._current_process
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def on_closing(self):
        proc = self._current_process
        if proc and proc.poll() is None:
            if messagebox.askyesno("Exit", "Encoding is currently in progress. Do you want to cancel and exit?"):
                self.cancel_processing()
                self.root.destroy()
        else:
            self.root.destroy()

    def toggle_trim(self):
        state = "normal" if self.trim_var.get() else "disabled"
        self.entry_start.config(state=state)
        self.entry_end.config(state=state)

        if self.trim_var.get():
            input_path = self.file_path_var.get().strip()
            if input_path and os.path.exists(input_path):
                self._load_media_info_async(input_path)

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Select Video/Audio File",
            filetypes=[("Media files", "*.mp4 *.avi *.mkv *.mov *.flv *.wmv *.webm *.mp3 *.wav *.flac *.m4a"), ("All files", "*.*")]
        )
        if filename:
            self.file_path_var.set(filename)
            self.status_var.set("Ready")

    def start_processing(self):
        input_path = self.file_path_var.get().strip()
        if not input_path:
            messagebox.showwarning("Warning", "Please select a file first.")
            return

        if not os.path.exists(input_path):
            messagebox.showerror("Error", "File does not exist.")
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
                messagebox.showwarning("Warning", "Please enter valid start/end times.")
                return
            trim_args = (start, end)

        is_custom_bitrate = bool(self._parse_custom_bitrate_kbps(bitrate_choice))
        if not should_mute and not trim_args and convert_format == "None" and res_choice == "Original" and not is_custom_bitrate:
            messagebox.showinfo("Info", "Nothing to do! Select an option.")
            return

        self._cancel_event.clear()
        self.btn_process.config(state="disabled")
        self.btn_browse.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress.config(mode='determinate')
        self.progress['value'] = 0
        self.status_var.set("Processing... 0.0%")

        threading.Thread(
            target=self.process_video,
            args=(input_path, should_mute, convert_format, trim_args, res_choice, bitrate_choice, encoder_choice),
            daemon=True
        ).start()

    def update_progress(self, percent):
        self.progress['value'] = percent
        self.status_var.set(f"Processing... {percent:.1f}%")

    def _parse_custom_bitrate_kbps(self, br_str):
        if not br_str or br_str.strip().lower() in ["auto", "none", "default", "-", "original"]:
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

    def process_video(self, input_path, should_mute, convert_format, trim_args=None, res_choice="Original", bitrate_choice="Auto", encoder_choice="Auto"):
        try:
            folder = os.path.dirname(input_path)
            filename = os.path.basename(input_path)
            name, ext = os.path.splitext(filename)

            if convert_format != "None":
                ext = f".{convert_format.lower()}"

            res_map = {
                "144p": 144,
                "240p": 240,
                "360p": 360,
                "480p": 480,
                "720p": 720,
                "1080p": 1080,
                "1440p": 1440
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
                                self.dispatch_ui(self.update_progress, percent)
                except Exception:
                    pass

                process.wait()
                self._current_process = None
                return process.returncode, "".join(error_output)

            # First attempt with resolved encoder
            returncode, error_msg = execute_ffmpeg(resolved_encoder)

            if self._cancel_event.is_set():
                _cleanup_output()
                self.dispatch_ui(self.finish_cancelled)
                return

            # Fallback to libx264 if GPU encoding failed
            if returncode != 0 and resolved_encoder != "libx264" and convert_format not in ["MP3", "FLAC"]:
                self.dispatch_ui(self.status_var.set, "GPU error. Falling back to CPU (libx264)...")
                self.dispatch_ui(self.update_progress, 0)
                _cleanup_output()
                returncode, error_msg = execute_ffmpeg("libx264")

                if self._cancel_event.is_set():
                    _cleanup_output()
                    self.dispatch_ui(self.finish_cancelled)
                    return

            if returncode == 0:
                self.dispatch_ui(self.update_progress, 100.0)
                self.dispatch_ui(self.finish_success, output_path)
            else:
                self.dispatch_ui(self.finish_error, error_msg)

        except Exception as e:
            self.dispatch_ui(self.finish_error, str(e))

    def finish_success(self, output_path):
        self.btn_process.config(state="normal")
        self.btn_browse.config(state="normal")
        self.btn_cancel.config(state="disabled")
        out_info = self._parse_media_info(output_path)
        out_size = out_info.get("filesize", "-")
        out_br = out_info.get("bitrate", "-")
        fname = os.path.basename(output_path)
        self.status_var.set(f"Done! Saved to:\n{fname}\nSize: {out_size} | Bitrate: {out_br}")
        messagebox.showinfo(
            "Success",
            f"Process completed successfully!\n\nSaved as: {fname}\nSize: {out_size}\nBitrate: {out_br}"
        )

    def finish_error(self, error_msg):
        self.btn_process.config(state="normal")
        self.btn_browse.config(state="normal")
        self.btn_cancel.config(state="disabled")
        self.status_var.set("Error occurred.")
        messagebox.showerror("Error", f"Failed to process file.\n{error_msg}")

    def finish_cancelled(self):
        self.btn_process.config(state="normal")
        self.btn_browse.config(state="normal")
        self.btn_cancel.config(state="disabled")
        self.progress['value'] = 0
        self.status_var.set("Encoding cancelled.")


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
