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
        self.root.title("Easy Media Editor")
        self.root.geometry("520x600")
        
        if windnd:
            try:
                windnd.hook_dropfiles(self.root, func=self.on_drop_files)
            except Exception:
                pass
        
        # Style
        style = ttk.Style()
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=6)

        # File Selection Frame
        self.file_frame = ttk.LabelFrame(root, text="Source File", padding=10)
        self.file_frame.pack(fill="x", padx=10, pady=10)

        self.file_path_var = tk.StringVar()
        self.entry_path = ttk.Entry(self.file_frame, textvariable=self.file_path_var, width=50)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_browse = ttk.Button(self.file_frame, text="Browse", command=self.browse_file)
        self.btn_browse.pack(side="right")

        # Options Frame (for Trimming and Muting)
        self.opts_frame = ttk.LabelFrame(root, text="Options", padding=10)
        self.opts_frame.pack(fill="x", padx=10, pady=5)

        # Convert Options
        self.convert_var = tk.StringVar(value="None")
        self.convert_frame = ttk.Frame(self.opts_frame)
        self.convert_frame.pack(fill="x", pady=(0, 20))
        
        ttk.Label(self.convert_frame, text="Convert to:").pack(side="left")
        ttk.Radiobutton(self.convert_frame, text="None", variable=self.convert_var, value="None").pack(side="left", padx=5)
        ttk.Radiobutton(self.convert_frame, text="MP4", variable=self.convert_var, value="MP4").pack(side="left", padx=5)
        ttk.Radiobutton(self.convert_frame, text="MP3", variable=self.convert_var, value="MP3").pack(side="left", padx=5)
        ttk.Radiobutton(self.convert_frame, text="FLAC", variable=self.convert_var, value="FLAC").pack(side="left", padx=5)

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
        self.ops_frame = ttk.Frame(root, padding=10)
        self.ops_frame.pack(fill="both", expand=True, padx=10)

        self.status_var = tk.StringVar(value="Ready")
        self.lbl_status = ttk.Label(self.ops_frame, textvariable=self.status_var, font=("Segoe UI", 10))
        self.lbl_status.pack(pady=20)

        self.progress = ttk.Progressbar(self.ops_frame, mode='determinate', maximum=100)
        self.progress.pack(fill="x", pady=10)

        self.btn_process = ttk.Button(self.ops_frame, text="Process", command=self.start_processing)
        self.btn_process.pack(pady=10)
        
        # Footer
        ttk.Label(root, text="Uses imageio-ffmpeg", font=("Segoe UI", 8)).pack(side="bottom", pady=5)
        
        self.ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    def on_drop_files(self, files):
        if not files:
            return
        try:
            # windnd returns byte strings
            try:
                filename = files[0].decode('gbk')
            except UnicodeDecodeError:
                filename = files[0].decode('utf-8', errors='ignore')
                
            filename = filename.strip()
            if os.path.exists(filename):
                self.file_path_var.set(filename)
                self.status_var.set("Ready")
                self._maybe_autofill_end_time(filename)
            else:
                messagebox.showerror("Error", f"Dropped file not found:\n{filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load dropped file: {e}")

    def _maybe_autofill_end_time(self, input_path):
        if not input_path or not os.path.exists(input_path):
            return
        if self.trim_var.get():
            if not hasattr(self, '_last_autofilled_file') or self._last_autofilled_file != input_path:
                try:
                    ffmpeg_exe = self.ffmpeg_exe
                    startupinfo = None
                    if os.name == 'nt':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        
                    result = subprocess.run(
                        [ffmpeg_exe, "-i", input_path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        startupinfo=startupinfo,
                        encoding='utf-8',
                        errors='replace'
                    )
                    match = re.search(r"Duration: (\d{2}:\d{2}:\d{2}(?:\.\d+)?)", result.stderr)
                    if match:
                        self.end_time_var.set(match.group(1))
                        self._last_autofilled_file = input_path
                except Exception:
                    pass

    def toggle_trim(self):
        state = "normal" if self.trim_var.get() else "disabled"
        self.entry_start.config(state=state)
        self.entry_end.config(state=state)
        
        if self.trim_var.get():
            input_path = self.file_path_var.get()
            self._maybe_autofill_end_time(input_path)

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[("Video files", "*.mp4 *.avi *.mkv *.mov *.flv *.wmv *.webm"), ("All files", "*.*")]
        )
        if filename:
            self.file_path_var.set(filename)
            self.status_var.set("Ready")
            self._maybe_autofill_end_time(filename)

    def start_processing(self):
        input_path = self.file_path_var.get()
        if not input_path:
            messagebox.showwarning("Warning", "Please select a file first.")
            return

        if not os.path.exists(input_path):
            messagebox.showerror("Error", "File does not exist.")
            return
            
        should_mute = self.mute_var.get()
        convert_format = self.convert_var.get()

        # Prepare trim args if enabled
        trim_args = None
        if self.trim_var.get():
            start = self.start_time_var.get().strip()
            end = self.end_time_var.get().strip()
            # Basic validation could go here, but ffmpeg might handle formats best
            if not start or not end:
                messagebox.showwarning("Warning", "Please enter valid start/end times.")
                return
            trim_args = (start, end)
            
        if not should_mute and not trim_args and convert_format == "None":
             messagebox.showinfo("Info", "Nothing to do! Select an option.")
             return

        self.btn_process.config(state="disabled")
        self.btn_browse.config(state="disabled")
        self.progress.config(mode='determinate')
        self.progress['value'] = 0
        self.status_var.set("Processing... 0.0%")

        # Run in separate thread to keep UI responsive
        threading.Thread(target=self.process_video, args=(input_path, should_mute, convert_format, trim_args), daemon=True).start()

    def update_progress(self, percent):
        self.progress['value'] = percent
        self.status_var.set(f"Processing... {percent:.1f}%")

    def process_video(self, input_path, should_mute, convert_format, trim_args=None):
        try:
            folder = os.path.dirname(input_path)
            filename = os.path.basename(input_path)
            name, ext = os.path.splitext(filename)
            
            if convert_format != "None":
                ext = f".{convert_format.lower()}"

            suffix = ""
            if should_mute and convert_format not in ["MP3", "FLAC"]:
                suffix += "_muted"
            if trim_args:
                start_str = trim_args[0].replace(":", "-")
                end_str = trim_args[1].replace(":", "-")
                suffix += f"_{start_str}_to_{end_str}"
            if convert_format != "None":
                suffix += f"_converted_{convert_format.lower()}"
                
            # Fallback if no suffix (should be caught by validation, but just in case)
            if not suffix:
                suffix = "_processed"

            output_path = os.path.join(folder, f"{name}{suffix}{ext}")

            # Construct command
            cmd = [self.ffmpeg_exe, "-y"]
            
            if trim_args:
                start_t, end_t = trim_args
                # Place -ss and -to before -i for fast input seeking
                cmd.extend(["-ss", start_t, "-to", end_t])
                
            cmd.extend(["-i", input_path])
            
            if convert_format == "None":
                cmd.extend(["-c", "copy"])
            elif convert_format in ["MP3", "FLAC"]:
                cmd.append("-vn")
                if convert_format == "MP3":
                    cmd.extend(["-c:a", "libmp3lame", "-q:a", "2"])
                elif convert_format == "FLAC":
                    cmd.extend(["-c:a", "flac"])
            
            if should_mute and convert_format not in ["MP3", "FLAC"]:
                cmd.append("-an")
                
            cmd.append(output_path)
            
            # Hide console window on Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # print(f"Command: {cmd}") # Debug

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
                            except:
                                pass

                if duration_secs > 0:
                    match = time_re.search(line)
                    if match:
                        h, m, s = match.groups()
                        current_secs = int(h) * 3600 + int(m) * 60 + float(s)
                        percent = (current_secs / duration_secs) * 100
                        if percent > 100: percent = 100
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

if __name__ == "__main__":
    root = tk.Tk()
    
    # Enable high DPI awareness on Windows
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

    app = AudioRemoverApp(root)
    root.mainloop()
