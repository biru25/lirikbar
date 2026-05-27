#!/usr/bin/env python3
"""
LirikBar - Aplikasi Musik + Lirik di Taskbar
Dengar musik sambil lirik selalu muncul di dekat taskbar (desktop overlay)
"""

import pygame
import threading
import time
import os
import re
import json
import requests
from pathlib import Path
from mutagen import File as MutagenFile
# Tkinter + GUI-only imports are done lazily inside LirikBarApp (so the script can be imported for tests)

# ==================== CONFIG ====================
APP_NAME = "LirikBar"
CONFIG_FILE = Path.home() / ".lirikbar" / "config.json"
os.makedirs(CONFIG_FILE.parent, exist_ok=True)

# Colors - dark modern
BG_DARK = "#0f0f1a"
BG_CARD = "#16162a"
ACCENT = "#ff4d94"
ACCENT2 = "#7c3aed"
TEXT_PRIMARY = "#f0f0f5"
TEXT_SECONDARY = "#a1a1b5"
TEXT_MUTED = "#6b6b80"

# ==================== LRC PARSER ====================
class LRCParser:
    """Parser untuk format LRC (synced lyrics)"""
    
    TIME_RE = re.compile(r'\[(\d+):(\d{2})(?:\.(\d{2,3}))?\]')
    
    @staticmethod
    def parse(lrc_text: str):
        """
        Parse LRC text -> list of (timestamp_ms, lyric_line)
        """
        lines = []
        for raw in lrc_text.strip().splitlines():
            raw = raw.strip()
            if not raw or raw.startswith(('[ti:', '[ar:', '[al:', '[by:', '[offset:')):
                continue
            
            matches = list(LRCParser.TIME_RE.finditer(raw))
            if not matches:
                continue
            
            # Ambil lyric setelah semua tag waktu
            lyric = LRCParser.TIME_RE.sub('', raw).strip()
            if not lyric:
                lyric = "♪ Instrumental ♪"
            
            for m in matches:
                mm, ss, ms = m.groups()
                minutes = int(mm)
                seconds = int(ss)
                millis = int(ms.ljust(3, '0')) if ms else 0
                total_ms = (minutes * 60 + seconds) * 1000 + millis
                lines.append((total_ms, lyric))
        
        lines.sort(key=lambda x: x[0])
        # Remove duplicate times
        seen = set()
        unique = []
        for t, l in lines:
            if t not in seen:
                seen.add(t)
                unique.append((t, l))
        return unique
    
    @staticmethod
    def get_current(lyrics, pos_ms, default=""):
        """Return (prev, current, next) lines berdasarkan posisi saat ini"""
        if not lyrics:
            return ("", default or "♪", "")
        
        idx = 0
        for i, (t, _) in enumerate(lyrics):
            if t <= pos_ms:
                idx = i
            else:
                break
        
        prev = lyrics[idx-1][1] if idx > 0 else ""
        curr = lyrics[idx][1]
        nxt = lyrics[idx+1][1] if idx+1 < len(lyrics) else ""
        return (prev, curr, nxt)
    
    @staticmethod
    def get_full_text(lyrics):
        return "\n".join(l for _, l in lyrics)


# ==================== AUDIO PLAYER ====================
class AudioPlayer:
    def __init__(self):
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        self.current_path = None
        self.duration_ms = 0
        self.start_offset = 0  # untuk seek
        self._playing = False
        self._end_event = pygame.USEREVENT + 1
        pygame.mixer.music.set_endevent(self._end_event)
        
    def load(self, path: str, duration_hint: float = 0):
        self.stop()
        try:
            pygame.mixer.music.load(path)
            self.current_path = path
            self.duration_ms = int(duration_hint * 1000) if duration_hint else 0
            self.start_offset = 0
            return True
        except Exception as e:
            print("Load error:", e)
            return False
    
    def play(self, start_ms: int = 0):
        if not self.current_path:
            return
        try:
            secs = max(0, start_ms / 1000.0)
            pygame.mixer.music.play(start=secs)
            self.start_offset = start_ms
            self._playing = True
        except Exception as e:
            print("Play error:", e)
    
    def pause(self):
        pygame.mixer.music.pause()
        self._playing = False
    
    def unpause(self):
        pygame.mixer.music.unpause()
        self._playing = True
    
    def stop(self):
        pygame.mixer.music.stop()
        self._playing = False
        self.start_offset = 0
    
    def toggle(self):
        if self.is_playing():
            self.pause()
        else:
            if pygame.mixer.music.get_busy():
                self.unpause()
            else:
                self.play(self.start_offset)
    
    def is_playing(self):
        return self._playing and pygame.mixer.music.get_busy()
    
    def get_pos_ms(self):
        """Posisi saat ini dalam milidetik"""
        if not self.current_path:
            return 0
        pos = pygame.mixer.music.get_pos()
        if pos < 0:
            pos = 0
        return self.start_offset + pos
    
    def seek(self, target_ms: int):
        """Seek dengan restart playback (paling reliable di pygame)"""
        if not self.current_path:
            return
        was_playing = self.is_playing()
        self.stop()
        target_ms = max(0, min(target_ms, self.duration_ms - 500))
        if was_playing:
            self.play(target_ms)
        else:
            self.start_offset = target_ms
    
    def set_volume(self, vol: float):
        """0.0 - 1.0"""
        pygame.mixer.music.set_volume(max(0.0, min(1.0, vol)))
    
    def get_volume(self):
        return pygame.mixer.music.get_volume()
    
    def check_ended(self):
        """Cek event selesai lagu"""
        for event in pygame.event.get():
            if event.type == self._end_event:
                return True
        return False
    
    def close(self):
        pygame.mixer.quit()


# ==================== YOUTUBE / SPOTIFY PROVIDER ====================
CACHE_DIR = Path.home() / ".lirikbar" / "youtube_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

