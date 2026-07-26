# MediaTinker 🛠️

[English](#english) | [中文](#中文)

---

<a name="english"></a>
## English

**MediaTinker** (`media-tinker`) is a lightweight desktop media processing tool built with **Python** and **FFmpeg**.

Designed for fast and effortless daily media file handling: simply **drag and drop** your file, and easily perform **Cutting**, **Format Conversion**, and **Muting**. No complex FFmpeg commands required — get things done in a clean, straightforward GUI!

### ✨ Key Features

- 🖱️ **Drag & Drop**: Simply drag video/audio files into the app window to start processing immediately.
- ✂️ **Precise Cutting**: Visually set start and end times to trim clips with or without re-encoding.
- 🔄 **Format Conversion**: Convert between popular formats like MP4, MP3, FLAC, etc.
- 🔇 **One-Click Muting**: Instantly remove audio tracks to export pure silent videos or extract standalone audio.
- 🚀 **Fast & Lightweight**: Powered by native `FFmpeg` with low memory usage and quick processing.

### 📦 Prerequisites & Installation

#### 1. Install FFmpeg

`MediaTinker` relies on **FFmpeg** as its backend core. Make sure it is installed and added to your system `PATH`:

- **Windows** (Scoop): `scoop install ffmpeg` or download from [FFmpeg Official Website](https://ffmpeg.org/download.html).

#### 2. Setup & Run

```bash
# Clone repository
git clone [https://github.com/your-username/media-tinker.git](https://github.com/your-username/media-tinker.git)
cd media-tinker

# Install dependencies
pip install -r requirements.txt

# Run the GUI
python -m media_tinker
```





---










<a name="中文"></a>
## 中文

**MediaTinker** (`media-tinker`) 是一个基于 **Python** 与 **FFmpeg** 的轻量级桌面音视频微调工具。

专为高效处理日常媒体文件而设计：只需**拖入文件**，即可快速完成**剪切 (Cut)**、**格式转换 (Convert)** 与 **一键消音 (Mute)**。无需记住复杂的 FFmpeg 命令行，极简视窗一键搞定！

---

## ✨ 核心特性

- 🖱️ **拖拽即用 (Drag & Drop)**：支持直接将音频/视频文件拖入窗口，即刻开始处理。
- ✂️ **精准剪切 (Cut)**：可视化设置起止时间，快速无损或重新编码裁剪片段。
- 🔄 **格式转换 (Convert)**：支持 MP4, MP3, FLAC 等常见格式快速互转。
- 🔇 **一键消音 (Mute)**：一键剥离视频中的音轨，导出纯净无声视频。
- 🚀 **极速轻量**：基于底层原生 `FFmpeg`，内存占用小，响应迅速。

---

## 📦 环境要求与安装

### 1. 安装 FFmpeg

`MediaTinker` 底层依赖 **FFmpeg**，请确保系统中已安装并配置了环境变量：

- **Windows** (Scoop): `scoop install ffmpeg` 或从 [FFmpeg 官网](https://ffmpeg.org/download.html) 下载并添加至系统的 PATH 中。

### 2. 安装与运行

```bash
# 克隆仓库
git clone [https://github.com/your-username/media-tinker.git](https://github.com/your-username/media-tinker.git)
cd media-tinker

# 安装依赖
pip install -r requirements.txt

# 启动 GUI 界面
python -m media_tinker
