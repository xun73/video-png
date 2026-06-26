import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import cv2
import os
import random
import re
import shutil
import tempfile
from PIL import Image, ImageTk
import pytesseract

def _find_tesseract():
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    paths = [
        os.path.join(base, 'tesseract_portable', 'tesseract.exe'),
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return 'tesseract'

pytesseract.pytesseract.tesseract_cmd = _find_tesseract()


class VideoExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("影片畫面擷取工具")
        self.root.geometry("960x780")

        self.video_path = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.frame_count = tk.IntVar(value=10)
        self.mode = tk.StringVar(value="固定間隔")
        self.naming_mode = tk.StringVar(value="預設檔名")

        # Video state
        self.cap = None
        self.total_frames = 0
        self.fps = 0.0
        self.current_frame_idx = 0
        self.playing = False
        self._play_after_id = None
        self.video_temp = None
        self.video_loaded = False

        # Extraction markers
        self.extraction_points = []
        self.dragging_marker_idx = -1

        # Crop ROI (red)
        self.roi = None
        # Date ROI (blue) — area where date text appears
        self.date_roi = None
        # Time ROI (green) — area where time text appears
        self.time_roi = None
        self._drawing_roi = False
        self._roi_start_canvas = None
        self._roi_draw_mode = "crop"  # "crop", "date", or "time"

        # Display geometry
        self.video_orig_w = 0
        self.video_orig_h = 0
        self.disp_x = 0
        self.disp_y = 0
        self.disp_w = 0
        self.disp_h = 0
        self.scale = 1.0

        self._img_tk = None

        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ========== UI Setup ==========

    def setup_ui(self):
        root = self.root

        top = tk.Frame(root)
        top.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(top, text="影片檔案:").grid(row=0, column=0, sticky=tk.W)
        tk.Entry(top, textvariable=self.video_path, width=60).grid(row=0, column=1, padx=5)
        tk.Button(top, text="選擇影片", command=self.browse_video).grid(row=0, column=2)

        tk.Label(top, text="輸出資料夾:").grid(row=1, column=0, sticky=tk.W, pady=5)
        tk.Entry(top, textvariable=self.output_folder, width=60).grid(row=1, column=1, padx=5)
        tk.Button(top, text="選擇輸出位置", command=self.browse_folder).grid(row=1, column=2)

        self.video_frame = tk.Frame(root, bg='black')
        self.video_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=2)

        self.canvas = tk.Canvas(self.video_frame, bg='black', cursor='cross', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        ctrl = tk.Frame(root)
        ctrl.pack(fill=tk.X, padx=10, pady=2)

        self.play_btn = tk.Button(ctrl, text="▶ 播放", command=self.toggle_play,
                                  state=tk.DISABLED, width=8)
        self.play_btn.pack(side=tk.LEFT)

        self.time_label = tk.Label(ctrl, text="00:00 / 00:00", width=16)
        self.time_label.pack(side=tk.LEFT, padx=5)

        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_bar = ttk.Scale(ctrl, from_=0.0, to=1000.0, orient=tk.HORIZONTAL,
                                  variable=self.seek_var, command=self.on_seek, state=tk.DISABLED)
        self.seek_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.timeline_frame = tk.Frame(root, height=55)
        self.timeline_frame.pack(fill=tk.X, padx=10, pady=2)

        self.timeline = tk.Canvas(self.timeline_frame, height=40, bg='#e8e8e8', highlightthickness=0)
        self.timeline.pack(fill=tk.X)
        self.timeline.bind("<Button-1>", self.on_timeline_click)
        self.timeline.bind("<B1-Motion>", self.on_timeline_drag)
        self.timeline.bind("<ButtonRelease-1>", self.on_timeline_release)
        self.timeline.bind("<Double-1>", self.on_timeline_double_click)
        self._timeline_hint = tk.Label(self.timeline_frame,
                                       text="單擊拖曳=移動標記  雙擊空白=新增標記  雙擊標記=刪除標記",
                                       fg="#888", font=("", 9))
        self._timeline_hint.pack()

        params = tk.Frame(root)
        params.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(params, text="擷取張數:").pack(side=tk.LEFT)
        tk.Entry(params, textvariable=self.frame_count, width=6).pack(side=tk.LEFT, padx=2)

        tk.Label(params, text="擷取模式:").pack(side=tk.LEFT, padx=10)
        self.mode_combo = ttk.Combobox(params, textvariable=self.mode,
                                       values=["固定間隔", "隨機間隔"], state="readonly", width=10)
        self.mode_combo.pack(side=tk.LEFT)
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_mode_change)

        tk.Button(params, text="生成標記", command=self.generate_markers).pack(side=tk.LEFT, padx=10)
        tk.Button(params, text="清除標記", command=self.clear_markers).pack(side=tk.LEFT)
        tk.Label(params, text="  |  ").pack(side=tk.LEFT)
        self.btn_draw_crop = tk.Button(params, text="圈選裁切範圍", command=self.activate_crop_roi,
                                        bg="#ffcccc", relief=tk.RAISED)
        self.btn_draw_crop.pack(side=tk.LEFT, padx=2)
        tk.Button(params, text="清除裁切範圍", command=self.clear_roi).pack(side=tk.LEFT, padx=2)
        tk.Label(params, text="  ", fg="red").pack(side=tk.LEFT)
        tk.Label(params, text="■裁切範圍", fg="red", font=("", 9)).pack(side=tk.LEFT)
        tk.Button(params, text="測試 OCR", command=self.test_ocr,
                   fg="#666", bg="#f0f0f0").pack(side=tk.RIGHT)

        naming_frame = tk.Frame(root)
        naming_frame.pack(fill=tk.X, padx=10, pady=2)

        tk.Label(naming_frame, text="檔名規則:").pack(side=tk.LEFT)
        self.naming_combo = ttk.Combobox(naming_frame, textvariable=self.naming_mode,
                                          values=["預設檔名", "日期時間命名"], state="readonly", width=14)
        self.naming_combo.pack(side=tk.LEFT, padx=5)
        self.naming_combo.bind("<<ComboboxSelected>>", self.on_naming_mode_change)

        self.subsecond_var = tk.BooleanVar(value=False)
        tk.Checkbutton(naming_frame, text="末2碼", variable=self.subsecond_var).pack(side=tk.LEFT, padx=2)

        self.btn_draw_date = tk.Button(naming_frame, text="圈選日期", command=self.activate_date_roi,
                                        bg="#88ccff", relief=tk.RAISED)
        self.btn_draw_date.pack(side=tk.LEFT, padx=2)
        self.btn_draw_time = tk.Button(naming_frame, text="圈選時間", command=self.activate_time_roi,
                                        bg="#88ff88", relief=tk.RAISED)
        self.btn_draw_time.pack(side=tk.LEFT, padx=2)
        self.btn_clear_ocr = tk.Button(naming_frame, text="清除", command=self.clear_ocr_roi)
        self.btn_clear_ocr.pack(side=tk.LEFT, padx=2)
        tk.Label(naming_frame, text="  ", fg="dodgerblue").pack(side=tk.LEFT)
        tk.Label(naming_frame, text="■日期", fg="dodgerblue", font=("", 9)).pack(side=tk.LEFT)
        tk.Label(naming_frame, text="  ", fg="green").pack(side=tk.LEFT)
        tk.Label(naming_frame, text="■時間", fg="green", font=("", 9)).pack(side=tk.LEFT)
        self.ocr_status = tk.Label(naming_frame, text="", fg="#888")
        self.ocr_status.pack(side=tk.LEFT, padx=5)

        self.extract_btn = tk.Button(naming_frame, text="開始擷取", command=self.start_extraction,
                                      bg="lightblue", width=10, state=tk.DISABLED)
        self.extract_btn.pack(side=tk.RIGHT)

        self.canvas.bind("<ButtonPress-1>", self.on_video_press)
        self.canvas.bind("<B1-Motion>", self.on_video_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_video_release)
        self.canvas.bind("<Configure>", self.on_canvas_resize)

        self.update_roi_ui()

    def update_roi_ui(self):
        """Update button colors: dark=ROI set, light=no ROI."""
        is_date_mode = self.naming_mode.get() == "日期時間命名"
        self.btn_draw_crop.config(bg="#ff6666" if self.roi else "#ffcccc",
                                   state=tk.NORMAL)
        date_state = tk.NORMAL if is_date_mode else tk.DISABLED
        self.btn_draw_date.config(state=date_state,
                                   bg="#4499dd" if self.date_roi else "#88ccff")
        self.btn_draw_time.config(state=date_state,
                                   bg="#44dd44" if self.time_roi else "#88ff88")
        self.btn_clear_ocr.config(state=date_state)
        if not is_date_mode:
            self.ocr_status.config(text="", fg="#888")
        else:
            parts = []
            if self.date_roi:
                parts.append(f"日期{self.date_roi[2]-self.date_roi[0]}x{self.date_roi[3]-self.date_roi[1]}")
            if self.time_roi:
                parts.append(f"時間{self.time_roi[2]-self.time_roi[0]}x{self.time_roi[3]-self.time_roi[1]}")
            if parts:
                self.ocr_status.config(text="已圈選 " + "+".join(parts), fg="green")
            else:
                self.ocr_status.config(text="尚未圈選", fg="#888")

    # ========== File Dialogs ==========

    def browse_video(self):
        path = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv")])
        if path:
            self.video_path.set(path)
            default_out = os.path.join(os.path.dirname(path), "temp")
            self.output_folder.set(default_out)
            self.load_video()

    def browse_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.output_folder.set(path)

    # ========== Video Loading ==========

    def load_video(self):
        self.stop_playback()
        self.clear_markers()
        self.clear_roi()
        self.clear_ocr_roi()
        self._roi_draw_mode = "crop"
        self.video_loaded = False

        v_path = self.video_path.get()
        if not os.path.exists(v_path):
            return

        if self.cap:
            self.cap.release()
            self.cap = None
        if self.video_temp and os.path.exists(self.video_temp):
            try:
                os.remove(self.video_temp)
            except OSError:
                pass
            self.video_temp = None

        try:
            if any(ord(c) > 127 for c in v_path):
                ext = os.path.splitext(v_path)[1]
                self.video_temp = os.path.join(
                    tempfile.gettempdir(),
                    f"_vid_{random.randint(100000, 999999)}{ext}"
                )
                shutil.copy2(v_path, self.video_temp)
                cap = cv2.VideoCapture(self.video_temp)
            else:
                cap = cv2.VideoCapture(v_path)

            if not cap.isOpened():
                messagebox.showerror("錯誤", "無法開啟影片檔案")
                return

            self.cap = cap
            self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = cap.get(cv2.CAP_PROP_FPS)
            self.video_orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.video_orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if self.total_frames <= 0:
                messagebox.showerror("錯誤", "無法讀取影片幀數")
                self.cap.release()
                self.cap = None
                return

            self.current_frame_idx = 0
            self.video_loaded = True

            self.play_btn.config(state=tk.NORMAL)
            self.seek_bar.config(state=tk.NORMAL)
            self.extract_btn.config(state=tk.NORMAL)

            self.seek_to(0)

        except Exception as e:
            messagebox.showerror("錯誤", f"載入影片失敗：{e}")

    # ========== Frame Display ==========

    def seek_to(self, frame_idx):
        if not self.cap:
            return
        frame_idx = max(0, min(frame_idx, self.total_frames - 1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if ret:
            self.current_frame_idx = frame_idx
            self._show_frame(frame)
            self._update_time_label()
            self._update_seek_bar()
            self._redraw_timeline()
            self._draw_all_overlays()

    def _show_frame(self, frame):
        if frame is None:
            return

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)

        cw = self.canvas.winfo_width() or 640
        ch = self.canvas.winfo_height() or 480
        if cw < 10 or ch < 10:
            cw, ch = 640, 480

        iw, ih = img.size
        scale = min(cw / iw, ch / ih)
        dw = int(iw * scale)
        dh = int(ih * scale)
        dx = (cw - dw) // 2
        dy = (ch - dh) // 2

        self.disp_x, self.disp_y = dx, dy
        self.disp_w, self.disp_h = dw, dh
        self.scale = scale

        resized = img.resize((dw, dh), Image.LANCZOS)
        self._img_tk = ImageTk.PhotoImage(resized)

        self.canvas.delete("video_frame")
        self.canvas.create_image(dx, dy, anchor=tk.NW, image=self._img_tk, tag="video_frame")
        self.canvas.tag_lower("video_frame")

    # ========== Coordinate Conversion ==========

    def _canvas_to_video(self, cx, cy):
        if self.scale <= 0:
            return (0, 0)
        vx = (cx - self.disp_x) / self.scale
        vy = (cy - self.disp_y) / self.scale
        vx = max(0, min(vx, self.video_orig_w - 1))
        vy = max(0, min(vy, self.video_orig_h - 1))
        return (int(vx), int(vy))

    def _video_to_canvas(self, vx, vy):
        cx = vx * self.scale + self.disp_x
        cy = vy * self.scale + self.disp_y
        return (int(cx), int(cy))

    # ========== ROI Drawing (both crop & ocr) ==========

    def _reset_draw_buttons(self):
        self.btn_draw_crop.config(relief=tk.RAISED)
        self.btn_draw_date.config(relief=tk.RAISED)
        self.btn_draw_time.config(relief=tk.RAISED)
        if self._roi_draw_mode == "crop":
            self.btn_draw_crop.config(relief=tk.SUNKEN)
        elif self._roi_draw_mode == "date":
            self.btn_draw_date.config(relief=tk.SUNKEN)
        elif self._roi_draw_mode == "time":
            self.btn_draw_time.config(relief=tk.SUNKEN)
        self.update_roi_ui()

    def activate_crop_roi(self):
        self._roi_draw_mode = "crop"
        self.canvas.config(cursor="cross")
        self._reset_draw_buttons()

    def activate_date_roi(self):
        self._roi_draw_mode = "date"
        self.canvas.config(cursor="cross")
        self._reset_draw_buttons()

    def activate_time_roi(self):
        self._roi_draw_mode = "time"
        self.canvas.config(cursor="cross")
        self._reset_draw_buttons()

    def on_video_press(self, event):
        if not self.video_loaded:
            return
        self._drawing_roi = True
        self._roi_start_canvas = (event.x, event.y)

    def on_video_drag(self, event):
        if not self._drawing_roi or self._roi_start_canvas is None:
            return
        mode = self._roi_draw_mode
        tag_map = {"crop": "roi_rect", "date": "date_roi_rect", "time": "time_roi_rect"}
        color_map = {"crop": "red", "date": "dodgerblue", "time": "green"}
        tag = tag_map[mode]
        self.canvas.delete(tag)
        x1, y1 = self._roi_start_canvas
        x2, y2 = event.x, event.y
        dash = None if mode == "crop" else (4, 2)
        self.canvas.create_rectangle(x1, y1, x2, y2, outline=color_map[mode], width=2, tag=tag, dash=dash)

    def on_video_release(self, event):
        if not self._drawing_roi or self._roi_start_canvas is None:
            return
        self._drawing_roi = False
        x1, y1 = self._roi_start_canvas
        x2, y2 = event.x, event.y
        if abs(x2 - x1) < 5 or abs(y2 - y1) < 5:
            tag_map = {"crop": "roi_rect", "date": "date_roi_rect", "time": "time_roi_rect"}
            self.canvas.delete(tag_map[self._roi_draw_mode])
            if self._roi_draw_mode == "crop":
                self.roi = None
            elif self._roi_draw_mode == "date":
                self.date_roi = None
            elif self._roi_draw_mode == "time":
                self.time_roi = None
            self._reset_draw_buttons()
            self._roi_start_canvas = None
            return

        vx1, vy1 = self._canvas_to_video(min(x1, x2), min(y1, y2))
        vx2, vy2 = self._canvas_to_video(max(x1, x2), max(y1, y2))
        mode = self._roi_draw_mode
        color_map = {"crop": "red", "date": "dodgerblue", "time": "green"}
        tag_map = {"crop": "roi_rect", "date": "date_roi_rect", "time": "time_roi_rect"}

        self.canvas.delete(tag_map[mode])
        self.canvas.create_rectangle(x1, y1, x2, y2, outline=color_map[mode], width=2, tag=tag_map[mode])

        if mode == "crop":
            self.roi = (vx1, vy1, vx2, vy2)
        elif mode == "date":
            self.date_roi = (vx1, vy1, vx2, vy2)
        elif mode == "time":
            self.time_roi = (vx1, vy1, vx2, vy2)

        self._roi_draw_mode = "crop"
        self._reset_draw_buttons()
        self._roi_start_canvas = None

    def _draw_all_overlays(self):
        self.canvas.delete("roi_rect", "date_roi_rect", "time_roi_rect")
        if self.roi:
            x1, y1 = self._video_to_canvas(self.roi[0], self.roi[1])
            x2, y2 = self._video_to_canvas(self.roi[2], self.roi[3])
            self.canvas.create_rectangle(x1, y1, x2, y2, outline='red', width=2, tag="roi_rect")
        if self.date_roi:
            x1, y1 = self._video_to_canvas(self.date_roi[0], self.date_roi[1])
            x2, y2 = self._video_to_canvas(self.date_roi[2], self.date_roi[3])
            self.canvas.create_rectangle(x1, y1, x2, y2, outline='dodgerblue', width=2, tag="date_roi_rect")
        if self.time_roi:
            x1, y1 = self._video_to_canvas(self.time_roi[0], self.time_roi[1])
            x2, y2 = self._video_to_canvas(self.time_roi[2], self.time_roi[3])
            self.canvas.create_rectangle(x1, y1, x2, y2, outline='green', width=2, tag="time_roi_rect")

    def clear_roi(self):
        self.roi = None
        self.canvas.delete("roi_rect")
        self.update_roi_ui()

    def clear_ocr_roi(self):
        self.date_roi = None
        self.time_roi = None
        self.canvas.delete("date_roi_rect", "time_roi_rect")
        self.update_roi_ui()

    # ========== Canvas Resize ==========

    def on_canvas_resize(self, event):
        if self.video_loaded:
            self.seek_to(self.current_frame_idx)

    # ========== Playback ==========

    def toggle_play(self):
        if self.playing:
            self.pause_playback()
        else:
            self.start_playback()

    def start_playback(self):
        if not self.video_loaded:
            return
        self.playing = True
        self.play_btn.config(text="❚❚ 暫停")
        self._schedule_next()

    def _schedule_next(self):
        if not self.playing or not self.cap:
            return
        ret, frame = self.cap.read()
        if ret:
            self.current_frame_idx += 1
            self._show_frame(frame)
            self._update_time_label()
            self._update_seek_bar()
            self._redraw_timeline()
            self._draw_all_overlays()
            delay = max(1, int(1000 / self.fps))
            self._play_after_id = self.root.after(delay, self._schedule_next)
        else:
            self.pause_playback()
            self.seek_to(0)

    def pause_playback(self):
        self.playing = False
        self.play_btn.config(text="▶ 播放")
        if self._play_after_id:
            self.root.after_cancel(self._play_after_id)
            self._play_after_id = None

    def stop_playback(self):
        self.pause_playback()

    # ========== Seek Bar ==========

    def on_seek(self, val):
        if not self.video_loaded or self.playing:
            return
        ratio = float(val) / 1000.0
        target = int(ratio * (self.total_frames - 1))
        self.seek_to(target)

    def _update_seek_bar(self):
        if self.total_frames > 1:
            ratio = self.current_frame_idx / (self.total_frames - 1)
            self.seek_var.set(ratio * 1000.0)

    def _update_time_label(self):
        if self.fps <= 0:
            return
        cur = self.current_frame_idx / self.fps
        tot = self.total_frames / self.fps
        self.time_label.config(text=f"{self._fmt_time(cur)} / {self._fmt_time(tot)}")

    @staticmethod
    def _fmt_time(sec):
        m = int(sec // 60)
        s = int(sec % 60)
        return f"{m:02d}:{s:02d}"

    # ========== Mode Change ==========

    def on_mode_change(self, event=None):
        pass

    def on_naming_mode_change(self, event=None):
        self.update_roi_ui()

    # ========== Timeline & Markers ==========

    def generate_markers(self):
        if not self.video_loaded:
            return
        count = self.frame_count.get()
        if count <= 0:
            return

        self.extraction_points = []
        if self.mode.get() == "固定間隔":
            interval = max(1, self.total_frames // count)
            self.extraction_points = [i * interval for i in range(count)]
        else:
            cnt = min(count, self.total_frames)
            self.extraction_points = sorted(random.sample(range(self.total_frames), cnt))

        self._redraw_timeline()

    def clear_markers(self):
        self.extraction_points = []
        self._redraw_timeline()

    def _redraw_timeline(self):
        self.timeline.delete("all")
        cw = self.timeline.winfo_width() or 600
        if cw < 10:
            cw = 600

        h = 40
        bar_y = 28
        bar_h = 6
        x0, x1 = 10, cw - 10
        if x1 <= x0:
            return

        self.timeline.create_rectangle(x0, bar_y, x1, bar_y + bar_h, fill='#ccc', outline='', tag="bar")

        if self.total_frames > 1:
            ratio = self.current_frame_idx / (self.total_frames - 1)
            px = x0 + ratio * (x1 - x0)
            self.timeline.create_line(px, 0, px, h, fill='#666', width=2, tag="pos")

        for i, fidx in enumerate(self.extraction_points):
            ratio = fidx / max(1, self.total_frames - 1)
            mx = x0 + ratio * (x1 - x0)
            self.timeline.create_line(
                mx, bar_y - 10, mx, bar_y + bar_h + 10,
                fill='red', width=3, tags=("marker", f"m_{i}")
            )
            r = 6
            self.timeline.create_oval(
                mx - r, bar_y - r - 10, mx + r, bar_y + r + 10,
                fill='red', outline='darkred', width=2,
                tags=("marker", f"m_{i}")
            )

    def on_timeline_click(self, event):
        if not self.video_loaded:
            return
        cw = self.timeline.winfo_width() or 600
        if cw < 10:
            return
        x0, x1 = 10, cw - 10
        if x1 <= x0:
            return

        for i, fidx in enumerate(self.extraction_points):
            ratio = fidx / max(1, self.total_frames - 1)
            mx = x0 + ratio * (x1 - x0)
            if abs(event.x - mx) < 10:
                self.dragging_marker_idx = i
                return

        ratio = (event.x - x0) / (x1 - x0)
        ratio = max(0, min(1, ratio))
        self.seek_to(int(ratio * (self.total_frames - 1)))

    def on_timeline_double_click(self, event):
        if not self.video_loaded:
            return
        cw = self.timeline.winfo_width() or 600
        if cw < 10:
            return
        x0, x1 = 10, cw - 10
        if x1 <= x0:
            return

        for i, fidx in enumerate(self.extraction_points):
            ratio = fidx / max(1, self.total_frames - 1)
            mx = x0 + ratio * (x1 - x0)
            if abs(event.x - mx) < 10:
                del self.extraction_points[i]
                self.frame_count.set(len(self.extraction_points))
                self._redraw_timeline()
                return

        ratio = (event.x - x0) / (x1 - x0)
        ratio = max(0, min(1, ratio))
        target = int(ratio * (self.total_frames - 1))
        self.extraction_points.append(target)
        self.extraction_points.sort()
        self.frame_count.set(len(self.extraction_points))
        self._redraw_timeline()
        self.seek_to(target)

    def on_timeline_drag(self, event):
        if self.dragging_marker_idx < 0 or not self.video_loaded:
            return
        cw = self.timeline.winfo_width() or 600
        if cw < 10:
            return
        x0, x1 = 10, cw - 10
        if x1 <= x0:
            return
        ratio = (event.x - x0) / (x1 - x0)
        ratio = max(0, min(1, ratio))
        target = int(ratio * (self.total_frames - 1))
        self.extraction_points[self.dragging_marker_idx] = target
        self.seek_to(target)

    def on_timeline_release(self, event):
        self.dragging_marker_idx = -1

    # ========== OCR ==========

    def _ocr_region_parsed(self, frame, roi, parser):
        """Run OCR on a region, return the first successfully parsed result."""
        if roi is None:
            return None
        x1, y1, x2, y2 = roi
        crop = frame[y1:y2 + 1, x1:x2 + 1]
        if crop.size == 0:
            return None

        enlarged = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        _, bin_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if bin_otsu.mean() < 127:
            bin_otsu = cv2.bitwise_not(bin_otsu)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        bin_dilate = cv2.dilate(bin_otsu.copy(), kernel, iterations=1)

        big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        gray2 = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray2)
        _, bin_clahe = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if bin_clahe.mean() < 127:
            bin_clahe = cv2.bitwise_not(bin_clahe)
        bin_adapt = cv2.adaptiveThreshold(gray2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                           cv2.THRESH_BINARY, 31, 2)

        preps = [
            ('4x_CLAHE', bin_clahe),
            ('4x_Adaptive', bin_adapt),
            ('3x_Otsu', bin_otsu),
            ('3x_Otsu+膨脹', bin_dilate),
        ]
        cfgs = [
            ('PSM6+白名單', '--psm 6 -c tessedit_char_whitelist=0123456789-: '),
            ('PSM6 一般',   '--psm 6'),
            ('PSM7+白名單', '--psm 7 -c tessedit_char_whitelist=0123456789-: '),
            ('PSM7 一般',   '--psm 7'),
            ('PSM8+白名單', '--psm 8 -c tessedit_char_whitelist=0123456789-: '),
            ('PSM8 一般',   '--psm 8'),
        ]

        best_result = None
        best_score = -1
        for pname, pimg in preps:
            for cname, cfg in cfgs:
                text = pytesseract.image_to_string(pimg, lang='eng', config=cfg).strip()
                result = parser(text)
                if result:
                    numbers = re.findall(r'\d+', text)
                    nd = sum(len(n) for n in numbers)
                    nn = len(numbers)
                    score = (100 if nn == 3 else 0) + nd
                    if score >= best_score:
                        best_score = score
                        best_result = result
        return best_result

    @staticmethod
    def _parse_date_text(text):
        """從日期文字取出 YYYYMMDD。"""
        if not text:
            return None
        numbers = re.findall(r'\d+', text)
        for i, num in enumerate(numbers):
            if len(num) == 4 and num.startswith('20'):
                if len(numbers) >= i + 3:
                    y = num.zfill(4)
                    m = numbers[i+1].zfill(2)
                    d = numbers[i+2].zfill(2)
                    if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
                        return f"{y}{m}{d}"
        return None

    @staticmethod
    def _parse_time_text(text):
        """從時間文字取出 HHMMSS。"""
        if not text:
            return None
        numbers = re.findall(r'\d+', text)
        if len(numbers) >= 3:
            h, m, s = numbers[-3], numbers[-2], numbers[-1]
        elif len(numbers) == 2:
            h, m, s = '00', numbers[-2], numbers[-1]
        else:
            return None
        hi, mi, si = int(h), int(m), int(s)
        if hi <= 23 and mi <= 59 and si <= 59:
            return f"{hi:02d}{mi:02d}{si:02d}"
        return None

    def _ocr_frame_datetime(self, frame):
        """分別 OCR 日期區與時間區，回傳 14 位數字或 None。"""
        if not self.date_roi or not self.time_roi:
            return None
        d = self._ocr_region_parsed(frame, self.date_roi, self._parse_date_text)
        t = self._ocr_region_parsed(frame, self.time_roi, self._parse_time_text)
        if d and t:
            return d + t
        return None

    def _test_region_ocr_data(self, frame, roi, parser):
        """Test all OCR combos on one region, return list of result dicts."""
        if roi is None:
            return None
        x1, y1, x2, y2 = roi
        crop = frame[y1:y2 + 1, x1:x2 + 1]
        if crop.size == 0:
            return None

        enlarged = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        _, bin_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if bin_otsu.mean() < 127:
            bin_otsu = cv2.bitwise_not(bin_otsu)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        bin_dilate = cv2.dilate(bin_otsu.copy(), kernel, iterations=1)

        big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        gray2 = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray2)
        _, bin_clahe = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if bin_clahe.mean() < 127:
            bin_clahe = cv2.bitwise_not(bin_clahe)
        bin_adapt = cv2.adaptiveThreshold(gray2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                           cv2.THRESH_BINARY, 31, 2)

        preps = [
            ('4x_CLAHE', bin_clahe),
            ('4x_Adaptive', bin_adapt),
            ('3x_Otsu', bin_otsu),
            ('3x_Otsu+膨脹', bin_dilate),
        ]
        cfgs = [
            ('PSM6+白名單', '--psm 6 -c tessedit_char_whitelist=0123456789-: '),
            ('PSM6 一般',   '--psm 6'),
            ('PSM7+白名單', '--psm 7 -c tessedit_char_whitelist=0123456789-: '),
            ('PSM7 一般',   '--psm 7'),
            ('PSM8+白名單', '--psm 8 -c tessedit_char_whitelist=0123456789-: '),
            ('PSM8 一般',   '--psm 8'),
        ]

        rows = []
        for pname, pimg in preps:
            for cname, cfg in cfgs:
                text = pytesseract.image_to_string(pimg, lang='eng', config=cfg).strip()
                numbers = re.findall(r'\d+', text)
                parsed = parser(text)
                rows.append((pname, cname, text, numbers, parsed))
        return rows

    def test_ocr(self):
        if not self.video_loaded or not self.cap:
            return
        if not self.date_roi and not self.time_roi:
            messagebox.showinfo("測試 OCR", "請先圈選日期區域和時間區域")
            return

        points = list(self.extraction_points)
        if not points:
            points = [self.current_frame_idx]
        points = sorted(set(points))

        debug_dir = os.path.dirname(self.video_path.get())
        log_path = os.path.join(debug_dir, "_ocr_debug.txt")
        ok_count = 0

        with open(log_path, 'w', encoding='utf-8') as f:
            for idx in points:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = self.cap.read()
                if not ret:
                    f.write(f"========== Frame {idx} ==========\n讀取失敗\n\n")
                    continue

                f.write(f"========== Frame {idx} ==========\n")

                for roi, label, parser in [
                    (self.date_roi, "日期", self._parse_date_text),
                    (self.time_roi, "時間", self._parse_time_text),
                ]:
                    if roi is None:
                        f.write(f"--- {label}: 未圈選 ---\n\n")
                        continue
                    x1, y1, x2, y2 = roi
                    f.write(f"--- {label} ({(x2-x1)+1}x{(y2-y1)+1}) ---\n")
                    rows = self._test_region_ocr_data(frame, roi, parser)
                    if rows is None:
                        f.write("區域無效\n\n")
                        continue
                    best_result = None
                    best_score = -1
                    for pname, cname, text, numbers, parsed in rows:
                        f.write(f"=== {pname} + {cname} ===\n")
                        f.write(f"原始: {text or '(空白)'}\n")
                        f.write(f"數字: {numbers}\n")
                        f.write(f"結果: {parsed or '辨識失敗'}\n\n")
                        if parsed:
                            nd = sum(len(n) for n in numbers)
                            nn = len(numbers)
                            score = (100 if nn == 3 else 0) + nd
                            if score >= best_score:
                                best_score = score
                                best_result = parsed
                    f.write(f"最佳: {best_result or '辨識失敗'}\n\n")

                date_result = self._ocr_region_parsed(frame, self.date_roi, self._parse_date_text)
                time_result = self._ocr_region_parsed(frame, self.time_roi, self._parse_time_text)
                if date_result and time_result:
                    final = date_result + time_result
                    ok_count += 1
                else:
                    final = None
                f.write(f"最終採用: {final or '辨識失敗'}\n\n")

        messagebox.showinfo("測試 OCR 結果",
            f"共測試 {len(points)} 幀 ({ok_count} 幀成功)\n"
            f"結果已寫入檔案，請用記事本開啟：\n{log_path}")
        os.startfile(log_path)

    # ========== Extraction ==========

    def start_extraction(self):
        if not self.video_loaded or not self.cap:
            return

        o_path = self.output_folder.get()
        if not o_path:
            messagebox.showerror("錯誤", "請設定輸出資料夾")
            return

        if not os.path.exists(o_path):
            os.makedirs(o_path)

        use_date_naming = self.naming_mode.get() == "日期時間命名"
        if use_date_naming and (not self.date_roi or not self.time_roi):
            messagebox.showerror("錯誤", "請先圈選日期區域和時間區域")
            return

        points = list(self.extraction_points)
        if not points:
            count = self.frame_count.get()
            if count <= 0:
                messagebox.showerror("錯誤", "請設定擷取張數")
                return
            if self.mode.get() == "固定間隔":
                interval = max(1, self.total_frames // count)
                points = [i * interval for i in range(count)]
            else:
                cnt = min(count, self.total_frames)
                points = sorted(random.sample(range(self.total_frames), cnt))

        saved = 0
        try:
            for idx, frame_idx in enumerate(points):
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = self.cap.read()
                if not ret:
                    continue

                if self.roi:
                    rx1, ry1, rx2, ry2 = self.roi
                    out_img = frame[ry1:ry2 + 1, rx1:rx2 + 1]
                else:
                    out_img = frame

                ok, buf = cv2.imencode('.png', out_img)
                if not ok:
                    continue

                if use_date_naming:
                    dt_str = self._ocr_frame_datetime(frame)
                    if dt_str:
                        name = dt_str if self.subsecond_var.get() else dt_str[:12]
                        filename = f"{name}.png"
                    else:
                        filename = f"frame_{idx:04d}.png"
                else:
                    filename = f"frame_{idx:04d}.png"

                out_path = os.path.join(o_path, filename)
                with open(out_path, 'wb') as f:
                    f.write(buf.tobytes())
                saved += 1

            msg = f"已成功擷取 {saved} 張畫面到：\n{o_path}"
            if messagebox.askyesno("完成", msg + "\n\n是否開啟資料夾？"):
                os.startfile(o_path)

        except Exception as e:
            messagebox.showerror("錯誤", f"擷取失敗：{e}")

    # ========== Cleanup ==========

    def on_close(self):
        self.stop_playback()
        if self.cap:
            self.cap.release()
        if self.video_temp and os.path.exists(self.video_temp):
            try:
                os.remove(self.video_temp)
            except OSError:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = VideoExtractorApp(root)
    root.mainloop()