class YouTubeProvider:
    """
    Handles:
    - YouTube direct links → audio download (cached)
    - Spotify track links → resolve title/artist → search YouTube → download
    Uses yt-dlp for everything. Very reliable.
    """

    def __init__(self):
        self.ydl_opts_base = {
            'format': 'bestaudio/best',
            'outtmpl': str(CACHE_DIR / '%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'noplaylist': True,
        }

    def is_youtube_url(self, url: str) -> bool:
        return any(x in url.lower() for x in ['youtube.com/watch', 'youtu.be/', 'youtube.com/shorts'])

    def is_spotify_url(self, url: str) -> bool:
        return 'open.spotify.com/track/' in url.lower() or 'spotify:track:' in url.lower()

    def resolve_spotify(self, url: str):
        """Return (title, artist) from Spotify oEmbed (no API key needed)"""
        try:
            clean_url = url.split('?')[0]
            oembed_url = f"https://open.spotify.com/oembed?url={clean_url}"
            r = requests.get(oembed_url, timeout=6)
            if r.status_code == 200:
                data = r.json()
                title = data.get('title', '')
                # oEmbed gives "Artist - Title" or just title sometimes
                if ' - ' in title:
                    artist, song = title.split(' - ', 1)
                else:
                    song = title
                    artist = data.get('author_name', 'Unknown')
                return song.strip(), artist.strip()
        except Exception as e:
            print("Spotify resolve error:", e)
        return None, None

    def _search_youtube(self, query: str):
        """Return best video id + title for a search query"""
        try:
            import yt_dlp
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'playlist_items': '1',   # only first result
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
                if info and 'entries' in info and info['entries']:
                    entry = info['entries'][0]
                    return entry.get('id'), entry.get('title', query)
        except Exception as e:
            print("YouTube search error:", e)
        return None, None

    def download_audio(self, url: str, on_progress=None, on_status=None):
        """
        Main entry point.
        url can be YouTube or Spotify.
        Returns (local_path, title, artist, duration_seconds) or (None, None, None, 0)
        """
        import yt_dlp

        original_url = url
        title, artist = None, None
        video_id = None

        if self.is_spotify_url(url):
            if on_status:
                on_status("Menyelesaikan link Spotify...")
            song, art = self.resolve_spotify(url)
            if song and art:
                title, artist = song, art
                if on_status:
                    on_status(f"Mencari di YouTube: {artist} - {title}")
                video_id, yt_title = self._search_youtube(f"{artist} {title} official audio")
                if not video_id:
                    video_id, _ = self._search_youtube(f"{artist} {title}")
                url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None
            else:
                return None, None, None, 0

        if not url:
            return None, None, None, 0

        if self.is_youtube_url(url) and not video_id:
            # extract id from url for cache check
            match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
            if match:
                video_id = match.group(1)

        # Check cache first
        if video_id:
            cached = self._find_cached(video_id)
            if cached:
                if on_status:
                    on_status("Menggunakan cache...")
                meta = self._read_cached_meta(video_id)
                return cached, meta.get('title', 'Unknown'), meta.get('artist', 'Unknown'), meta.get('duration', 0)

        if on_status:
            on_status("Mengunduh audio dari YouTube...")

        # Prepare yt-dlp options with progress hook
        def progress_hook(d):
            if on_progress and d.get('status') == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                pct = int((downloaded / total) * 100) if total > 0 else 0
                speed = d.get('speed', 0)
                on_progress(pct, speed)

        ydl_opts = self.ydl_opts_base.copy()
        ydl_opts['progress_hooks'] = [progress_hook]
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
        ydl_opts['outtmpl'] = str(CACHE_DIR / '%(id)s.%(ext)s')

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if 'entries' in info:
                    info = info['entries'][0]

                video_id = info.get('id')
                final_path = CACHE_DIR / f"{video_id}.mp3"

                # Get nice metadata
                if not title:
                    title = info.get('title', 'Unknown YouTube Track')
                if not artist:
                    artist = info.get('uploader', info.get('channel', 'YouTube'))

                duration = info.get('duration', 0)

                # Save sidecar metadata
                self._save_cached_meta(video_id, {
                    'title': title,
                    'artist': artist,
                    'duration': duration,
                    'original_url': original_url,
                    'youtube_id': video_id,
                })

                return str(final_path), title, artist, duration

        except Exception as e:
            print("yt-dlp download failed:", e)
            if on_status:
                on_status(f"Gagal download: {e}")
            return None, None, None, 0

    def _find_cached(self, video_id: str):
        mp3 = CACHE_DIR / f"{video_id}.mp3"
        if mp3.exists():
            return str(mp3)
        # also check other possible extensions before postprocess
        for ext in ['.m4a', '.webm', '.opus']:
            p = CACHE_DIR / f"{video_id}{ext}"
            if p.exists():
                return str(p)
        return None

    def _save_cached_meta(self, video_id, meta):
        meta_file = CACHE_DIR / f"{video_id}.json"
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    def _read_cached_meta(self, video_id):
        meta_file = CACHE_DIR / f"{video_id}.json"
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    # ---------- Search ----------
    def search_youtube(self, query: str, limit: int = 10):
        """Search YouTube. Returns list of dicts: {id, title, channel, duration, url}"""
        import yt_dlp
        results = []
        try:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'playlist_items': f'1:{limit}',
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                for entry in info.get('entries', []):
                    if not entry:
                        continue
                    vid = entry.get('id')
                    results.append({
                        'id': vid,
                        'title': entry.get('title', 'Unknown'),
                        'channel': entry.get('uploader') or entry.get('channel', 'Unknown'),
                        'duration': entry.get('duration', 0),
                        'url': f"https://www.youtube.com/watch?v={vid}",
                        'source': 'youtube'
                    })
        except Exception as e:
            print("YouTube search error:", e)
        return results

    # ---------- Spotify Search (requires client credentials) ----------
    def get_spotify_token(self, client_id: str, client_secret: str):
        """Get Spotify access token using Client Credentials flow"""
        try:
            import base64
            auth_str = f"{client_id}:{client_secret}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            headers = {
                "Authorization": f"Basic {b64_auth}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            data = {"grant_type": "client_credentials"}
            r = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data, timeout=8)
            if r.status_code == 200:
                return r.json().get("access_token")
        except Exception as e:
            print("Spotify token error:", e)
        return None

    def search_spotify(self, query: str, client_id: str, client_secret: str, limit: int = 10):
        """Search Spotify tracks. Returns list of dicts"""
        token = self.get_spotify_token(client_id, client_secret)
        if not token:
            return []

        try:
            headers = {"Authorization": f"Bearer {token}"}
            params = {
                "q": query,
                "type": "track",
                "limit": limit
            }
            r = requests.get("https://api.spotify.com/v1/search", headers=headers, params=params, timeout=8)
            if r.status_code != 200:
                return []

            items = r.json().get("tracks", {}).get("items", [])
            results = []
            for track in items:
                artists = ", ".join(a["name"] for a in track.get("artists", []))
                results.append({
                    'id': track.get('id'),
                    'title': track.get('name'),
                    'artist': artists,
                    'album': track.get('album', {}).get('name', ''),
                    'duration': track.get('duration_ms', 0) / 1000,
                    'url': track.get('external_urls', {}).get('spotify'),
                    'source': 'spotify'
                })
            return results
        except Exception as e:
            print("Spotify search error:", e)
            return []


