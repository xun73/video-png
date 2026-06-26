# Video to PNG - 影片轉圖片工具

Extract frames from video with preview, crop, and OCR-based date/time naming.
支援預覽、裁切、OCR 自動命名日期時間的影片截圖工具。

---

## 下載 Download

**Windows 單檔執行檔 (含 Tesseract OCR)：**
[video-png.exe](https://github.com/xun73/video-png/releases/download/v1.0.0/video-png.exe)

**示範影片 (Stellarium 木星)：**
[stellarium.mp4](https://github.com/xun73/video-png/releases/download/v1.0.0/stellarium.mp4)

> 進入 [Releases](https://github.com/xun73/video-png/releases) 頁面也可找到所有版本。

---

## 中文說明

### 功能特色

- 播放影片、拖曳時間軸、設定多個擷取標記
- 圈選裁切範圍（紅色）、日期區域（藍色）、時間區域（綠色）
- OCR 自動辨識日期時間 → 輸出 `YYYYMMDDHHMMSS.png`
- 支援傳統流水號命名 `frame_0000.png`
- 三種繪圖模式切換，按鈕顏色顯示 ROI 設定狀態
- 內建 Tesseract OCR 引擎，無需額外安裝

### 使用方法

1. 下載 `video-png.exe`，解壓後執行
2. 開啟影片檔（支援 mp4/avi/mov 等）
3. 播放到目標畫面，滑鼠雙擊時間軸空白處新增標記
4. 按「圈選裁切範圍」框選輸出區域
5. 按「圈選日期」「圈選時間」框選 OCR 區域
6. 按「測試 OCR」確認辨識結果
7. 選擇命名模式後按「開始擷取」

---

## English

### Features

- Video playback with timeline and draggable markers
- Three independent ROIs: crop (red), date (blue), time (green)
- OCR auto-naming → `YYYYMMDDHHMMSS.png`
- Traditional sequential naming `frame_0000.png`
- Visual draw-mode buttons showing ROI status
- Bundled Tesseract OCR, no setup required

### How to Use

1. Download `video-png.exe`, extract and run
2. Open a video file (mp4/avi/mov etc.)
3. Play to target frame, double-click empty timeline to add markers
4. Click crop button and draw the output region
5. Click date/time buttons and draw the OCR regions
6. Click "Test OCR" to verify recognition
7. Choose naming mode and click "Extract"

---

## Build from Source

```bash
pip install opencv-python pillow pytesseract pyinstaller
pyinstaller --onefile --windowed --add-data "tesseract_portable;tesseract_portable" --name "video-png" video-png.py
```

Tesseract portable must be placed in `tesseract_portable/` directory.
