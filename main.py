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

        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        self.has_video = False
        self._last_loaded_file = None

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

        # --- Right Sidebar: Media Info ---
        self.sidebar_frame = ttk.LabelFrame(main_container, text="Media Info / 媒体信息", padding=10)
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

        # Resolution Options (for Video)
        self.res_frame = ttk.Frame(self.opts_frame)
        self.res_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(self.res_frame, text="Resolution:").pack(side="left")
        self.resolution_var = tk.StringVar(value="Original")
        self.cbo_resolution = ttk.Combobox(
            self.res_frame,
            textvariable=self.resolution_var,
            values=["Original", "144p", "240p", "360p", "480p", "720p", "1080p", "1440p"],
            state="disabled",
            width=12
        )
        self.cbo_resolution.pack(side="left", padx=5)

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

        # Operations Frame
        self.ops_frame = ttk.Frame(left_container, padding=10)
        self.ops_frame.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Ready")
        self.lbl_status = ttk.Label(self.ops_frame, textvariable=self.status_var, font=("Segoe UI", 10), wraplength=450)
        self.lbl_status.pack(pady=15)

        self.progress = ttk.Progressbar(self.ops_frame, mode='determinate', maximum=100)
        self.progress.pack(fill="x", pady=10)

        self.btn_process = ttk.Button(self.ops_frame, text="Process", command=self.start_processing)
        self.btn_process.pack(pady=10)

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
        ttk.Label(info_inner, text="[ General / 基本信息 ]", font=("Segoe UI", 9, "bold"), foreground="#0066cc").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.lbl_info_name = add_row(1, "Name:")
        self.lbl_info_size = add_row(2, "Size:")
        self.lbl_info_dur = add_row(3, "Duration:")
        self.lbl_info_br = add_row(4, "Bitrate:")

        # Separator
        ttk.Separator(info_inner, orient="horizontal").grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)

        # Video Section
        ttk.Label(info_inner, text="[ Video / 视频流 ]", font=("Segoe UI", 9, "bold"), foreground="#0066cc").grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.lbl_info_vcodec = add_row(7, "Codec:")
        self.lbl_info_res = add_row(8, "Resolution:")
        self.lbl_info_fps = add_row(9, "FPS:")

        # Separator
        ttk.Separator(info_inner, orient="horizontal").grid(row=10, column=0, columnspan=2, sticky="ew", pady=8)

        # Audio Section
        ttk.Label(info_inner, text="[ Audio / 音频流 ]", font=("Segoe UI", 9, "bold"), foreground="#0066cc").grid(row=11, column=0, columnspan=2, sticky="w", pady=(0, 4))
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
        self._update_resolution_state()

    def _display_media_info(self, info):
        if info.get("filepath") != self.file_path_var.get().strip():
            return

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

        if self.trim_var.get() and info.get("duration") and info.get("duration") != "-":
            self.end_time_var.set(info.get("duration"))

    def _update_resolution_state(self):
        convert_fmt = self.convert_var.get()
        if self.has_video and convert_fmt not in ["MP3", "FLAC"]:
            self.cbo_resolution.config(state="readonly")
        else:
            self.cbo_resolution.config(state="disabled")
            self.resolution_var.set("Original")

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
            self.root.after(0, lambda: self._display_media_info(info))

        threading.Thread(target=worker, daemon=True).start()

    def _parse_media_info(self, input_path):
        info = {
            "filename": os.path.basename(input_path),
            "filepath": input_path,
            "filesize": "-",
            "duration": "-",
            "bitrate": "-",
            "has_video": False,
            "video_codec": "-",
            "resolution": "-",
            "fps": "-",
            "has_audio": False,
            "audio_codec": "-",
            "sample_rate": "-",
            "channels": "-",
        }

        if os.path.exists(input_path):
            size_bytes = os.path.getsize(input_path)
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

            dur_match = re.search(r"Duration:\s*(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", stderr_txt)
            if dur_match:
                info["duration"] = dur_match.group(1).split('.')[0]

            br_match = re.search(r"bitrate:\s*(\d+\s*k?b/s)", stderr_txt, re.IGNORECASE)
            if br_match:
                info["bitrate"] = br_match.group(1)

            video_line = re.search(r"Stream #\d+:\d+.*?: Video: (.*)", stderr_txt)
            if video_line:
                v_info = video_line.group(1)
                info["has_video"] = True
                parts = v_info.split(',')
                if parts:
                    info["video_codec"] = parts[0].strip().split()[0]
                res_m = re.search(r"(\d{2,5}x\d{2,5})", v_info)
                if res_m:
                    info["resolution"] = res_m.group(1)
                fps_m = re.search(r"(\d+(?:\.\d+)?)\s*fps", v_info)
                if fps_m:
                    info["fps"] = f"{fps_m.group(1)} fps"

            audio_line = re.search(r"Stream #\d+:\d+.*?: Audio: (.*)", stderr_txt)
            if audio_line:
                a_info = audio_line.group(1)
                info["has_audio"] = True
                parts = a_info.split(',')
                if parts:
                    info["audio_codec"] = parts[0].strip().split()[0]
                sr_m = re.search(r"(\d+\s*Hz)", a_info)
                if sr_m:
                    info["sample_rate"] = sr_m.group(1)
                ch_m = re.search(r"\b(mono|stereo|5\.1|7\.1|\d+\s*channels?)\b", a_info, re.IGNORECASE)
                if ch_m:
                    info["channels"] = ch_m.group(1)

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

        trim_args = None
        if self.trim_var.get():
            start = self.start_time_var.get().strip()
            end = self.end_time_var.get().strip()
            if not start or not end:
                messagebox.showwarning("Warning", "Please enter valid start/end times.")
                return
            trim_args = (start, end)

        if not should_mute and not trim_args and convert_format == "None" and res_choice == "Original":
            messagebox.showinfo("Info", "Nothing to do! Select an option.")
            return

        self.btn_process.config(state="disabled")
        self.btn_browse.config(state="disabled")
        self.progress.config(mode='determinate')
        self.progress['value'] = 0
        self.status_var.set("Processing... 0.0%")

        threading.Thread(
            target=self.process_video,
            args=(input_path, should_mute, convert_format, trim_args, res_choice),
            daemon=True
        ).start()

    def update_progress(self, percent):
        self.progress['value'] = percent
        self.status_var.set(f"Processing... {percent:.1f}%")

    def process_video(self, input_path, should_mute, convert_format, trim_args=None, res_choice="Original"):
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

            suffix = ""
            if should_mute and convert_format not in ["MP3", "FLAC"]:
                suffix += "_muted"
            if trim_args:
                start_str = trim_args[0].replace(":", "-")
                end_str = trim_args[1].replace(":", "-")
                suffix += f"_{start_str}_to_{end_str}"
            if target_h and convert_format not in ["MP3", "FLAC"]:
                suffix += f"_{res_choice}"
            if convert_format != "None":
                suffix += f"_converted_{convert_format.lower()}"

            if not suffix:
                suffix = "_processed"

            output_path = os.path.join(folder, f"{name}{suffix}{ext}")

            cmd = [self.ffmpeg_exe, "-y"]

            if trim_args:
                start_t, end_t = trim_args
                cmd.extend(["-ss", start_t, "-to", end_t])

            cmd.extend(["-i", input_path])

            if target_h and convert_format not in ["MP3", "FLAC"]:
                cmd.extend(["-vf", f"scale=-2:{target_h}"])

            if convert_format == "None":
                if target_h:
                    cmd.extend(["-c:v", "libx264"])
                    if should_mute:
                        cmd.append("-an")
                    else:
                        cmd.extend(["-c:a", "copy"])
                else:
                    if should_mute:
                        cmd.extend(["-c:v", "copy", "-an"])
                    else:
                        cmd.extend(["-c", "copy"])
            elif convert_format == "MP4":
                cmd.extend(["-c:v", "libx264"])
                if should_mute:
                    cmd.append("-an")
                else:
                    cmd.extend(["-c:a", "aac"])
            elif convert_format in ["MP3", "FLAC"]:
                cmd.append("-vn")
                if convert_format == "MP3":
                    cmd.extend(["-c:a", "libmp3lame", "-q:a", "2"])
                elif convert_format == "FLAC":
                    cmd.extend(["-c:a", "flac"])

            cmd.append(output_path)

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                encoding='utf-8',
                errors='replace'
            )

            duration_secs = 0.0
            error_output = []

            duration_re = re.compile(r"Duration: (\d+):(\d+):(\d+\.\d+)")
            time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

            for line in process.stderr:
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
                        self.root.after(0, lambda p=percent: self.update_progress(p))

            process.wait()

            if process.returncode == 0:
                self.root.after(0, lambda p=100.0: self.update_progress(p))
                self.root.after(0, lambda: self.finish_success(output_path))
            else:
                error_msg = "".join(error_output)
                self.root.after(0, lambda: self.finish_error(error_msg))

        except Exception as e:
            self.root.after(0, lambda: self.finish_error(str(e)))

    def finish_success(self, output_path):
        self.btn_process.config(state="normal")
        self.btn_browse.config(state="normal")
        self.status_var.set(f"Done! Saved to:\n{os.path.basename(output_path)}")
        messagebox.showinfo("Success", f"Process completed successfully!\nSaved as: {os.path.basename(output_path)}")

    def finish_error(self, error_msg):
        self.btn_process.config(state="normal")
        self.btn_browse.config(state="normal")
        self.status_var.set("Error occurred.")
        messagebox.showerror("Error", f"Failed to process file.\n{error_msg}")


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