# ==================== LYRICS PROVIDERS (LRCLIB + Musixmatch) ====================
class LyricsProvider:
    """Unified lyrics fetcher supporting multiple sources"""

    def __init__(self, musixmatch_key=None):
        self.musixmatch_key = musixmatch_key

    def fetch(self, title, artist, duration=0):
        """
        Try multiple sources. Returns (lyrics_text, source_name)
        Prioritizes synced lyrics when possible.
        """
        # 1. Try LRCLIB first (best for synced LRC)
        try:
            lyrics = self._fetch_lrclib(title, artist, duration)
            if lyrics:
                return lyrics, "LRCLIB (synced)"
        except Exception as e:
            print("LRCLIB error:", e)

        # 2. Try Musixmatch (if key available)
        if self.musixmatch_key:
            try:
                lyrics = self._fetch_musixmatch(title, artist)
                if lyrics:
                    return lyrics, "Musixmatch"
            except Exception as e:
                print("Musixmatch error:", e)

        return None, None

    def _fetch_lrclib(self, title, artist, duration):
        params = {"track_name": title, "artist_name": artist}
        if duration > 10:
            params["duration"] = int(duration)
        r = requests.get("https://lrclib.net/api/get", params=params, timeout=8)
        if r.status_code == 200:
            data = r.json()
            return data.get("syncedLyrics") or data.get("plainLyrics")
        return None

    def _fetch_musixmatch(self, title, artist):
        if not self.musixmatch_key:
            return None
        url = "https://api.musixmatch.com/ws/1.1/matcher.lyrics.get"
        params = {
            "q_track": title,
            "q_artist": artist,
            "apikey": self.musixmatch_key,
        }
        r = requests.get(url, params=params, timeout=8)
        if r.status_code == 200:
            data = r.json()
            body = data.get("message", {}).get("body", {})
            lyrics = body.get("lyrics", {}).get("lyrics_body", "")
            if lyrics:
                # Musixmatch free often appends "..." at the end
                if lyrics.endswith("..."):
                    lyrics += "\n\n[Lirik sebagian - Musixmatch]"
                return lyrics
        return None


