# 🎵 LirikBar — Musik + Lirik di Taskbar

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](https://github.com/)
[![Stars](https://img.shields.io/github/stars/YOUR_USERNAME/lirikbar?style=social)](https://github.com/YOUR_USERNAME/lirikbar/stargazers)

Aplikasi desktop ringan untuk **memutar musik sambil menampilkan lirik secara real-time** di floating bar yang bisa kamu taruh tepat di atas taskbar (Windows) atau di mana saja di desktop.

> **Fitur unggulan**: Search YouTube & Spotify langsung dari dalam aplikasi + lirik dari LRCLIB + Musixmatch.

---

## Screenshots

### Main Player + Playlist
![Main Player](assets/screenshots/main-player.png)
> Tampilan utama dengan playlist, kontrol playback, dan lirik lengkap.

### Floating Lyrics Bar (Taskbar Mode)
![Lyrics Bar](assets/screenshots/lyrics-bar.png)
> **Ini fitur andalan** — lirik kecil yang selalu di atas, bisa ditarik tepat di atas taskbar.

### Search YouTube & Spotify
![Search Dialog](assets/screenshots/search-dialog.png)
> Cari lagu langsung dari YouTube atau Spotify tanpa harus copy-paste link.

### Settings & API Keys
![Settings](assets/screenshots/settings.png)
> Kelola Musixmatch & Spotify API key dengan mudah.

> **Catatan**: Screenshot di atas adalah placeholder. Silakan ganti dengan tangkapan layar asli dari aplikasi kamu.

---

## Demo

Ingin melihat LirikBar beraksi?

Rekomendasi: Buat demo GIF pendek (8–12 detik) yang menunjukkan:
- Membuka aplikasi
- Menekan tombol **🔍 Search**
- Mencari lagu di YouTube/Spotify
- Lirik Bar muncul dan update otomatis
- Menarik Lyrics Bar ke bawah layar

**Cara membuat demo GIF yang bagus:**
- Gunakan [ScreenToGif](https://www.screentogif.com/) (Windows) atau `peek` (Linux)
- Rekam di resolusi 1280x720 atau lebih kecil
- Simpan sebagai `assets/screenshots/demo.gif`

Contoh placeholder:

![Demo GIF](assets/screenshots/demo.gif)

---

## Fitur Utama

- **Lyrics Bar** (F11): Floating window kecil, always-on-top. Bisa kamu tarik tepat di atas taskbar Windows
- **🔍 Search YouTube & Spotify**: Cari lagu langsung di dalam aplikasi tanpa copy-paste
- **Streaming YouTube & Spotify**: Paste link atau hasil search → otomatis download audio berkualitas + cache pintar
- **Lirik Synced**: Dukungan LRCLIB (paling bagus) + Musixmatch (database terbesar)
- Modern dark UI, system tray, keyboard shortcuts lengkap
- Auto resume playlist + pengaturan tersimpan
- Ringan (bukan Electron) — hanya Python + Tkinter

## Cara Pakai (Super Mudah)

### 1. Install (Windows / Linux / macOS)

```bash
# Clone atau download folder lirikbar

cd lirikbar

# Install dependencies
pip install -r requirements.txt

# Windows (jika pakai python resmi): tkinter sudah include
# Linux (Ubuntu/Pop!_OS/Mint/Debian):
sudo apt install python3-tk ffmpeg -y

# Windows: install ffmpeg dari https://ffmpeg.org (atau pakai scoop/chocolatey)
# Jalankan
python main.py
```

### 2. Menjalankan Lirik di Taskbar

1. Tambah lagu lewat tombol **📂 Tambah File** atau **📁 Tambah Folder**
2. Double-click lagu di playlist → mulai main
3. Tekan tombol **🪟 Lyrics Bar** (atau tekan **F11**)
4. **Tarik** window lirik kecil itu ke bagian bawah layar, tepat di atas taskbar Windows kamu
5. Nikmati! Lirik akan update otomatis mengikuti lagu

Tips: Klik kanan di Lyrics Bar untuk menu cepat (Next, Pause, ganti ukuran font).

## Format Lirik (.lrc)

LirikBar pakai format LRC standar:

```lrc
[00:12.45]Ku ingin kau tahu
[00:16.20]Betapa ku mencintaimu
[00:21.80]Meski kita tak selalu bersama
```

Cara dapatkan:
- Letakkan file `lagu.mp3` + `lagu.lrc` di folder yang sama (otomatis terbaca)
- Atau tekan tombol **🔄 Fetch Lirik** saat lagu sedang diputar (butuh internet)

## Keyboard Shortcuts

| Tombol          | Fungsi                  |
|-----------------|-------------------------|
| `Spasi`         | Play / Pause            |
| `←` `→`         | Mundur / Maju 5 detik   |
| `↑` `↓`         | Volume naik / turun     |
| `Ctrl + N`      | Lagu berikutnya         |
| `Ctrl + P`      | Lagu sebelumnya         |
| `F11`           | Toggle Lyrics Bar       |
| `Esc`           | Tutup Lyrics Bar        |

## Tips & Trik

- **Windows**: Lyrics Bar bisa kamu "nempel" di atas taskbar dengan cara drag manual. Beberapa orang pakai untuk selalu kelihatan saat kerja.
- **Multi monitor**: Lyrics Bar bisa dipindah ke monitor mana saja.
- **Font size**: Klik kanan di bar → Besarkan / Kecilkan font.
- **Auto resume**: Saat kamu buka lagi, LirikBar ingat playlist + posisi terakhir.
- **Tray**: Klik kanan icon di system tray untuk kontrol cepat.

## Troubleshooting

**"No module named tkinter" (Linux)**
```bash
sudo apt install python3-tk python3-pil   # atau distro kamu
```

**Tidak ada suara**
- Pastikan pygame bisa akses audio device
- Coba restart aplikasi
- Format file didukung: mp3, flac, ogg, wav (m4a kadang butuh tambahan)

**Lirik tidak muncul**
- Pastikan file .lrc ada di folder yang sama
- Atau pakai tombol Fetch Lirik (pastikan judul & artist sudah benar di metadata)

## API Keys (Recommended)

Buka **⚙ Settings** di aplikasi untuk mengisi:

| Service       | Dibutuhkan Untuk              | Cara Mendapatkan                              | Gratis?     |
|---------------|-------------------------------|-----------------------------------------------|-------------|
| **Musixmatch**    | Lirik lebih lengkap           | https://developer.musixmatch.com              | Ya (2000 calls/bulan) |
| **Spotify**       | Search lagu langsung di Spotify | https://developer.spotify.com/dashboard       | Ya          |

> **Catatan Spotify**: Pilih "Client Credentials" saat membuat app. Tidak perlu redirect URI.

## Tech Stack

- Python 3 + Tkinter (GUI)
- pygame (audio playback)
- mutagen (baca metadata lagu)
- pystray + Pillow (system tray)
- requests (fetch lirik)
- **yt-dlp** (YouTube + Spotify streaming)

---

## Fitur Baru: YouTube & Spotify Streaming + Musixmatch

### Menambahkan Lagu dari YouTube / Spotify

1. Klik tombol **🌐 Add URL (YT/Spotify)**
2. Paste link YouTube (watch / youtu.be) **atau** link Spotify track
3. LirikBar akan:
   - Otomatis download audio berkualitas tinggi (mp3 192kbps)
   - Cache di `~/.lirikbar/youtube_cache/` (jadi kalau lagu sama dimainkan lagi, langsung dari cache)
   - Untuk Spotify → otomatis cari versi audio terbaik di YouTube

**Catatan penting:**
- Butuh **ffmpeg** terinstall di sistem (untuk konversi audio)
- Download pertama kali agak lama tergantung koneksi & panjang lagu
- Setelah itu cepat karena pakai cache

### Lyrics dari Musixmatch (lebih lengkap)

LirikBar sekarang mencoba **dua sumber** sekaligus:

1. **LRCLIB** (default) — sangat bagus untuk lirik **synced** (.lrc)
2. **Musixmatch** — database lirik terbesar di dunia (tapi butuh API key gratis)

**Cara aktifkan Musixmatch:**
1. Buka **⚙ Settings**
2. Daftar gratis di https://developer.musixmatch.com
3. Copy API key → paste di Settings → Simpan

Kalau Musixmatch aktif, LirikBar akan coba ambil dari sana kalau LRCLIB tidak menemukan.

### Membersihkan Cache YouTube

Di **⚙ Settings** ada tombol "Hapus Cache YouTube" kalau kamu ingin menghemat space.

## Lisensi

Bebas dipakai, dimodifikasi, dan dibagikan.

---

Dibuat dengan ❤️ untuk yang suka dengerin musik sambil ikut nyanyi liriknya.

Selamat menikmati musik + lirik dari YouTube, Spotify link, atau file lokal! 🎤

---

## Development & Git

### Menjalankan dari Source

```bash
git clone https://github.com/YOUR_USERNAME/lirikbar.git
cd lirikbar
pip install -r requirements.txt
python main.py
```

### Push ke Repository Git Kamu Sendiri

```bash
# Di dalam folder lirikbar
git init
git add .
git commit -m "Initial commit: LirikBar with YouTube/Spotify search + streaming"

# Hubungkan ke repo baru kamu di GitHub
git remote add origin https://github.com/YOUR_USERNAME/lirikbar.git
git branch -M main
git push -u origin main
```

Jangan lupa buat repository baru di GitHub terlebih dahulu.

### Setelah Push (Update Badge)

Setelah berhasil push ke GitHub, buka file `README.md` dan ganti semua kata `YOUR_USERNAME` menjadi username GitHub kamu. Setelah itu commit ulang:

```bash
git add README.md
git commit -m "docs: update GitHub username in badges"
git push
```

Badge (License, Stars, dll) akan langsung aktif setelah itu.

### Struktur Project

```
lirikbar/
├── main.py              # Semua kode aplikasi
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
└── (youtube_cache/ dibuat otomatis saat runtime)
```
