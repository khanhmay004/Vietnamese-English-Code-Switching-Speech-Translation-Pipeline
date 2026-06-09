"""
YouTube Ingestion GUI - Tkinter Client (3-Tab Architecture).

Standalone GUI for downloading YouTube videos and uploading to the server.
Performs duplicate detection before download with auto-channel-creation.

Features:
    - Tab 1: Multiple Video URLs (comma/newline separated)
    - Tab 2: Playlist Mode (multiple playlist URLs)
    - Tab 3: Channel Mode (single channel URL with video browser)
    - Auto-channel detection and creation
    - Global progress bar with download/upload tracking
    - Error summary at completion

Usage:
    python ingest_gui.py
"""

import os
import sys
import threading
from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass, field
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Load .env file BEFORE reading environment variables
from dotenv import load_dotenv
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import requests

from backend.ingestion.downloader import (
    fetch_metadata,
    fetch_playlist_metadata,
    download_audio,
    VideoMetadata
)


# =============================================================================
# CONFIGURATION
# =============================================================================

API_BASE = os.getenv("API_BASE", "http://localhost:8000/api")
DATA_ROOT = Path(os.getenv("DATA_ROOT", "./data"))
TEMP_DIR = DATA_ROOT / "temp"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DownloadResult:
    """Result of a download+upload operation."""
    video: VideoMetadata
    success: bool
    error_message: Optional[str] = None


@dataclass
class BatchProgress:
    """Tracks batch download progress."""
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    failed_videos: List[Tuple[str, str, str]] = field(default_factory=list)  # (title, error, url)


# =============================================================================
# API FUNCTIONS
# =============================================================================

def check_duplicate(url: str) -> dict:
    """Check if URL already exists in database."""
    try:
        resp = requests.get(f"{API_BASE}/videos/check", params={"url": url}, timeout=10)
        return resp.json()
    except Exception as e:
        return {"exists": False, "message": str(e)}


def get_users() -> List[dict]:
    """Fetch user list from API."""
    try:
        resp = requests.get(f"{API_BASE}/users", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def check_server_health() -> Tuple[bool, str]:
    """
    Check if server is reachable.
    
    Returns:
        (is_healthy, message)
    """
    try:
        resp = requests.get(f"{API_BASE.replace('/api', '')}/health", timeout=5)
        if resp.status_code == 200:
            return True, "Connected"
        return False, f"Status {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Connection refused"
    except requests.exceptions.Timeout:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)[:30]