# ==================== MAIN APPLICATION ====================
class LirikBarApp:
    def __init__(self, root):
        # Lazy import GUI deps so the module can be imported without tkinter (useful for tests)
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        # store on self for use in all methods (lazy import trick)
        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("980x620")
        self.root.minsize(820, 520)
        self.root.configure(bg=BG_DARK)
        
        # State
        self.playlist = []  # list of dicts
        self.current_idx = -1
        self.lyrics = []    # [(ms, text), ...]
        self.player = AudioPlayer()
        self.config = self._load_config()
        
        self.youtube = YouTubeProvider()
        self.lyrics_provider = LyricsProvider(
            musixmatch_key=self.config.get("musixmatch_key")
        )
        
        self.bar_win = None
        self.bar_label = None
        self.tray_icon = None
        self._drag_data = {"x": 0, "y": 0}
        self._last_ui_update = 0
        
        self._setup_styles()
        self._build_ui()
        self._bind_keys()
        
        # Timer UI
        self._schedule_ui_update()
        
        # Auto load last playlist if exists
        self._restore_session()
        
        # Tray
        self._setup_tray()
        
        # Cleanup on close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    # ---------- Config & Session ----------
    def _load_config(self):
        default = {
            "volume": 0.7,
            "bar_opacity": 0.92,
            "bar_font_size": 18,
            "last_playlist": [],
            "last_index": -1,
            "last_pos": 0,
            "window_geometry": "980x620",
            "musixmatch_key": None,
            "spotify_client_id": None,
            "spotify_client_secret": None,
        }
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    default.update(data)
        except Exception:
            pass
        return default
    
    def _save_config(self):
        try:
            self.config["volume"] = self.player.get_volume()
            self.config["window_geometry"] = self.root.geometry()
            if self.current_idx >= 0:
                self.config["last_index"] = self.current_idx
                self.config["last_pos"] = self.player.get_pos_ms()
            
            # Persist playlist (support both local files + YouTube cached files)
            self.config["last_playlist"] = []
            for p in self.playlist:
                entry = p["path"]
                self.config["last_playlist"].append(entry)
            
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print("Save config error:", e)
    
    def _restore_session(self):
        try:
            last_list = self.config.get("last_playlist", [])
            for p in last_list:
                if Path(p).exists():
                    self._add_to_playlist(p, silent=True)
            
            if self.playlist and self.config.get("last_index", -1) >= 0:
                idx = min(self.config["last_index"], len(self.playlist)-1)
                self._play_index(idx, start_ms=self.config.get("last_pos", 0))
        except Exception:
            pass
    
    # ---------- Styles ----------
    def _setup_styles(self):
        style = self.ttk.Style()
        style.theme_use("clam")
        
        style.configure("TFrame", background=BG_DARK)
        style.configure("Card.TFrame", background=BG_CARD)
        
        style.configure("TLabel", background=BG_DARK, foreground=TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 13, "bold"), foreground=TEXT_PRIMARY)
        style.configure("Muted.TLabel", foreground=TEXT_MUTED)
        
        style.configure("TButton", background=BG_CARD, foreground=TEXT_PRIMARY, 
                        borderwidth=0, padding=8, font=("Segoe UI", 10))
        style.map("TButton", background=[("active", "#23233a")])
        
        style.configure("Accent.TButton", background=ACCENT, foreground="white")
        style.map("Accent.TButton", background=[("active", "#ff6ba6")])
        
        style.configure("TScale", background=BG_DARK, troughcolor="#22223a")
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#22223a")
        
        style.configure("Treeview", background=BG_CARD, foreground=TEXT_PRIMARY,
                        fieldbackground=BG_CARD, borderwidth=0, rowheight=28)
        style.configure("Treeview.Heading", background=BG_DARK, foreground=TEXT_SECONDARY)
        style.map("Treeview", background=[("selected", ACCENT2)])
    
    # ---------- UI BUILD ----------
    def _build_ui(self):
        # Top bar
        top = self.tk.Frame(self.root, bg=BG_DARK, height=52)
        top.pack(fill="x", padx=12, pady=(8, 4))
        top.pack_propagate(False)
        
        self.tk.Label(top, text="♪ LirikBar", bg=BG_DARK, fg=ACCENT, 
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=6)
        
        self.tk.Label(top, text="Musik + Lirik di Taskbar", bg=BG_DARK, fg=TEXT_MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=10)
        
        # Controls right
        ctrl = self.tk.Frame(top, bg=BG_DARK)
        ctrl.pack(side="right")
        
        self.ttk.Button(ctrl, text="📂 Tambah File", command=self._add_files).pack(side="left", padx=4)
        self.ttk.Button(ctrl, text="📁 Tambah Folder", command=self._add_folder).pack(side="left", padx=4)
        self.ttk.Button(ctrl, text="🔍 Search", command=self._open_search_dialog).pack(side="left", padx=4)
        self.ttk.Button(ctrl, text="🌐 Add URL", command=self._add_from_url).pack(side="left", padx=4)
        self.ttk.Button(ctrl, text="🪟 Lyrics Bar", command=self._toggle_lyrics_bar).pack(side="left", padx=4)
        self.ttk.Button(ctrl, text="🔄 Fetch Lirik", command=self._fetch_lyrics_online).pack(side="left", padx=4)
        self.ttk.Button(ctrl, text="⚙ Settings", command=self._open_settings).pack(side="left", padx=4)
        
        # Main split
        main = self.tk.PanedWindow(self.root, orient="horizontal", bg=BG_DARK, sashwidth=4, sashrelief="flat")
        main.pack(fill="both", expand=True, padx=10, pady=6)
        
        # LEFT: Playlist
        left_frame = self.ttk.Frame(main, style="Card.TFrame", padding=8)
        main.add(left_frame, width=340)
        
        self.tk.Label(left_frame, text="PLAYLIST", bg=BG_CARD, fg=TEXT_SECONDARY, 
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0,6))
        
        self.playlist_tree = self.ttk.Treeview(left_frame, columns=("title", "artist", "dur"), 
                                          show="tree headings", selectmode="browse")
        self.playlist_tree.heading("#0", text="#")
        self.playlist_tree.heading("title", text="Judul")
        self.playlist_tree.heading("artist", text="Artist")
        self.playlist_tree.heading("dur", text="Durasi")
        
        self.playlist_tree.column("#0", width=28, stretch=False)
        self.playlist_tree.column("title", width=160)
        self.playlist_tree.column("artist", width=90)
        self.playlist_tree.column("dur", width=52, stretch=False)
        
        self.playlist_tree.pack(fill="both", expand=True)
        self.playlist_tree.bind("<<TreeviewSelect>>", self._on_playlist_select)
        self.playlist_tree.bind("<Double-1>", self._on_playlist_double)
        
        # RIGHT: Player + Lyrics
        right = self.ttk.Frame(main, style="Card.TFrame", padding=14)
        main.add(right, width=620)
        
        # Now playing
        self.title_label = self.tk.Label(right, text="Tidak ada lagu", bg=BG_CARD, 
                                    fg=TEXT_PRIMARY, font=("Segoe UI", 15, "bold"))
        self.title_label.pack(anchor="w")
        
        self.artist_label = self.tk.Label(right, text="", bg=BG_CARD, fg=TEXT_SECONDARY, font=("Segoe UI", 10))
        self.artist_label.pack(anchor="w", pady=(0, 8))
        
        # Progress
        prog_frame = self.tk.Frame(right, bg=BG_CARD)
        prog_frame.pack(fill="x", pady=4)
        
        self.time_label = self.tk.Label(prog_frame, text="00:00 / 00:00", bg=BG_CARD, fg=TEXT_MUTED, width=16)
        self.time_label.pack(side="left")
        
        self.progress = self.ttk.Scale(prog_frame, from_=0, to=1000, orient="horizontal",
                                  command=self._on_seek)
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        
        self.progress.bind("<ButtonRelease-1>", self._on_seek_release)
        
        # Controls
        btns = self.tk.Frame(right, bg=BG_CARD)
        btns.pack(pady=8)
        
        self.btn_prev = self.ttk.Button(btns, text="⏮", width=4, command=self.prev_track)
        self.btn_prev.pack(side="left", padx=3)
        
        self.btn_play = self.ttk.Button(btns, text="▶", width=5, command=self.toggle_play, style="Accent.TButton")
        self.btn_play.pack(side="left", padx=3)
        
        self.btn_next = self.ttk.Button(btns, text="⏭", width=4, command=self.next_track)
        self.btn_next.pack(side="left", padx=3)
        
        # Volume
        self.tk.Label(btns, text="  🔊", bg=BG_CARD, fg=TEXT_SECONDARY).pack(side="left")
        self.vol_scale = self.ttk.Scale(btns, from_=0, to=100, orient="horizontal", length=100,
                                   command=self._on_volume)
        self.vol_scale.set(int(self.config.get("volume", 0.7) * 100))
        self.vol_scale.pack(side="left", padx=4)
        
        # Lyrics area (full view)
        self.tk.Label(right, text="LIRIK", bg=BG_CARD, fg=TEXT_SECONDARY, 
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 4))
        
        lyrics_frame = self.tk.Frame(right, bg="#12121f", bd=1, relief="sunken")
        lyrics_frame.pack(fill="both", expand=True)
        
        self.lyrics_text = self.tk.Text(lyrics_frame, bg="#12121f", fg=TEXT_PRIMARY,
                                   font=("Segoe UI", 11), wrap="word", padx=12, pady=10,
                                   state="disabled", cursor="arrow")
        self.lyrics_text.pack(fill="both", expand=True, side="left")
        
        scroll = self.ttk.Scrollbar(lyrics_frame, command=self.lyrics_text.yview)
        scroll.pack(side="right", fill="y")
        self.lyrics_text.config(yscrollcommand=scroll.set)
        
        # Status bar
        self.status = self.tk.Label(self.root, text="Siap. Tambah musik untuk mulai.", 
                               bg=BG_DARK, fg=TEXT_MUTED, anchor="w", padx=12)
        self.status.pack(fill="x", side="bottom", pady=2)
    
    def _bind_keys(self):
        self.root.bind("<space>", lambda e: self.toggle_play())
        self.root.bind("<Left>", lambda e: self.seek_relative(-5000))
        self.root.bind("<Right>", lambda e: self.seek_relative(5000))
        self.root.bind("<Up>", lambda e: self._change_volume(0.05))
        self.root.bind("<Down>", lambda e: self._change_volume(-0.05))
        self.root.bind("<Control-n>", lambda e: self.next_track())
        self.root.bind("<Control-p>", lambda e: self.prev_track())
        self.root.bind("<Escape>", lambda e: self._hide_lyrics_bar())
        self.root.bind("<F11>", lambda e: self._toggle_lyrics_bar())
    
    # ---------- Playlist ----------
    def _add_files(self):
        files = self.filedialog.askopenfilenames(
            title="Pilih file musik",
            filetypes=[("Audio", "*.mp3 *.flac *.ogg *.wav *.m4a *.wma"), ("All", "*.*")]
        )
        for f in files:
            self._add_to_playlist(f)
    
    def _add_folder(self):
        folder = self.filedialog.askdirectory(title="Pilih folder musik")
        if not folder:
            return
        exts = {".mp3", ".flac", ".ogg", ".wav", ".m4a"}
        added = 0
        for root, _, files in os.walk(folder):
            for name in sorted(files):
                if Path(name).suffix.lower() in exts:
                    self._add_to_playlist(os.path.join(root, name), silent=True)
                    added += 1
        self.status.config(text=f"Menambahkan {added} lagu dari folder")

    # ---------- YouTube / Spotify URL Support ----------
    def _add_from_url(self):
        """Open dialog to add from YouTube or Spotify link"""
        dialog = self.tk.Toplevel(self.root)
        dialog.title("Tambah dari YouTube / Spotify")
        dialog.geometry("520x160")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=BG_CARD)

        self.tk.Label(dialog, text="Paste YouTube atau Spotify link:", bg=BG_CARD, fg=TEXT_PRIMARY,
                      font=("Segoe UI", 11)).pack(pady=(12, 4))

        url_var = self.tk.StringVar()
        entry = self.tk.Entry(dialog, textvariable=url_var, width=60, font=("Segoe UI", 10))
        entry.pack(padx=16, pady=4)
        entry.focus_set()

        status_label = self.tk.Label(dialog, text="", bg=BG_CARD, fg=ACCENT, font=("Segoe UI", 9))
        status_label.pack(pady=2)

        def start_download():
            url = url_var.get().strip()
            if not url:
                return
            dialog.destroy()
            self._download_and_add_url(url)

        btn_frame = self.tk.Frame(dialog, bg=BG_CARD)
        btn_frame.pack(pady=10)
        self.ttk.Button(btn_frame, text="Download & Tambah", command=start_download, style="Accent.TButton").pack(side="left", padx=6)
        self.ttk.Button(btn_frame, text="Batal", command=dialog.destroy).pack(side="left", padx=6)

        # Allow Enter key
        dialog.bind("<Return>", lambda e: start_download())

    def _download_and_add_url(self, url):
        """Run yt-dlp download in background thread + show progress"""
        progress_win = self.tk.Toplevel(self.root)
        progress_win.title("Mengunduh...")
        progress_win.geometry("420x110")
        progress_win.transient(self.root)
        progress_win.grab_set()
        progress_win.configure(bg=BG_CARD)

        self.tk.Label(progress_win, text="Sedang mengunduh audio...", bg=BG_CARD, fg=TEXT_PRIMARY,
                      font=("Segoe UI", 11, "bold")).pack(pady=(10, 4))

        status_var = self.tk.StringVar(value="Menghubungkan...")
        status_label = self.tk.Label(progress_win, textvariable=status_var, bg=BG_CARD, fg=TEXT_SECONDARY)
        status_label.pack()

        pb = self.ttk.Progressbar(progress_win, length=360, mode='determinate')
        pb.pack(pady=8, padx=16)

        def on_progress(pct, speed):
            pb["value"] = pct
            speed_str = f" ({speed/1024/1024:.1f} MB/s)" if speed else ""
            status_var.set(f"Mengunduh... {pct}%{speed_str}")

        def on_status(text):
            status_var.set(text)

        def worker():
            try:
                path, title, artist, duration = self.youtube.download_audio(
                    url,
                    on_progress=on_progress,
                    on_status=on_status
                )
                if path:
                    self.root.after(0, lambda: self._finish_add_youtube(path, title, artist, duration, url))
                else:
                    self.root.after(0, lambda: self.messagebox.showerror("Gagal", "Gagal mengunduh audio dari link tersebut."))
            except Exception as e:
                self.root.after(0, lambda: self.messagebox.showerror("Error", str(e)))
            finally:
                self.root.after(0, progress_win.destroy)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_add_youtube(self, path, title, artist, duration, original_url):
        """Add downloaded YouTube track to playlist with proper metadata"""
        if any(p.get("path") == path for p in self.playlist):
            self.status.config(text="Sudah ada di playlist")
            return

        item = {
            "path": path,
            "title": title or Path(path).stem,
            "artist": artist or "YouTube",
            "album": "YouTube / Streaming",
            "duration": duration or 0,
            "lrc_path": None,
            "source": "youtube",
            "original_url": original_url,
        }

        self.playlist.append(item)
        idx = len(self.playlist) - 1

        dur_str = self._fmt_time(item["duration"])
        self.playlist_tree.insert("", "end", iid=str(idx),
                                  text=str(idx + 1),
                                  values=(item["title"][:42], item["artist"][:26], dur_str + " [YT]"))

        self.status.config(text=f"✓ Added from YouTube: {title}")
        # Immediately play it
        self._play_index(idx)

    # ---------- Unified Search Dialog (YouTube + Spotify) ----------
    def _open_search_dialog(self):
        win = self.tk.Toplevel(self.root)
        win.title("Search YouTube / Spotify")
        win.geometry("780x520")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=BG_CARD)

        # Top controls
        top = self.tk.Frame(win, bg=BG_CARD)
        top.pack(fill="x", padx=12, pady=10)

        self.tk.Label(top, text="Search in:", bg=BG_CARD, fg=TEXT_SECONDARY).pack(side="left")

        search_mode = self.tk.StringVar(value="youtube")
        self.tk.Radiobutton(top, text="YouTube", variable=search_mode, value="youtube",
                            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK).pack(side="left", padx=8)
        self.tk.Radiobutton(top, text="Spotify", variable=search_mode, value="spotify",
                            bg=BG_CARD, fg=TEXT_PRIMARY, selectcolor=BG_DARK).pack(side="left", padx=4)

        query_var = self.tk.StringVar()
        entry = self.tk.Entry(top, textvariable=query_var, width=45, font=("Segoe UI", 11))
        entry.pack(side="left", padx=12)
        entry.focus_set()

        search_btn = self.ttk.Button(top, text="🔍 Search")
        search_btn.pack(side="left", padx=4)

        # Results
        self.tk.Label(win, text="Results (double-click or select then Add)", bg=BG_CARD, fg=TEXT_MUTED).pack(anchor="w", padx=12)

        columns = ("title", "artist", "duration", "source")
        results_tree = self.ttk.Treeview(win, columns=columns, show="headings", height=16)
        results_tree.heading("title", text="Title")
        results_tree.heading("artist", text="Artist / Channel")
        results_tree.heading("duration", text="Duration")
        results_tree.heading("source", text="Source")

        results_tree.column("title", width=320)
        results_tree.column("artist", width=200)
        results_tree.column("duration", width=90)
        results_tree.column("source", width=80)

        results_tree.pack(fill="both", expand=True, padx=12, pady=6)

        # Store search results in memory
        search_results = []

        def do_search():
            q = query_var.get().strip()
            if not q:
                return
            results_tree.delete(*results_tree.get_children())
            search_results.clear()

            mode = search_mode.get()

            if mode == "youtube":
                self.status.config(text="Searching YouTube...")
                win.update_idletasks()
                res = self.youtube.search_youtube(q, limit=12)
            else:
                cid = self.config.get("spotify_client_id")
                csecret = self.config.get("spotify_client_secret")
                if not cid or not csecret:
                    self.messagebox.showwarning("Spotify", "Masukkan Spotify Client ID & Secret dulu di ⚙ Settings")
                    return
                self.status.config(text="Searching Spotify...")
                win.update_idletasks()
                res = self.youtube.search_spotify(q, cid, csecret, limit=12)

            for item in res:
                dur = self._fmt_time(item.get("duration", 0))
                iid = results_tree.insert("", "end", values=(
                    item.get("title", "")[:60],
                    item.get("artist") or item.get("channel", "")[:35],
                    dur,
                    item.get("source", "").upper()
                ))
                search_results.append((iid, item))

            self.status.config(text=f"Found {len(res)} results")

        search_btn.config(command=do_search)
        entry.bind("<Return>", lambda e: do_search())

        def add_selected():
            sel = results_tree.selection()
            if not sel:
                return
            for item in sel:
                for iid, data in search_results:
                    if iid == item:
                        if data["source"] == "youtube":
                            # Download
                            win.destroy()
                            self._download_and_add_url(data["url"])
                        else:
                            # Spotify → resolve via YouTube search internally
                            win.destroy()
                            query = f"{data.get('artist', '')} {data.get('title', '')}"
                            self.status.config(text=f"Searching YouTube for Spotify result: {query}")
                            yt_results = self.youtube.search_youtube(query, limit=1)
                            if yt_results:
                                self._download_and_add_url(yt_results[0]["url"])
                            else:
                                self.messagebox.showerror("Error", "Gagal menemukan audio di YouTube untuk lagu Spotify ini.")
                        return

        def on_double_click(event):
            add_selected()

        results_tree.bind("<Double-1>", on_double_click)

        # Bottom buttons
        bottom = self.tk.Frame(win, bg=BG_CARD)
        bottom.pack(fill="x", pady=8)

        self.ttk.Button(bottom, text="Add Selected", command=add_selected, style="Accent.TButton").pack(side="left", padx=12)
        self.ttk.Button(bottom, text="Close", command=win.destroy).pack(side="left", padx=6)

    def _add_to_playlist(self, path, silent=False, **overrides):
        """Add local file. YouTube items are added via special _finish_add_youtube path."""
        path = str(Path(path).resolve())
        if any(p["path"] == path for p in self.playlist):
            return
        
        meta = self._read_metadata(path)
        item = {
            "path": path,
            "title": overrides.get("title") or meta.get("title", Path(path).stem),
            "artist": overrides.get("artist") or meta.get("artist", "Unknown"),
            "album": overrides.get("album") or meta.get("album", ""),
            "duration": overrides.get("duration") or meta.get("duration", 0),
            "lrc_path": self._find_lrc(path),
            **{k: v for k, v in overrides.items() if k not in ("title", "artist", "album", "duration")}
        }
        
        self.playlist.append(item)
        idx = len(self.playlist) - 1
        
        dur_str = self._fmt_time(item["duration"])
        self.playlist_tree.insert("", "end", iid=str(idx), 
                                  text=str(idx+1),
                                  values=(item["title"][:45], item["artist"][:28], dur_str))
        
        if not silent:
            self.status.config(text=f"Added: {item['title']}")
    
    def _read_metadata(self, path):
        try:
            audio = MutagenFile(path, easy=True)
            if audio is None:
                return {}
            dur = audio.info.length if audio.info else 0
            return {
                "title": audio.get("title", [Path(path).stem])[0],
                "artist": audio.get("artist", ["Unknown"])[0],
                "album": audio.get("album", [""])[0],
                "duration": dur
            }
        except Exception:
            return {"title": Path(path).stem, "artist": "Unknown", "duration": 0}
    
    def _find_lrc(self, audio_path):
        p = Path(audio_path)
        candidates = [
            p.with_suffix(".lrc"),
            p.parent / f"{p.stem}.lrc",
            p.parent / f"{p.stem.lower()}.lrc",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return None
    
    def _on_playlist_select(self, event=None):
        sel = self.playlist_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx != self.current_idx:
            self._play_index(idx)
    
    def _on_playlist_double(self, event=None):
        self._on_playlist_select()
    
    # ---------- Playback ----------
    def _play_index(self, idx, start_ms=0):
        if idx < 0 or idx >= len(self.playlist):
            return
        
        self.current_idx = idx
        item = self.playlist[idx]
        
        # Highlight in tree
        self.playlist_tree.selection_set(str(idx))
        self.playlist_tree.see(str(idx))
        
        # Load metadata + lyrics
        self.title_label.config(text=item["title"])
        self.artist_label.config(text=item["artist"])
        
        self.lyrics = []
        lrc_path = item.get("lrc_path")
        if lrc_path and Path(lrc_path).exists():
            try:
                with open(lrc_path, "r", encoding="utf-8", errors="ignore") as f:
                    self.lyrics = LRCParser.parse(f.read())
            except Exception as e:
                print("LRC parse error:", e)
        
        self._update_full_lyrics_view()
        
        # Load & play audio
        ok = self.player.load(item["path"], duration_hint=item["duration"])
        if ok:
            self.player.play(start_ms)
            self.btn_play.config(text="⏸")
            self.status.config(text=f"Now playing: {item['title']}")
        else:
            self.messagebox.showerror("Error", f"Gagal memuat: {item['path']}")
    
    def toggle_play(self):
        if self.current_idx < 0 and self.playlist:
            self._play_index(0)
            return
        
        self.player.toggle()
        self.btn_play.config(text="⏸" if self.player.is_playing() else "▶")
    
    def next_track(self):
        if not self.playlist:
            return
        nxt = (self.current_idx + 1) % len(self.playlist)
        self._play_index(nxt)
    
    def prev_track(self):
        if not self.playlist:
            return
        prev = (self.current_idx - 1) % len(self.playlist)
        self._play_index(prev)
    
    def seek_relative(self, delta_ms):
        if self.current_idx < 0:
            return
        new_pos = self.player.get_pos_ms() + delta_ms
        self.player.seek(new_pos)
    
    def _on_seek(self, val):
        # live preview only, actual seek on release
        pass
    
    def _on_seek_release(self, event):
        if self.current_idx < 0:
            return
        val = float(self.progress.get())
        item = self.playlist[self.current_idx]
        target = int((val / 1000.0) * (item["duration"] * 1000))
        self.player.seek(target)
    
    def _on_volume(self, val):
        self.player.set_volume(float(val) / 100.0)
    
    def _change_volume(self, delta):
        newv = max(0, min(1, self.player.get_volume() + delta))
        self.player.set_volume(newv)
        self.vol_scale.set(int(newv * 100))
    
    # ---------- Lyrics UI ----------
    def _update_full_lyrics_view(self):
        self.lyrics_text.config(state="normal")
        self.lyrics_text.delete("1.0", "end")
        
        if not self.lyrics:
            self.lyrics_text.insert("1.0", "Tidak ada lirik tersedia.\n\n• Letakkan file .lrc dengan nama sama di folder lagu\n• Atau klik tombol 'Fetch Lirik' untuk unduh otomatis")
            self.lyrics_text.config(fg=TEXT_MUTED)
        else:
            text = LRCParser.get_full_text(self.lyrics)
            self.lyrics_text.insert("1.0", text)
            self.lyrics_text.config(fg=TEXT_PRIMARY)
        
        self.lyrics_text.config(state="disabled")
    
    def _highlight_current_lyric(self, pos_ms):
        """Highlight baris lirik yang sedang diputar di view full"""
        if not self.lyrics:
            return
        
        # Cari index saat ini
        idx = 0
        for i, (t, _) in enumerate(self.lyrics):
            if t <= pos_ms:
                idx = i
            else:
                break
        
        # Scroll ke baris tersebut (kasar)
        try:
            line_num = idx + 1
            self.lyrics_text.see(f"{line_num}.0")
            # Simple highlight (reset dulu)
            self.lyrics_text.tag_remove("current", "1.0", "end")
            self.lyrics_text.tag_add("current", f"{line_num}.0", f"{line_num}.end+1c")
            self.lyrics_text.tag_config("current", background="#2a1f3a", foreground=ACCENT)
        except Exception:
            pass
    
    # ---------- Floating Lyrics Bar (THE FEATURE) ----------
    def _toggle_lyrics_bar(self):
        if self.bar_win and self.bar_win.winfo_exists():
            self._hide_lyrics_bar()
        else:
            self._show_lyrics_bar()
    
    def _show_lyrics_bar(self):
        if self.bar_win and self.bar_win.winfo_exists():
            self.bar_win.lift()
            return
        
        self.bar_win = self.tk.Toplevel(self.root)
        self.bar_win.overrideredirect(True)
        self.bar_win.attributes("-topmost", True)
        self.bar_win.attributes("-alpha", self.config.get("bar_opacity", 0.92))
        self.bar_win.configure(bg=BG_DARK)
        
        # Initial position: bottom center
        sw = self.bar_win.winfo_screenwidth()
        sh = self.bar_win.winfo_screenheight()
        w = min(720, int(sw * 0.65))
        x = (sw - w) // 2
        y = sh - 82   # above taskbar roughly
        self.bar_win.geometry(f"{w}x58+{x}+{y}")
        
        # Content
        container = self.tk.Frame(self.bar_win, bg=BG_DARK, bd=0)
        container.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Subtle border effect
        border = self.tk.Frame(container, bg=ACCENT, height=2)
        border.pack(fill="x", side="top")
        
        # Main lyric line
        self.bar_label = self.tk.Label(
            container,
            text="♪ Putar lagu untuk melihat lirik di sini",
            bg=BG_DARK,
            fg=TEXT_PRIMARY,
            font=("Segoe UI", self.config.get("bar_font_size", 18), "bold"),
            anchor="center",
            justify="center"
        )
        self.bar_label.pack(fill="both", expand=True, pady=(4, 2))
        
        # Tiny controls (appear on hover-ish)
        mini = self.tk.Frame(container, bg=BG_DARK)
        mini.pack(side="bottom", pady=(0, 3))
        
        self.tk.Button(mini, text="⏮", bg=BG_DARK, fg=TEXT_SECONDARY, bd=0, font=("Segoe UI", 9),
                  command=self.prev_track, activebackground=BG_CARD).pack(side="left", padx=6)
        self.tk.Button(mini, text="⏯", bg=BG_DARK, fg=ACCENT, bd=0, font=("Segoe UI", 9),
                  command=self.toggle_play, activebackground=BG_CARD).pack(side="left", padx=6)
        self.tk.Button(mini, text="⏭", bg=BG_DARK, fg=TEXT_SECONDARY, bd=0, font=("Segoe UI", 9),
                  command=self.next_track, activebackground=BG_CARD).pack(side="left", padx=6)
        
        # Drag support
        for w in (self.bar_win, container, self.bar_label, border, mini):
            w.bind("<ButtonPress-1>", self._bar_start_drag)
            w.bind("<B1-Motion>", self._bar_on_drag)
            w.bind("<Double-Button-1>", lambda e: self._open_main_from_bar())
        
        # Right click menu
        self.bar_win.bind("<Button-3>", self._bar_context_menu)
        self.bar_label.bind("<Button-3>", self._bar_context_menu)
        
        # Auto update hint
        self._update_bar_lyric(0)
    
    def _hide_lyrics_bar(self):
        if self.bar_win:
            try:
                self.bar_win.destroy()
            except:
                pass
        self.bar_win = None
        self.bar_label = None
    
    def _bar_start_drag(self, event):
        self._drag_data["x"] = event.x_root - self.bar_win.winfo_x()
        self._drag_data["y"] = event.y_root - self.bar_win.winfo_y()
    
    def _bar_on_drag(self, event):
        if not self.bar_win:
            return
        new_x = event.x_root - self._drag_data["x"]
        new_y = event.y_root - self._drag_data["y"]
        self.bar_win.geometry(f"+{new_x}+{new_y}")
    
    def _bar_context_menu(self, event):
        menu = self.tk.Menu(self.bar_win, tearoff=0, bg=BG_CARD, fg=TEXT_PRIMARY)
        menu.add_command(label="▶ Play / Pause", command=self.toggle_play)
        menu.add_command(label="⏭ Next", command=self.next_track)
        menu.add_command(label="⏮ Previous", command=self.prev_track)
        menu.add_separator()
        menu.add_command(label="Buka Player Utama", command=self._open_main_from_bar)
        menu.add_command(label="Tutup Lyrics Bar", command=self._hide_lyrics_bar)
        menu.add_separator()
        menu.add_command(label="Kecilkan Font", command=lambda: self._resize_bar_font(-1))
        menu.add_command(label="Besarkan Font", command=lambda: self._resize_bar_font(1))
        menu.tk_popup(event.x_root, event.y_root)
    
    def _open_main_from_bar(self):
        self.root.deiconify()
        self.root.lift()
    
    def _resize_bar_font(self, delta):
        if not self.bar_label:
            return
        curr = self.config.get("bar_font_size", 18)
        new_size = max(12, min(32, curr + delta))
        self.config["bar_font_size"] = new_size
        self.bar_label.config(font=("Segoe UI", new_size, "bold"))
    
    def _update_bar_lyric(self, pos_ms):
        if not self.bar_win or not self.bar_label:
            return
        
        if self.current_idx < 0 or not self.lyrics:
            txt = "♪ " + (self.playlist[self.current_idx]["title"] if self.current_idx >= 0 else "Tidak ada lirik")
        else:
            _, curr, _ = LRCParser.get_current(self.lyrics, pos_ms)
            txt = curr
        
        # Truncate if too long for bar width
        if len(txt) > 75:
            txt = txt[:72] + "..."
        
        self.bar_label.config(text=txt)
    
    # ---------- Online Lyrics (now supports LRCLIB + Musixmatch) ----------
    def _fetch_lyrics_online(self):
        if self.current_idx < 0:
            self.messagebox.showinfo("Info", "Putar lagu dulu sebelum fetch lirik.")
            return
        
        item = self.playlist[self.current_idx]
        title = item["title"]
        artist = item["artist"]
        dur = int(item.get("duration", 0))
        
        self.status.config(text=f"Mencari lirik (LRCLIB + Musixmatch) untuk: {artist} - {title} ...")
        self.root.update_idletasks()
        
        try:
            lyrics_text, source = self.lyrics_provider.fetch(title, artist, dur)
            
            if lyrics_text:
                self.lyrics = LRCParser.parse(lyrics_text)
                
                # Save .lrc next to the audio file (works for both local and YouTube cache)
                lrc_path = Path(item["path"]).with_suffix(".lrc")
                with open(lrc_path, "w", encoding="utf-8") as f:
                    f.write(lyrics_text)
                
                item["lrc_path"] = str(lrc_path)
                
                self._update_full_lyrics_view()
                self.status.config(text=f"✓ Lirik berhasil diunduh dari {source}")
                return
            
            self.messagebox.showwarning("Tidak ditemukan", 
                f"Lirik tidak ditemukan di LRCLIB / Musixmatch untuk:\n{artist} - {title}\n\n"
                "Coba perbaiki judul/artist atau buat file .lrc manual.")
        except Exception as e:
            self.messagebox.showerror("Error", f"Gagal mengambil lirik:\n{e}")
        finally:
            self.status.config(text="Selesai.")
    
    # ---------- UI Update Loop ----------
    def _schedule_ui_update(self):
        self._update_ui_loop()
    
    def _update_ui_loop(self):
        try:
            pos = self.player.get_pos_ms()
            
            # Check track end
            if self.player.check_ended():
                self.next_track()
                self._schedule_next()
                return
            
            # Update progress
            if self.current_idx >= 0:
                item = self.playlist[self.current_idx]
                dur_ms = int(item["duration"] * 1000) or 1
                pct = min(1000, int((pos / dur_ms) * 1000))
                self.progress.config(to=1000)
                self.progress.set(pct)
                
                # time labels
                self.time_label.config(text=f"{self._fmt_time(pos/1000)} / {self._fmt_time(item['duration'])}")
                
                # lyrics highlight
                self._highlight_current_lyric(pos)
                
                # floating bar
                if self.bar_win and self.bar_win.winfo_exists():
                    self._update_bar_lyric(pos)
            
            # Button state
            is_play = self.player.is_playing()
            self.btn_play.config(text="⏸" if is_play else "▶")
            
        except Exception as ex:
            pass  # silent fail in loop
        
        self._schedule_next()
    
    def _schedule_next(self):
        self.root.after(140, self._update_ui_loop)
    
    # ---------- Tray ----------
    def _setup_tray(self):
        try:
            # Create simple icon
            img = Image.new("RGBA", (64, 64), (15, 15, 26, 255))
            draw = ImageDraw.Draw(img)
            draw.ellipse([8, 8, 56, 56], fill=(255, 77, 148))
            draw.text((18, 18), "♪", fill="white", font=ImageFont.load_default(size=28))
            
            menu = (
                item("Buka LirikBar", self._show_main),
                item("Tampilkan Lyrics Bar", self._toggle_lyrics_bar),
                pystray.Menu.SEPARATOR,
                item("Play/Pause", self.toggle_play),
                item("Next", self.next_track),
                item("Previous", self.prev_track),
                pystray.Menu.SEPARATOR,
                item("Keluar", self._quit_app),
            )
            
            self.tray_icon = pystray.Icon(APP_NAME, img, APP_NAME, menu)
            
            # Run tray in background thread
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print("Tray setup failed (normal on some Linux):", e)
    
    def _show_main(self, icon=None, item=None):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
    
    # ---------- Helpers ----------
    @staticmethod
    def _fmt_time(seconds):
        if not seconds or seconds < 0:
            return "00:00"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"
    
    def _on_close(self):
        self._save_config()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except:
                pass
        self.player.close()
        self.root.destroy()
    
    def _quit_app(self, icon=None, item=None):
        if self.tray_icon:
            self.tray_icon.stop()
        self._save_config()
        self.player.close()
        self.root.after(50, self.root.destroy)
    
    # ---------- Settings (Musixmatch key + cache) ----------
    def _open_settings(self):
        win = self.tk.Toplevel(self.root)
        win.title("LirikBar Settings")
        win.geometry("460x220")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=BG_CARD)

        # Musixmatch
        self.tk.Label(win, text="Musixmatch API Key (opsional)", bg=BG_CARD, fg=TEXT_PRIMARY,
                      font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(12, 2))

        mm_key_var = self.tk.StringVar(value=self.config.get("musixmatch_key") or "")
        mm_entry = self.tk.Entry(win, textvariable=mm_key_var, width=52, font=("Consolas", 9))
        mm_entry.pack(padx=16, pady=2)
        self.tk.Label(win, text="https://developer.musixmatch.com (gratis)", bg=BG_CARD, fg=TEXT_MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=16)

        # Spotify
        self.tk.Label(win, text="Spotify Client ID & Secret (untuk fitur Search Spotify)", bg=BG_CARD, fg=TEXT_PRIMARY,
                      font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(14, 2))

        sp_id_var = self.tk.StringVar(value=self.config.get("spotify_client_id") or "")
        sp_secret_var = self.tk.StringVar(value=self.config.get("spotify_client_secret") or "")

        self.tk.Label(win, text="Client ID:", bg=BG_CARD, fg=TEXT_SECONDARY).pack(anchor="w", padx=16)
        sp_id_entry = self.tk.Entry(win, textvariable=sp_id_var, width=52, font=("Consolas", 9))
        sp_id_entry.pack(padx=16, pady=1)

        self.tk.Label(win, text="Client Secret:", bg=BG_CARD, fg=TEXT_SECONDARY).pack(anchor="w", padx=16)
        sp_secret_entry = self.tk.Entry(win, textvariable=sp_secret_var, width=52, font=("Consolas", 9), show="*")
        sp_secret_entry.pack(padx=16, pady=1)

        self.tk.Label(win, text="Buat app di https://developer.spotify.com/dashboard (pilih Client Credentials)", 
                      bg=BG_CARD, fg=TEXT_MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=16)

        self.tk.Label(win, text="Cache YouTube: " + str(CACHE_DIR), bg=BG_CARD, fg=TEXT_SECONDARY,
                      font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(12, 2))

        def save():
            # Musixmatch
            new_mm_key = mm_key_var.get().strip() or None
            self.config["musixmatch_key"] = new_mm_key
            self.lyrics_provider = LyricsProvider(musixmatch_key=new_mm_key)

            # Spotify
            self.config["spotify_client_id"] = sp_id_var.get().strip() or None
            self.config["spotify_client_secret"] = sp_secret_var.get().strip() or None

            self._save_config()
            win.destroy()
            self.status.config(text="Settings saved!")

        def clear_cache():
            import shutil
            try:
                shutil.rmtree(CACHE_DIR)
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                self.status.config(text="YouTube cache dibersihkan.")
            except Exception as e:
                self.messagebox.showerror("Error", str(e))

        btns = self.tk.Frame(win, bg=BG_CARD)
        btns.pack(side="bottom", pady=14)
        self.ttk.Button(btns, text="Simpan", command=save, style="Accent.TButton").pack(side="left", padx=6)
        self.ttk.Button(btns, text="Hapus Cache YouTube", command=clear_cache).pack(side="left", padx=6)
        self.ttk.Button(btns, text="Tutup", command=win.destroy).pack(side="left", padx=6)

    # ---------- Public helpers ----------
    def run(self):
        self.root.mainloop()


# ==================== ENTRY ====================
if __name__ == "__main__":
    # Final import here for the launcher
    import tkinter as tk
    root = tk.Tk()
    app = LirikBarApp(root)
    app.run()
