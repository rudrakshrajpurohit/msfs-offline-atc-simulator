# 🛫 MSFS Offline ATC Simulator

**A fully offline, intelligent ATC simulation system for Microsoft Flight Simulator (MSFS)**  
with a realistic voice experience powered by **Piper neural TTS** and full **ATC state machine logic**.

---

## ✨ Overview

This project simulates realistic Air Traffic Control (ATC) communication across the **entire flight lifecycle** — from cold & dark to parking — using **offline voice synthesis**, **SimBrief integration**, and optional **SimConnect live data**.

It’s designed for:
- Flight sim enthusiasts
- AI/ML and simulation researchers
- Anyone who wants **VATSIM-like realism offline**

The app includes a GUI-based control panel for manually triggering ATC events, monitoring frequency, and testing voice playback without interrupting your flight sim window.

---

## 🎯 Features

### 🗣️ Complete ATC Flow
1. **Clearance Delivery** — route, altitude, squawk  
2. **Pushback & Ground** — taxi instructions  
3. **Tower** — lineup, takeoff, departure handoff  
4. **Departure** — climb instructions  
5. **Center** — cruise monitoring, handoffs  
6. **Approach** — descent, STAR, ILS  
7. **Tower (Arrival)** — landing clearance  
8. **Ground (Arrival)** — taxi to gate, parking complete

### 🧩 Advanced Systems
- **Piper Neural TTS** (offline, natural voice)
- **pyttsx3 fallback** (offline basic voice)
- **SimBrief flight plan import**
- **Optional SimConnect live link** to MSFS
- **GUI control panel**
- **Non-blocking audio**
- **Realistic frequencies** (randomized)
- **Random squawk assignment**
- **Frequency realism & sector handoffs**
- **Airspace awareness**
- **Controller personalities**
- **NATO phonetic output**
- **Force commands** (Force Descent, Force Handoff, etc.)

---

## ⚙️ Installation

### 🧩 Prerequisites
- **Python 3.9+**
- **Windows 10 or 11**
- **Microsoft Flight Simulator (optional)**

### 🛠️ Install Dependencies

```bash
pip install pyttsx3 requests
pip install Python-SimConnect  # optional
pip install pydub              # optional
```

> ⚠️ `pydub` and `ffmpeg` are optional but recommended for better audio.

---

## 🗣️ Installing Piper TTS

1. Download from [Piper GitHub Releases](https://github.com/rhasspy/piper/releases)  
2. Extract to `C:\piper\`
3. Download a voice model like `en_US-lessac-medium.onnx`

---

## 🚀 Running the Application

```bash
python msfs_atc_gui.py
```

You’ll see a GUI with ATC buttons like:
- “Get IFR Clearance”
- “Request Pushback”
- “Force Descent”
- “Contact Next Frequency”

---

## 💬 Example ATC Flow

```
CLEARANCE: “Speedbird One Two Three, cleared to Frankfurt via BUZAD2G, maintain FL370, squawk 4721.”
TOWER: “Runway 27R, cleared for takeoff.”
CENTER: “Maintain flight level three seven zero.”
APPROACH: “Descend and maintain five thousand, expect ILS 25C.”
GROUND: “Taxi to gate via Bravo. Parking complete.”
```

---

## 📄 License

MIT License — Free for personal and educational use.

---

## 🧑‍💻 Author

**Rudraksh Rajpurohit**  
> Inspired by the realism of MSFS and ATC simulation research.
