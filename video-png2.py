import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import cv2
import os
import random
import shutil
import tempfile
from PIL import Image, ImageTk


class VideoExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("影片畫面擷取工具")
        self.root.geometry("960x780")

        self.video_path = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.frame_count = tk.IntVar(value=10)
        self.mode = tk.StringVar(value="固定間隔")

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

        # ROI
        self.roi = None
        self._roi_start_canvas = None
        self._drawing_roi = False

        # Display geometry (updated on resize)
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
        tk.Button(params, text="清除選取範圍", command=self.clear_roi).pack(side=tk.LEFT, padx=10)

        self.extract_btn = tk.Button(params, text="開始擷取", command=self.start_extraction,
                                      bg="lightblue", width=10, state=tk.DISABLED)
        self.extract_btn.pack(side=tk.RIGHT)

        self.canvas.bind("<ButtonPress-1>", self.on_video_press)
        self.canvas.bind("<B1-Motion>", self.on_video_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_video_release)
        self.canvas.bind("<Configure>", self.on_canvas_resize)

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
            self._draw_roi_overlay()

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

    # ========== ROI Selection ==========

    def on_video_press(self, event):
        if not self.video_loaded:
            return
        self._drawing_roi = True
        self._roi_start_canvas = (event.x, event.y)

    def on_video_drag(self, event):
        if not self._drawing_roi or self._roi_start_canvas is None:
            return
        self.canvas.delete("roi_rect")
        x1, y1 = self._roi_start_canvas
        x2, y2 = event.x, event.y
        self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline='red', width=2, tag="roi_rect", dash=(4, 2)
        )

    def on_video_release(self, event):
        if not self._drawing_roi or self._roi_start_canvas is None:
            return
        self._drawing_roi = False
        x1, y1 = self._roi_start_canvas
        x2, y2 = event.x, event.y
        if abs(x2 - x1) < 5 or abs(y2 - y1) < 5:
            self.canvas.delete("roi_rect")
            self.roi = None
            self._roi_start_canvas = None
            return

        vx1, vy1 = self._canvas_to_video(min(x1, x2), min(y1, y2))
        vx2, vy2 = self._canvas_to_video(max(x1, x2), max(y1, y2))
        self.roi = (vx1, vy1, vx2, vy2)

        self.canvas.delete("roi_rect")
        self.canvas.create_rectangle(x1, y1, x2, y2, outline='red', width=2, tag="roi_rect")
        self._roi_start_canvas = None

    def _draw_roi_overlay(self):
        self.canvas.delete("roi_rect")
        if self.roi:
            x1, y1 = self._video_to_canvas(self.roi[0], self.roi[1])
            x2, y2 = self._video_to_canvas(self.roi[2], self.roi[3])
            self.canvas.create_rectangle(x1, y1, x2, y2, outline='red', width=2, tag="roi_rect")

    def clear_roi(self):
        self.roi = None
        self.canvas.delete("roi_rect")

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
                if ret:
                    if self.roi:
                        x1, y1, x2, y2 = self.roi
                        frame = frame[y1:y2 + 1, x1:x2 + 1]

                    ok, buf = cv2.imencode('.png', frame)
                    if ok:
                        out_path = os.path.join(o_path, f"frame_{idx:04d}.png")
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