def get_channels() -> List[dict]:
    """Fetch channel list from API."""
    try:
        resp = requests.get(f"{API_BASE}/channels", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            return data
        return []
    except Exception:
        return []


def get_or_create_channel(name: str, url: str) -> Optional[dict]:
    """
    Get existing channel by URL, or create a new one.
    
    Args:
        name: Channel display name
        url: YouTube channel URL
        
    Returns:
        Channel dict with 'id' key, or None if failed
    """
    try:
        # Try to find existing channel by URL
        resp = requests.get(f"{API_BASE}/channels/by-url", params={"url": url}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        
        # Channel not found, create it
        resp = requests.post(
            f"{API_BASE}/channels",
            json={"name": name, "url": url},
            timeout=10
        )
        if resp.status_code == 201:
            return resp.json()
        elif resp.status_code == 409:
            # Race condition: channel was created between check and create
            resp = requests.get(f"{API_BASE}/channels/by-url", params={"url": url}, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        
        return None
    except Exception as e:
        print(f"Channel API error: {e}")
        return None


def upload_video(
    file_path: Path,
    title: str,
    duration: int,
    url: str,
    channel_id: int,
    user_id: int
) -> dict:
    """Upload video to server."""
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{API_BASE}/videos/upload",
                headers={"X-User-ID": str(user_id)},
                files={"audio": (file_path.name, f, "audio/mp4")},
                data={
                    "title": title,
                    "duration_seconds": duration,
                    "original_url": url,
                    "channel_id": channel_id,
                },
                timeout=300  # 5 min timeout for large files
            )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# GUI APPLICATION
# =============================================================================

class IngestGUI:
    """YouTube ingestion GUI application with 3-tab architecture."""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("🎙️ Speech Translation - YouTube Ingestion")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        # Configure style
        self._setup_styles()
        
        # Data
        self.videos: List[VideoMetadata] = []
        self.users = get_users()
        self.progress = BatchProgress()
        self.is_downloading = False
        self.detected_channel: Optional[dict] = None  # Auto-detected channel
        
        self._build_ui()
    
    def _setup_styles(self):
        """Configure ttk styles."""
        style = ttk.Style()
        style.configure("TFrame", background="#f0f0f0")
        style.configure("TLabel", background="#f0f0f0")
        style.configure("TButton", padding=6)
        style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Success.TLabel", foreground="green")
        style.configure("Error.TLabel", foreground="red")
    
    def _build_ui(self):
        """Build the user interface."""
        # Main container
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        
        # ========== Top Section: User Selection ==========
        self._build_user_section(main)
        
        # ========== Tab Notebook ==========
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Build all 3 tabs
        self._build_tab_urls(self.notebook)      # Tab 1: Multiple URLs
        self._build_tab_playlist(self.notebook)  # Tab 2: Playlist Mode
        self._build_tab_channel(self.notebook)   # Tab 3: Channel Mode
        
        # ========== Progress Section ==========
        self._build_progress_section(main)
        
        # ========== Log Section ==========
        self._build_log_section(main)
    
    def _build_user_section(self, parent):
        """Build user selection dropdown and server status."""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(frame, text="User:", style="Header.TLabel").pack(side=tk.LEFT, padx=(0, 5))
        self.user_var = tk.StringVar()
        self.user_combo = ttk.Combobox(
            frame,
            textvariable=self.user_var,
            values=[u["username"] for u in self.users],
            width=20,
            state="readonly"
        )
        self.user_combo.pack(side=tk.LEFT, padx=(0, 20))
        if self.users:
            self.user_combo.current(0)
        
        # Channel display (auto-detected, read-only)
        ttk.Label(frame, text="Channel:", style="Header.TLabel").pack(side=tk.LEFT, padx=(0, 5))
        self.channel_label = ttk.Label(frame, text="(auto-detected)", foreground="gray")
        self.channel_label.pack(side=tk.LEFT)
        
        # Server status display (right side)
        server_frame = ttk.Frame(frame)
        server_frame.pack(side=tk.RIGHT)
        
        # Extract host from API_BASE for display (e.g., "100.64.0.1:8000")
        api_host = API_BASE.replace("http://", "").replace("https://", "").replace("/api", "")
        
        # Check server health
        is_healthy, status_msg = check_server_health()
        
        ttk.Label(server_frame, text="Server:", style="Header.TLabel").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(server_frame, text=api_host, foreground="gray").pack(side=tk.LEFT, padx=(0, 5))
        
        # Status indicator
        if is_healthy:
            status_label = ttk.Label(server_frame, text="✓ Connected", foreground="green")
        else:
            status_label = ttk.Label(server_frame, text=f"✗ {status_msg}", foreground="red")
        status_label.pack(side=tk.LEFT)
    
    # =========================================================================
    # TAB 1: Multiple Video URLs
    # =========================================================================
    
    def _build_tab_urls(self, notebook):
        """Build Tab 1: Multiple video URLs input."""
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text="📹 Video URLs")
        
        # Instructions
        ttk.Label(
            tab,
            text="Paste YouTube video URLs (one per line or comma-separated):",
            style="Header.TLabel"
        ).pack(anchor=tk.W, pady=(0, 5))
        
        # Text input for URLs
        url_frame = ttk.Frame(tab)
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.urls_text = scrolledtext.ScrolledText(url_frame, height=5, width=80)
        self.urls_text.pack(fill=tk.X, expand=True)
        
        # Buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(btn_frame, text="Fetch Videos", command=self._fetch_urls).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Clear", command=lambda: self.urls_text.delete("1.0", tk.END)).pack(side=tk.LEFT)
        
        # Video list (shared across tabs, but we'll use the main one)
        self._build_video_list(tab)
    
    # =========================================================================
    # TAB 2: Playlist Mode
    # =========================================================================
    
    def _build_tab_playlist(self, notebook):
        """Build Tab 2: Playlist URLs input."""
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text="📋 Playlists")
        
        # Instructions
        ttk.Label(
            tab,
            text="Paste YouTube playlist URLs (one per line or comma-separated):",
            style="Header.TLabel"
        ).pack(anchor=tk.W, pady=(0, 5))
        
        # Text input for playlist URLs
        url_frame = ttk.Frame(tab)
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.playlist_text = scrolledtext.ScrolledText(url_frame, height=5, width=80)
        self.playlist_text.pack(fill=tk.X, expand=True)
        
        # Buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(btn_frame, text="Fetch Playlists", command=self._fetch_playlists).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Clear", command=lambda: self.playlist_text.delete("1.0", tk.END)).pack(side=tk.LEFT)
        
        # Video list placeholder (shares main tree)
        ttk.Label(tab, text="Videos will appear in the list below after fetching.", foreground="gray").pack(anchor=tk.W)
    
    # =========================================================================
    # TAB 3: Channel Mode
    # =========================================================================
    
    def _build_tab_channel(self, notebook):
        """Build Tab 3: Channel browser."""
        tab = ttk.Frame(notebook, padding=10)
        notebook.add(tab, text="📺 Channel")
        
        # Instructions
        ttk.Label(
            tab,
            text="Paste a YouTube channel URL to browse its videos:",
            style="Header.TLabel"
        ).pack(anchor=tk.W, pady=(0, 5))
        
        # Single URL input for channel
        url_frame = ttk.Frame(tab)
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.channel_url_entry = ttk.Entry(url_frame, width=70)
        self.channel_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.channel_url_entry.bind("<Return>", lambda e: self._fetch_channel())
        
        ttk.Button(url_frame, text="Fetch Channel", command=self._fetch_channel).pack(side=tk.LEFT)
        
        # Sorting options
        sort_frame = ttk.Frame(tab)
        sort_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(sort_frame, text="Sort by:").pack(side=tk.LEFT, padx=(0, 5))
        self.sort_var = tk.StringVar(value="title")
        ttk.Radiobutton(sort_frame, text="Title", variable=self.sort_var, value="title", command=self._sort_videos).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(sort_frame, text="Duration", variable=self.sort_var, value="duration", command=self._sort_videos).pack(side=tk.LEFT, padx=(0, 10))
        
        # Video list placeholder
        ttk.Label(tab, text="Videos will appear in the list below after fetching.", foreground="gray").pack(anchor=tk.W)
    
    # =========================================================================
    # SHARED: Video List (Treeview)
    # =========================================================================
    
    def _build_video_list(self, parent):
        """Build the video list treeview (displayed in main area, shared across tabs)."""
        # This is called from Tab 1, but we'll put the actual list below the notebook
        pass
    
    def _build_progress_section(self, parent):
        """Build global progress bar and video list."""
        # Video list frame
        list_frame = ttk.LabelFrame(parent, text="Videos", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Treeview for video list
        columns = ("title", "duration", "channel", "status")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("title", text="Title", command=lambda: self._sort_column("title"))
        self.tree.heading("duration", text="Duration", command=lambda: self._sort_column("duration"))
        self.tree.heading("channel", text="Channel")
        self.tree.heading("status", text="Status")
        self.tree.column("title", width=400)
        self.tree.column("duration", width=80)
        self.tree.column("channel", width=150)
        self.tree.column("status", width=120)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Action buttons
        action_frame = ttk.Frame(parent)
        action_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(action_frame, text="Select All", command=self._select_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Deselect All", command=self._deselect_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Check Duplicates", command=self._check_duplicates).pack(side=tk.LEFT, padx=(0, 5))
        self.download_btn = ttk.Button(action_frame, text="Download Selected", command=self._download_selected)
        self.download_btn.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Clear List", command=self._clear_list).pack(side=tk.LEFT)
        
        # Progress bar
        progress_frame = ttk.Frame(parent)
        progress_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.progress_label = ttk.Label(progress_frame, text="Ready")
        self.progress_label.pack(side=tk.LEFT, padx=(0, 10))
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", length=400)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
    
    def _build_log_section(self, parent):
        """Build log output section."""
        log_frame = ttk.LabelFrame(parent, text="Log", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)  # Allow expansion
        
        self.log = scrolledtext.ScrolledText(log_frame, height=12, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)
    
    # =========================================================================
    # LOGGING
    # =========================================================================
    
    def _log(self, message: str):
        """Add message to log (thread-safe)."""
        def _do_log():
            self.log.configure(state=tk.NORMAL)
            self.log.insert(tk.END, f"{message}\n")
            self.log.see(tk.END)
            self.log.configure(state=tk.DISABLED)
        
        if threading.current_thread() is threading.main_thread():
            _do_log()
        else:
            self.root.after(0, _do_log)
    
    def _update_progress(self):
        """Update progress bar and label."""
        def _do_update():
            p = self.progress
            total = p.total
            done = p.completed + p.failed + p.skipped
            
            if total > 0:
                self.progress_bar["value"] = (done / total) * 100
                self.progress_label.config(
                    text=f"Progress: {done}/{total} (✓{p.completed} ✗{p.failed} ⏭{p.skipped})"
                )
            else:
                self.progress_bar["value"] = 0
                self.progress_label.config(text="Ready")
        
        self.root.after(0, _do_update)
    
    # =========================================================================
    # URL PARSING
    # =========================================================================
    
    def _parse_urls(self, text: str) -> List[str]:
        """Parse URLs from text (comma or newline separated)."""
        # Replace commas with newlines, then split
        text = text.replace(",", "\n")
        urls = []
        for line in text.strip().split("\n"):
            url = line.strip()
            if url and ("youtube.com" in url or "youtu.be" in url):
                urls.append(url)
        return urls
    
    # =========================================================================
    # TAB 1: Fetch Multiple URLs
    # =========================================================================
    
    def _fetch_urls(self):
        """Fetch metadata for multiple video URLs."""
        text = self.urls_text.get("1.0", tk.END)
        urls = self._parse_urls(text)
        
        if not urls:
            messagebox.showwarning("Error", "Please enter at least one valid YouTube URL")
            return
        
        self._log(f"Fetching {len(urls)} URLs...")
        self._clear_list()
        
        def fetch():
            all_videos = []
            for url in urls:
                try:
                    videos = fetch_playlist_metadata(url)
                    all_videos.extend(videos)
                    self._log(f"  Found {len(videos)} video(s) from {url[:50]}...")
                except Exception as e:
                    self._log(f"  ✗ Failed: {url[:50]}... ({e})")
            
            # Deduplicate by original_url
            seen = set()
            unique_videos = []
            for v in all_videos:
                if v.original_url not in seen:
                    seen.add(v.original_url)
                    unique_videos.append(v)
            
            self.root.after(0, lambda: self._update_video_list(unique_videos))
        
        threading.Thread(target=fetch, daemon=True).start()
    
    # =========================================================================
    # TAB 2: Fetch Playlists
    # =========================================================================
    
    def _fetch_playlists(self):
        """Fetch metadata for multiple playlist URLs."""
        text = self.playlist_text.get("1.0", tk.END)
        urls = self._parse_urls(text)
        
        if not urls:
            messagebox.showwarning("Error", "Please enter at least one valid playlist URL")
            return
        
        self._log(f"Fetching {len(urls)} playlists...")
        self._clear_list()
        
        def fetch():
            all_videos = []
            for url in urls:
                try:
                    videos = fetch_playlist_metadata(url)
                    all_videos.extend(videos)
                    self._log(f"  Found {len(videos)} video(s) from playlist")
                except Exception as e:
                    self._log(f"  ✗ Failed: {url[:50]}... ({e})")
            
            # Deduplicate
            seen = set()
            unique_videos = []
            for v in all_videos:
                if v.original_url not in seen:
                    seen.add(v.original_url)
                    unique_videos.append(v)
            
            self.root.after(0, lambda: self._update_video_list(unique_videos))
        
        threading.Thread(target=fetch, daemon=True).start()
    
    # =========================================================================
    # TAB 3: Fetch Channel
    # =========================================================================
    
    def _fetch_channel(self):
        """Fetch all videos from a YouTube channel."""
        url = self.channel_url_entry.get().strip()
        if not url:
            messagebox.showwarning("Error", "Please enter a channel URL")
            return
        
        self._log(f"Fetching channel: {url}")
        self._clear_list()
        
        def fetch():
            try:
                videos = fetch_playlist_metadata(url)
                
                if videos:
                    # Extract channel info from first video
                    channel_name = videos[0].channel_name or "Unknown"
                    channel_url = videos[0].channel_url or url
                    
                    # Auto-detect/create channel
                    self.detected_channel = get_or_create_channel(channel_name, channel_url)
                    
                    if self.detected_channel:
                        self.root.after(0, lambda: self.channel_label.config(
                            text=f"{self.detected_channel['name']} (ID: {self.detected_channel['id']})",
                            foreground="green"
                        ))
                        self._log(f"  Channel detected: {channel_name}")
                    else:
                        self._log(f"  ⚠ Could not create channel in database")
                
                self.root.after(0, lambda: self._update_video_list(videos))
                
            except Exception as e:
                self._log(f"  ✗ Failed to fetch channel: {e}")
        
        threading.Thread(target=fetch, daemon=True).start()
    
    # =========================================================================
    # VIDEO LIST OPERATIONS
    # =========================================================================
    
    def _update_video_list(self, videos: List[VideoMetadata]):
        """Update video list in UI."""
        self.videos = videos
        self.tree.delete(*self.tree.get_children())
        
        for video in videos:
            duration_str = f"{video.duration_seconds // 60}:{video.duration_seconds % 60:02d}"
            channel = video.channel_name or "Unknown"
            self.tree.insert("", tk.END, values=(video.title, duration_str, channel, "Ready"))
        
        # Auto-detect channel from first video if not already set
        if videos and not self.detected_channel:
            first = videos[0]
            if first.channel_url:
                self.detected_channel = get_or_create_channel(
                    first.channel_name or "Unknown",
                    first.channel_url
                )
                if self.detected_channel:
                    self.channel_label.config(
                        text=f"{self.detected_channel['name']} (ID: {self.detected_channel['id']})",
                        foreground="green"
                    )
        
        self._log(f"Found {len(videos)} videos total")
    
    def _clear_list(self):
        """Clear video list."""
        self.tree.delete(*self.tree.get_children())
        self.videos.clear()
        self.detected_channel = None
        self.channel_label.config(text="(auto-detected)", foreground="gray")
        self.progress = BatchProgress()
        self._update_progress()
    
    def _select_all(self):
        """Select all videos in list."""
        for item in self.tree.get_children():
            self.tree.selection_add(item)
    
    def _deselect_all(self):
        """Deselect all videos."""
        self.tree.selection_remove(*self.tree.get_children())
    
    def _sort_videos(self):
        """Sort videos based on current sort setting."""
        self._sort_column(self.sort_var.get())
    
    def _sort_column(self, col: str):
        """Sort treeview by column."""
        if not self.videos:
            return
        
        if col == "title":
            self.videos.sort(key=lambda v: v.title.lower())
        elif col == "duration":
            self.videos.sort(key=lambda v: v.duration_seconds, reverse=True)
        
        self._update_video_list(self.videos)
    
    # =========================================================================
    # DUPLICATE CHECK
    # =========================================================================
    
    def _check_duplicates(self):
        """Check all videos for duplicates."""
        if not self.videos:
            messagebox.showwarning("Error", "No videos to check")
            return
        
        self._log("Checking for duplicates...")
        
        def check():
            for i, video in enumerate(self.videos):
                item = self.tree.get_children()[i]
                result = check_duplicate(video.original_url)
                
                if result.get("exists"):
                    self.root.after(0, lambda it=item: self.tree.set(it, "status", "⚠️ Duplicate"))
                else:
                    self.root.after(0, lambda it=item: self.tree.set(it, "status", "✓ OK"))
            
            self._log("Duplicate check complete")
        
        threading.Thread(target=check, daemon=True).start()
    
    # =========================================================================
    # DOWNLOAD + UPLOAD
    # =========================================================================
    
    def _download_selected(self):
        """Download and upload selected videos."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Error", "Please select videos first")
            return
        
        if self.is_downloading:
            messagebox.showwarning("Error", "Download already in progress")
            return
        
        # Get user
        user_idx = self.user_combo.current()
        if user_idx < 0:
            messagebox.showwarning("Error", "Please select a user")
            return
        
        user_id = self.users[user_idx]["id"]
        
        # Prepare temp directory
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        
        # Reset progress
        self.progress = BatchProgress()
        self.progress.total = len(selection)
        self._update_progress()
        
        self.is_downloading = True
        self.download_btn.config(state=tk.DISABLED)
        
        def download_all():
            for item in selection:
                idx = self.tree.index(item)
                video = self.videos[idx]
                
                # Skip duplicates
                status = self.tree.set(item, "status")
                if "Duplicate" in status:
                    self._log(f"⏭ Skipping duplicate: {video.title[:50]}...")
                    self.progress.skipped += 1
                    self._update_progress()
                    continue
                
                # Update status
                self.root.after(0, lambda it=item: self.tree.set(it, "status", "⏳ Downloading..."))
                
                try:
                    # Download
                    result = download_audio(
                        video.original_url,
                        TEMP_DIR,
                        lambda msg: self._log(f"  {msg}")
                    )
                    
                    if not result or not result.file_path:
                        raise Exception("Download returned no file")
                    
                    # Get or create channel for THIS SPECIFIC VIDEO
                    # CRITICAL: Always use each video's own channel metadata,
                    # NOT the cached detected_channel from first video
                    channel_id = None
                    if result.channel_url:
                        ch = get_or_create_channel(result.channel_name or "Unknown", result.channel_url)
                        if ch:
                            channel_id = ch["id"]
                            self._log(f"  → Channel: {ch['name']}")
                    
                    if not channel_id:
                        raise Exception("Could not determine channel from video metadata")
                    
                    # Upload
                    self.root.after(0, lambda it=item: self.tree.set(it, "status", "⏳ Uploading..."))
                    
                    upload_result = upload_video(
                        result.file_path,
                        result.title,
                        result.duration_seconds,
                        result.original_url,
                        channel_id,
                        user_id
                    )
                    
                    if "video_id" in upload_result:
                        self.root.after(0, lambda it=item: self.tree.set(it, "status", "✓ Complete"))
                        self._log(f"✓ Uploaded: {video.title[:50]}...")
                        self.progress.completed += 1
                    else:
                        error = upload_result.get("error", upload_result.get("detail", "Unknown error"))
                        raise Exception(f"Upload failed: {error}")
                    
                    # Clean up temp file
                    try:
                        if result.file_path and result.file_path.exists():
                            result.file_path.unlink()
                    except Exception:
                        pass
                    
                except Exception as e:
                    error_msg = str(e)
                    self._log(f"✗ Failed: {video.title[:50]}... - {error_msg}")
                    self.root.after(0, lambda it=item, err=error_msg[:30]: self.tree.set(it, "status", f"✗ {err}"))
                    self.progress.failed += 1
                    self.progress.failed_videos.append((video.title, error_msg, video.original_url))
                
                self._update_progress()
            
            # Summary
            self._log("=" * 50)
            self._log(f"Batch complete: {self.progress.completed} success, {self.progress.failed} failed, {self.progress.skipped} skipped")
            
            if self.progress.failed_videos:
                self._log("\nFailed videos:")
                for title, error, url in self.progress.failed_videos:
                    self._log(f"  - {title[:40]}...: {error}")
                
                # Copy-paste ready URLs section
                self._log("\n" + "=" * 50)
                self._log("📋 FAILED URLS (copy-paste ready):")
                self._log("-" * 40)
                for title, error, url in self.progress.failed_videos:
                    self._log(url)
                self._log("-" * 40)
                self._log(f"Total failed: {len(self.progress.failed_videos)}")
            
            self.is_downloading = False
            self.root.after(0, lambda: self.download_btn.config(state=tk.NORMAL))
        
        threading.Thread(target=download_all, daemon=True).start()


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run the ingestion GUI."""
    root = tk.Tk()
    app = IngestGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
