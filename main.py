import sys
import os
import io

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

os.environ["QT_WAYLAND_DISABLE_WINDOWDECORATION"] = "1"
os.environ["QT_QPA_PLATFORM"] = "xcb"

import re
import logging
import aiohttp
import json
import time
import asyncio
import datetime
import webbrowser
from datetime import datetime as dt_obj
from dotenv import load_dotenv

from oauth_server import start_oauth_server, get_authorization_code
from oauth_manager import (
    get_access_token,
    refresh_access_token,
    refresh_and_update_tokens,
    get_authorization_url,
    schedule_token_refresh,
    check_and_refresh_on_401,
    is_token_expired_error
)
import aiomisc

# PyQt6 Imports
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy,
    QPushButton, QFileDialog, QSlider, QLabel, QCheckBox, QComboBox,
    QMenuBar, QMenu, QMainWindow, QStatusBar, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal as Signal, QSignalBlocker, QEvent
from PyQt6.QtGui import QIcon, QAction

import mpv

logging.basicConfig(level=logging.INFO)

# Получаем путь к самому AppImage файлу
def get_appimage_path():
    # Проверяем, запущены ли мы как AppImage
    appimage = os.environ.get('APPIMAGE')
    if appimage:
        # Возвращаем директорию, где находится AppImage
        return os.path.dirname(appimage)
    
    # Проверяем другой способ - переменная OWD (Original Working Directory)
    owd = os.environ.get('OWD')
    if owd:
        return owd

    # Fallback: обычный путь
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    elif __file__:
        return os.path.dirname(__file__)

# Определяем pyinstaller
pyinstaller = False
try:
    sys._MEIPASS
    pyinstaller = True
except Exception:
    pass

# Получаем путь к исходной директории с AppImage
pathname = get_appimage_path()
print(f"Original AppImage directory: {pathname}")

# ======================
# LOGGING CONFIGURATION
# ======================
# Set up logging to track application events with timestamps
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ======================
# ENVIRONMENT VARIABLES
# ======================
# Load environment variables from .env file
load_dotenv(f"{pathname}/.env")

# ======================
# STATE MANAGEMENT
# ======================
# File to store playback state (watched position, skip settings)
STATE_FILE = f"{pathname}/playback_state.json"
# File to store folder history
FOLDER_HISTORY_FILE = f"{pathname}/folder_history.json"

def load_state():
    """Load playback state from JSON file."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    """Save playback state to JSON file."""
    if getattr(save_state, '_in_progress', False):
        return
    save_state._in_progress = True
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except:
        pass
    finally:
        save_state._in_progress = False

def load_folder_history():
    """Load folder history from JSON file."""
    if not os.path.exists(FOLDER_HISTORY_FILE):
        return []
    try:
        with open(FOLDER_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_folder_history(history):
    """Save folder history to JSON file."""
    if getattr(save_folder_history, '_in_progress', False):
        return
    save_folder_history._in_progress = True
    try:
        with open(FOLDER_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except:
        pass
    finally:
        save_folder_history._in_progress = False

def add_to_folder_history(folder):
    """Add folder to history, keeping only the last 5."""
    if getattr(add_to_folder_history, '_in_progress', False):
        return
    add_to_folder_history._in_progress = True
    try:
        if not os.path.exists(FOLDER_HISTORY_FILE):
            history = []
        else:
            try:
                with open(FOLDER_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except:
                history = []
        if folder in history:
            history.remove(folder)
        history.insert(0, folder)
        history = history[:5]
        save_folder_history(history)
    finally:
        add_to_folder_history._in_progress = False

# ======================
# EPISODE PARSER
# ======================
def get_episode(path):
    """Extract episode number from filename using various patterns."""
    name = os.path.basename(path).lower()
    # Match patterns: e12, ep12, episode12, or standalone number
    match = re.search(r"(?:e|ep|episode)?\s*(\d+)", name)
    if match:
        return int(match.group(1))

    # Match patterns: s01e12 (season + episode)
    match = re.search(r"s\d+e(\d+)", name)
    if match:
        return int(match.group(1))

    return 1

# ======================
# SORT KEY FUNCTION
# ======================
def anime_sort_key(path):
    """Generate sort key for anime files based on season and episode numbers."""
    name = os.path.basename(path).lower()
    match = re.search(r"(s(\d+))?e?(\d+)", name)
    if match:
        # Extract season (default 0) and episode (default 0)
        season = int(match.group(2)) if match.group(2) else 0
        episode = int(match.group(3)) if match.group(3) else 0
        return (season, episode)
    return name

# ======================
# USER INFO WORKER
# ======================
class UserInfoWorker(QThread):
    """Background thread to fetch user information from Shikimori API."""
    result = Signal(dict)

    def __init__(self, token):
        super().__init__()
        self.token = token
        self.token_updated = False
        self.new_token = None

    async def _fetch_user_info(self):
        global SHIKIMORI_TOKEN
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://shikimori.io/api/users/whoami",
                headers={
                    "User-Agent": "AnimePlayer",
                    "Authorization": f"Bearer {self.token}"
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 401:
                    is_refreshed, new_token_data = await check_and_refresh_on_401(response, None)
                    if is_refreshed and new_token_data:
                        self.token = new_token_data["access_token"]
                        self.new_token = new_token_data["access_token"]
                        self.token_updated = True
                        SHIKIMORI_TOKEN = new_token_data["access_token"]
                        return await self._fetch_user_info()
                    else:
                        return {"error": "401 Unauthorized - token invalid or expired"}
                response.raise_for_status()
                return await response.json()

    def run(self):
        """Fetch current user data from Shikimori API."""
        try:
            data = asyncio.run(self._fetch_user_info())
            self.result.emit(data)
        except Exception as e:
            self.result.emit({"error": str(e)})

# ======================
# ANIME SEARCH WORKER
# ======================
class AnimeSearchWorker(QThread):
    """Background thread to search for anime and fetch episode opening/endings data."""
    result = Signal(dict)

    def __init__(self, query):
        super().__init__()
        self.query = query

    async def _search_anime(self):
        global SHIKIMORI_TOKEN
        async with aiohttp.ClientSession() as session:
            headers_auth = {
                "User-Agent": "AnimePlayer",
                "Authorization": f"Bearer {SHIKIMORI_TOKEN}",
            }
            headers_no_auth = {
                "User-Agent": "AnimePlayer",
            }
            
            headers = headers_auth if SHIKIMORI_TOKEN else headers_no_auth
            
            async with session.get(
                "https://shikimori.io/api/animes",
                params={"search": self.query},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 401:
                    is_refreshed, new_token_data = await check_and_refresh_on_401(response, None)
                    if is_refreshed and new_token_data:
                        SHIKIMORI_TOKEN = new_token_data["access_token"]
                        return await self._search_anime()
                    else:
                        return {"error": "401 Unauthorized - token invalid or expired"}
                response.raise_for_status()
                data = await response.json()

            if not data:
                return {"error": "api/animes not found"}

            anime = data[0]
            await asyncio.sleep(0.3)

            async with session.get(
                f"https://shikimori.io/api/animes/{anime.get('id')}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 401:
                    is_refreshed, new_token_data = await check_and_refresh_on_401(response, None)
                    if is_refreshed and new_token_data:
                        SHIKIMORI_TOKEN = new_token_data["access_token"]
                        return await self._search_anime()
                    else:
                        return {"error": "401 Unauthorized - token invalid or expired"}
                response.raise_for_status()
                data = await response.json()

            if not data:
                return {"error": f"api/animes/{anime.get('id')} not found"}

            headers_anilibria = {
                "User-Agent": "AnimePlayer",
            }

            async with session.get(
                "https://anilibria.top/api/v1/app/search/releases",
                params={"query": data.get("russian") or data.get("name")},
                headers=headers_anilibria,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response.raise_for_status()
                data_anilibria = await response.json()

            data_episodes = [{
                "number": 0,
                "opening": 0,
                "ending": 0
            }]

            if data_anilibria:            
                anime_anilibria = data_anilibria[0]

                async with session.get(
                    f"https://anilibria.top/api/v1/anime/releases/{anime_anilibria.get('id')}",
                    headers=headers_anilibria,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()
                    data_anilibria_release = await response.json()

                    if data_anilibria_release:
                        data_episodes = []
                        for episode in data_anilibria_release.get("episodes", []):
                            ep_num = episode.get("ordinal")
                            if ep_num is None:
                                continue
                        
                            data_ep_anilibria = {
                                "number": ep_num,
                                "opening": episode.get("opening"),
                                "ending": episode.get("ending")
                            }
                            data_episodes.append(data_ep_anilibria)

            ur = data.get("user_rate") or {}

            return {
                "id": data.get("id"),
                "name": data.get("russian") or data.get("name"),
                "image": data.get("image", {}).get("original"),
                "user_rate": ur.get("id"),
                "anilibria_episodes": data_episodes,
            }

    def run(self):
        """Search for anime on Shikimori and fetch episode data from Anilibria."""
        try:
            data = asyncio.run(self._search_anime())
            self.result.emit(data)
        except Exception as e:
            print(f"Anime search error for '{self.query}': {e}")
            self.result.emit({"error": str(e)})

# ======================
# USER RATES WORKER
# ======================
class UserRateWorker(QThread):
    """Background thread to increment user's anime progress on Shikimori."""
    result = Signal(dict)

    def __init__(self, user_id, anime_id, id_rate, episode, token):
        super().__init__()
        self.user_id = user_id
        self.anime_id = anime_id
        self.id_rate = id_rate
        self.episode = episode
        self.token = token

    async def _update_user_rate(self):
        global SHIKIMORI_TOKEN
        async with aiohttp.ClientSession() as session:
            headers_auth = {
                "User-Agent": "AnimePlayer",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            headers_no_auth = {
                "User-Agent": "AnimePlayer",
                "Content-Type": "application/json"
            }
            headers = headers_auth if self.token else headers_no_auth

            url = f"https://shikimori.io/api/v2/user_rates/{self.id_rate}"

            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 401:
                    is_refreshed, new_token_data = await check_and_refresh_on_401(response, None)
                    if is_refreshed and new_token_data:
                        self.token = new_token_data["access_token"]
                        SHIKIMORI_TOKEN = new_token_data["access_token"]
                        return await self._update_user_rate()
                    else:
                        return {"error": "401 Unauthorized - token invalid or expired"}
                response.raise_for_status()
                data = await response.json()

            if int(self.episode) <= int(data.get("episodes", 0)):
                return {"message": "No increment needed"}
            
            url = f"{url}/increment"
            
            async with session.post(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 401:
                    is_refreshed, new_token_data = await check_and_refresh_on_401(response, None)
                    if is_refreshed and new_token_data:
                        self.token = new_token_data["access_token"]
                        SHIKIMORI_TOKEN = new_token_data["access_token"]
                        return await self._update_user_rate()
                    else:
                        return {"error": "401 Unauthorized - token invalid or expired"}
                response.raise_for_status()
                data = await response.json()

            return data

    def run(self):
        """Send episode progress update to Shikimori API."""
        try:
            if not self.id_rate:
                self.result.emit({"error": "no user_rate id"})
                return
            
            data = asyncio.run(self._update_user_rate())
            logging.info(f"USER_RATE RESPONSE: {json.dumps(data, ensure_ascii=False, indent=2)}")
            self.result.emit(data)

        except Exception as e:
            logging.error(f"USER_RATE ERROR: {e}")
            self.result.emit({"error": str(e)})

# ======================
# PLAYER WINDOW
# ======================
class Player(QMainWindow):
    """Main application window for anime video playback — VLC-style UI."""
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon(f"{pathname}/icon.png"))

        self.is_fullscreen = False
        self.normal_geometry = None

        # Window setup
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle("Anime Player")
        self.resize(1100, 700)
        self.setMinimumSize(800, 500)

        # Load saved playback state
        self.state = load_state()

        # Load folder history
        self.folder_history = load_folder_history()

        # Get skip settings from state
        skip_state = self.state.get("skip_settings", {}).get("skip_op_enabled", False)
        self.playlist = []
        self.index = 0
        self.current_file = None

        # Store episode metadata for OP/ED skipping
        self.anilibria_episode_select_op_end = None

        # Anime info
        self.anime_id = None
        self.anime_name = None
        self.anime_image_url = None

        # User rate tracking
        self.user_id = None
        self.user_rate = None   
        self.last_sent_episode = 0

        # Current episode tracking
        self.current_episode = 1

        # Seek state tracking
        self.user_seeking = False
        self.duration = 0
        self.position = 0

        # Throttling for state saving
        self.last_save_time = 0

        # OP/ED skipping state
        self.skipping_op_ed = False

        # Track all workers for proper cleanup on exit
        self._workers = set()

        # ===== SKIP SETTINGS =====
        self.skip_op_enabled = skip_state
        self.player = None

        # ===== MENU BAR (VLC-style) =====
        self._setup_menu()

        # ===== CENTRAL WIDGET =====
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Video area
        self.video = QWidget()
        self.video.installEventFilter(self)
        self.video.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.video.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video.setUpdatesEnabled(True)
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video.setFocus()
        self.video.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, False)
        self.video.setMouseTracking(True)
        self.video.setObjectName("videoArea")
        self.video.setStyleSheet("""
            QWidget#videoArea {
                background-color: #1a1a1a;
            }
        """)

        main_layout.addWidget(self.video, 1)

        # ===== INFO BAR (thin, below video) =====
        self.info_bar = QFrame()
        self.info_bar.setObjectName("infoBar")
        self.info_bar.setStyleSheet("""
            QFrame#infoBar {
                background-color: #2d2d2d;
                border-top: 1px solid #444;
                padding: 2px 8px;
            }
        """)
        info_layout = QHBoxLayout(self.info_bar)
        info_layout.setContentsMargins(8, 2, 8, 2)
        info_layout.setSpacing(12)

        self.anime_label = QLabel("Anime: —")
        self.anime_label.setStyleSheet("color: #ddd; font-size: 12px;")
        self.anime_label.setTextFormat(Qt.TextFormat.PlainText)

        self.shikimori_link = QLabel()
        self.shikimori_link.setOpenExternalLinks(True)
        self.shikimori_link.setStyleSheet("color: #6af; font-size: 12px;")
        self.shikimori_link.setTextFormat(Qt.TextFormat.RichText)

        self.user_label = QLabel("Loading user...")
        self.user_label.setStyleSheet("color: #aaa; font-size: 11px;")

        self.episode_label = QLabel("EP: —")
        self.episode_label.setStyleSheet("color: #ddd; font-size: 12px; font-weight: bold;")

        info_layout.addWidget(self.anime_label, 1)
        info_layout.addWidget(self.episode_label)
        info_layout.addWidget(self.shikimori_link)
        info_layout.addWidget(self.user_label)

        main_layout.addWidget(self.info_bar)

        # ===== BOTTOM CONTROLS (directly in main_layout) =====
        self.bottom_controls = QWidget()
        self.bottom_controls.setObjectName("bottomControls")
        bottom_layout = QVBoxLayout(self.bottom_controls)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        # --- Seek bar row ---
        seek_row = QWidget()
        seek_row_layout = QHBoxLayout(seek_row)
        seek_row_layout.setContentsMargins(8, 4, 8, 2)
        seek_row_layout.setSpacing(6)

        self.time_start = QLabel("00:00")
        self.time_start.setStyleSheet("color: #aaa; font-size: 11px; font-family: monospace;")
        self.time_start.setMinimumWidth(40)

        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setObjectName("seekSlider")
        self.seek.setStyleSheet("""
            QSlider#seekSlider::groove:horizontal {
                height: 6px;
                background: #555;
                border-radius: 3px;
            }
            QSlider#seekSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                margin: -4px 0;
                background: #6af;
                border-radius: 7px;
            }
            QSlider#seekSlider::sub-page:horizontal {
                background: #6af;
                border-radius: 3px;
            }
        """)

        self.time_end = QLabel("00:00")
        self.time_end.setStyleSheet("color: #aaa; font-size: 11px; font-family: monospace;")
        self.time_end.setMinimumWidth(40)

        self.time_total = QLabel("/ 00:00")
        self.time_total.setStyleSheet("color: #888; font-size: 11px; font-family: monospace;")

        seek_row_layout.addWidget(self.time_start)
        seek_row_layout.addWidget(self.seek, 1)
        seek_row_layout.addWidget(self.time_end)

        bottom_layout.addWidget(seek_row)

        # --- Buttons row ---
        btn_row_layout = QHBoxLayout()
        btn_row_layout.setContentsMargins(8, 2, 8, 6)
        btn_row_layout.setSpacing(4)

        # Helper to style buttons
        def style_btn(text, tooltip=None, size=(36, 28)):
            btn = QPushButton(text)
            btn.setFixedSize(*size)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #ddd;
                    font-size: 16px;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: #444;
                }
                QPushButton:pressed {
                    background: #555;
                }
            """)
            if tooltip:
                btn.setToolTip(tooltip)
            return btn

        # Transport controls
        btn_style = """
            QPushButton {
                background: transparent;
                color: #ddd;
                font-size: 18px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #444;
            }
            QPushButton:pressed {
                background: #555;
            }
        """
        big_btn_style = """
            QPushButton {
                background: transparent;
                color: #fff;
                font-size: 24px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #444;
            }
            QPushButton:pressed {
                background: #555;
            }
        """

        self.btn_prev = QPushButton("⏮")
        self.btn_prev.setFixedSize(36, 32)
        self.btn_prev.setStyleSheet(btn_style)
        self.btn_prev.setToolTip("Previous (Ctrl+P)")

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(44, 36)
        self.btn_play.setStyleSheet(big_btn_style)
        self.btn_play.setToolTip("Play/Pause (Space)")

        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setFixedSize(36, 32)
        self.btn_stop.setStyleSheet(btn_style)
        self.btn_stop.setToolTip("Stop")

        self.btn_next = QPushButton("⏭")
        self.btn_next.setFixedSize(36, 32)
        self.btn_next.setStyleSheet(btn_style)
        self.btn_next.setToolTip("Next (Ctrl+N)")

        btn_row_layout.addSpacing(8)
        btn_row_layout.addWidget(self.btn_play)
        btn_row_layout.addWidget(self.btn_prev)
        btn_row_layout.addWidget(self.btn_stop)
        btn_row_layout.addWidget(self.btn_next)

        # Fullscreen button
        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setFixedSize(32, 28)
        self.btn_fullscreen.setStyleSheet(btn_style)
        self.btn_fullscreen.setToolTip("Fullscreen (F11)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        btn_row_layout.addWidget(self.btn_fullscreen)

        btn_row_layout.addSpacing(16)

        # Volume
        self.vol_icon = QPushButton("🔊")
        self.vol_icon.setFixedSize(32, 28)
        self.vol_icon.setStyleSheet(btn_style)
        self.vol_icon.setToolTip("Volume")
        self.vol_icon.clicked.connect(self._toggle_mute)

        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.setFixedWidth(100) 
        self.volume.setObjectName("volumeSlider")
        self.volume.setStyleSheet("""
            QSlider#volumeSlider::groove:horizontal {
                height: 4px;
                background: #555;
                border-radius: 2px;
            }
            QSlider#volumeSlider::handle:horizontal {
                width: 12px;
                height: 12px;
                margin: -4px 0;
                background: #ddd;
                border-radius: 6px;
            }
            QSlider#volumeSlider::sub-page:horizontal {
                background: #ddd;
                border-radius: 2px;
            }
        """)

        self.vol_label = QLabel("100%")
        self.vol_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self.vol_label.setMinimumWidth(32)

        self.btn_mute = QCheckBox("Mute")
        self.btn_mute.setStyleSheet("color: #aaa; font-size: 11px;")

        btn_row_layout.addStretch(1)

        # Skip OP/ED
        self.skip_checkbox = QCheckBox("Skip OP/ED")
        self.skip_checkbox.setChecked(self.skip_op_enabled)
        self.skip_checkbox.stateChanged.connect(self.toggle_skip)
        self.skip_checkbox.setStyleSheet("color: #aaa; font-size: 11px;")
        btn_row_layout.addWidget(self.skip_checkbox)

        # Folder history combo
        self.folder_combo = QComboBox()
        self.folder_combo.setFixedWidth(200)
        self.folder_combo.setMaxVisibleItems(5)
        self.update_folder_history_ui()
        self.folder_combo.addItems(self.folder_history)
        self.folder_combo.currentIndexChanged.connect(self.on_folder_selected)
        self.folder_combo.setStyleSheet("""
            QComboBox {
                color: #ddd;
                background: #3a3a3a;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 11px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background: #3a3a3a;
                color: #ddd;
                selection-background-color: #6af;
            }
        """)
        btn_row_layout.addWidget(self.folder_combo)

        btn_row_layout.addSpacing(16)
        btn_row_layout.addWidget(self.vol_icon)
        btn_row_layout.addWidget(self.volume)
        btn_row_layout.addWidget(self.vol_label)

        bottom_layout.addLayout(btn_row_layout)

        main_layout.addWidget(self.bottom_controls)

        # ===== STATUS BAR =====
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.setStyleSheet("color: #aaa; font-size: 11px;")
        self.statusBar.showMessage("Ready")

        # ===== SIGNALS =====
        self.btn_next.clicked.connect(self.next)
        self.btn_prev.clicked.connect(self.prev)
        self.btn_play.clicked.connect(self.toggle)
        self.btn_stop.clicked.connect(self.stop_playback)
        self.volume.valueChanged.connect(self.set_volume)
        self.volume.valueChanged.connect(lambda v: self.vol_label.setText(f"{v}%"))

        self.seek.sliderPressed.connect(self.seek_start)
        self.seek.sliderReleased.connect(self.seek_end)

        # Timer to update UI (every 200ms)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(200)

        # Track mute state
        self.is_muted = False

        self.load_user()

    def _setup_menu(self):
        """Create VLC-style menu bar."""
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #2d2d2d;
                color: #ddd;
                padding: 2px 0;
                border-bottom: 1px solid #444;
            }
            QMenuBar::item:selected {
                background: #444;
            }
            QMenu { 
                background-color: #2d2d2d;
                color: #ddd;
                border: 1px solid #555;
            }
            QMenu::item:selected {
                background: #6af;
                color: #000;
            }
        """)

        # Media menu
        media_menu = menubar.addMenu("&Media")

        open_folder_act = QAction("Open &Folder...\tCtrl+O", self)
        open_folder_act.triggered.connect(self.open_folder)
        media_menu.addAction(open_folder_act)

        media_menu.addSeparator()

        exit_act = QAction("E&xit\tCtrl+Q", self)
        exit_act.triggered.connect(self.close)
        media_menu.addAction(exit_act)

        # Playback menu
        playback_menu = menubar.addMenu("&Playback")

        play_act = QAction("&Play/Pause\tSpace", self)
        play_act.triggered.connect(self.toggle)
        playback_menu.addAction(play_act)

        stop_act = QAction("&Stop\tCtrl+S", self)
        stop_act.triggered.connect(self.stop_playback)
        playback_menu.addAction(stop_act)

        playback_menu.addSeparator()

        prev_act = QAction("&Previous\tCtrl+P", self)
        prev_act.triggered.connect(self.prev)
        playback_menu.addAction(prev_act)

        next_act = QAction("&Next\tCtrl+N", self)
        next_act.triggered.connect(self.next)
        playback_menu.addAction(next_act)

        playback_menu.addSeparator()

        skip_op_act = QAction("Skip &OP/ED", self)
        skip_op_act.setCheckable(True)
        skip_op_act.setChecked(self.skip_op_enabled)
        skip_op_act.toggled.connect(self.toggle_skip)
        playback_menu.addAction(skip_op_act)
        self.skip_op_action = skip_op_act

        # View menu
        view_menu = menubar.addMenu("&View")

        fs_act = QAction("&Fullscreen\tF11", self)
        fs_act.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fs_act)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_act = QAction("&About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _show_about(self):
        """Show simple about dialog."""
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.about(
            self, "About Anime Player",
            "Anime Player v1.0\n\n"
            "A VLC-style anime video player with Shikimori integration.\n"
            "Built with PyQt6 + python-mpv."
        )

    def stop_playback(self):
        """Stop playback and reset."""
        if self.player:
            self.save_progress()
            self.player.stop()
            self.statusBar.showMessage("Stopped")

    def _toggle_mute(self):
        """Toggle mute state."""
        self.is_muted = not self.is_muted
        if self.is_muted:
            if self.player:
                self.player.volume = 0
            self.vol_icon.setText("🔇")
            self.vol_icon.setToolTip("Unmute")
        else:
            v = self.volume.value()
            if self.player:
                self.player.volume = v
            self._update_vol_icon(v)
            self.vol_icon.setToolTip("Volume")

    def _update_vol_icon(self, v):
        """Update volume icon based on level."""
        if v == 0:
            self.vol_icon.setText("🔇")
        elif v < 40:
            self.vol_icon.setText("🔈")
        elif v < 80:
            self.vol_icon.setText("🔉")
        else:
            self.vol_icon.setText("🔊")

    def eventFilter(self, obj, event):
        if obj == self.video and event.type() == QEvent.Type.MouseButtonDblClick:
            self.toggle_fullscreen()
            return True
        if obj == self.video and event.type() == QEvent.Type.Resize and self.player:
            # When video widget resizes, tell mpv to follow
            r = event.size()
            self.player.geometry = f"{r.width()}x{r.height()}"
            return False
        return super().eventFilter(obj, event)

    def toggle_fullscreen(self):
        """Toggle fullscreen mode."""
        if not self.is_fullscreen:
            self.normal_geometry = self.saveGeometry()
            self.menuBar().hide()
            self.statusBar.hide()
            self.info_bar.hide()
            self.bottom_controls.hide()
            if self.player:
                self.player.osc = True
            self.showFullScreen()
            self.is_fullscreen = True
        else:
            self.showNormal()
            if self.normal_geometry:
                self.restoreGeometry(self.normal_geometry)
            self.menuBar().show()
            self.statusBar.show()
            self.info_bar.show()
            self.bottom_controls.show()
            if self.player:
                self.player.osc = False
            self.is_fullscreen = False

    def keyPressEvent(self, event):
        mod = event.modifiers()
        if event.key() == Qt.Key.Key_Space:
            self.toggle()
            event.accept()
            return
        if event.key() == Qt.Key.Key_F11 or event.key() in (Qt.Key.Key_F, 1040):
            self.toggle_fullscreen()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.is_fullscreen:
            self.toggle_fullscreen()
            event.accept()
            return
        if mod == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_O:
            self.open_folder()
            event.accept()
            return
        if mod == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Q:
            self.close()
            event.accept()
            return
        if mod == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_P:
            self.prev()
            event.accept()
            return
        if mod == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_N:
            self.next()
            event.accept()
            return
        if mod == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_S:
            self.stop_playback()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Comma, Qt.Key.Key_Less, Qt.Key.Key_Left):
            self._seek_relative(-5)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Period, Qt.Key.Key_Greater, Qt.Key.Key_Right):
            self._seek_relative(5)
            event.accept()
            return
        super().keyPressEvent(event)

    def update_folder_history_ui(self):
        if not hasattr(self, 'folder_combo') or self.folder_combo is None:
            return

        if getattr(self, '_updating_history', False):
            return

        self._updating_history = True
        try:
            self.folder_combo.clear()

            for folder in self.folder_history:
                if isinstance(folder, str) and os.path.isdir(folder):
                    self.folder_combo.addItem(
                        os.path.basename(folder),
                        folder
                    )
        finally:
            self._updating_history = False

    def on_folder_selected(self, index):
        """Handle folder selection from combo box."""
        if index >= 0:
            folder = self.folder_combo.itemData(index)
            if folder and os.path.isdir(folder):
                self.open_folder(folder)

    def update_user_rate_if_needed(self):
        """Send episode progress to Shikimori if anime and user info available."""
        if not (self.anime_id and self.user_id and self.user_rate):
            return

        # Only increment if episode has progressed
        if self.current_episode <= self.last_sent_episode:
            return

        self.last_sent_episode = self.current_episode

        self.rate_worker = UserRateWorker(
            self.user_id,
            self.anime_id,
            self.user_rate,
            self.current_episode,
            SHIKIMORI_TOKEN
        )
        self._workers.add(self.rate_worker)
        self.rate_worker.finished.connect(self.rate_worker.deleteLater)
        self.rate_worker.finished.connect(lambda w=self.rate_worker: self._workers.discard(w))
        self.rate_worker.result.connect(lambda d: None)
        self.rate_worker.start()

    def load_user(self):
        """Fetch and display current user information."""
        if not SHIKIMORI_TOKEN:
            self.user_label.setText("No SHIKIMORI_TOKEN")
            return

        self.worker = UserInfoWorker(SHIKIMORI_TOKEN)
        self._workers.add(self.worker)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(lambda: setattr(self, "worker", None))
        self.worker.finished.connect(lambda w=self.worker: self._workers.discard(w))
        self.worker.result.connect(self.on_user)
        self.worker.start()

    def on_user(self, data):
        """Handle user info response from API."""
        if "error" in data:
            self.user_label.setText(data["error"])
        else:
            self.user_id = data.get("id")
            self.user_label.setText(f"👤 {data.get('nickname','Unknown')} | ID: {self.user_id}")

    def search_anime(self, file_path):
        """Search for anime info based on current folder name."""
        folder_path = os.path.dirname(file_path)
        name = os.path.basename(folder_path)
        name = re.sub(r"\[.*?\]|\(.*?\)|\d{2,}", " ", name).strip()

        self.anime_worker = AnimeSearchWorker(name)
        self._workers.add(self.anime_worker)
        self.anime_worker.finished.connect(self.anime_worker.deleteLater)
        self.anime_worker.finished.connect(lambda: setattr(self, "anime_worker", None))
        self.anime_worker.finished.connect(lambda w=self.anime_worker: self._workers.discard(w))

        self.anime_worker.result.connect(self.on_anime_found)
        self.anime_worker.start()

    def on_anime_found(self, data):
        """Handle anime search results and update UI."""
        if "error" in data:
            self.anime_label.setText(data.get("error"))
            self.shikimori_link.clear()
            self.anime_id = None
            return

        # Build episode map for OP/ED skipping
        anime_anilibria_episodes = data.get("anilibria_episodes")
        anilibria_episodes_map = {ep["number"]: ep for ep in anime_anilibria_episodes}
        self.anilibria_episode_select_op_end = anilibria_episodes_map.get(int(self.current_episode))

        # Store anime info
        self.anime_id = data["id"]
        self.anime_name = data["name"]
        self.anime_image_url = data["image"]
        self.user_rate = data["user_rate"]

        self.anime_label.setText(f"{self.anime_name}")
        self.episode_label.setText(f"EP: {self.current_episode}")
        self.shikimori_link.setText(f'<a href="https://shikimori.io/animes/{self.anime_id}">Shikimori →</a>')

        self.statusBar.showMessage(f"Loaded: {self.anime_name} — Episode {self.current_episode}")

    def init_mpv(self):
        """Initialize MPV player instance if not already created."""
        if self.player:
            return

        wid = int(self.video.winId())
        print("WINID: ", wid)

        self.player = mpv.MPV(
            wid=str(wid),
            vo="gpu-next",
            keep_open=True,
            loop="no",
            hwdec="auto-safe",
            force_window="yes",
            input_default_bindings=False,
            input_vo_keyboard=False,
            input_media_keys=False,
            osc=False,
        )

        # MPV key bindings removed — all keys handled via Qt keyPressEvent/eventFilter

        # Observer to track current playback position
        @self.player.property_observer("time-pos")
        def time_observer(name, value):
            self.position = value or 0

        # Observer to track video duration
        @self.player.property_observer("duration")
        def duration_observer(name, value):
            self.duration = value or 0

        # Observer for video end (EOF reached)
        @self.player.property_observer('eof-reached')
        def eof_observer(_name, value):
            if value:
                print(f"Видео завершено: {os.path.basename(self.current_file)}")
                self.next()

        # Event callback for end-file event
        @self.player.event_callback("end-file")
        def end(event):
            if getattr(event, "reason", " ") == "eof":
                self.next()

# ======================
# STATE SAVE
# ======================
    def save_progress(self):
        """Save current playback position for the current file."""
        if not self.current_file:
            return

        self.state[self.current_file] = {
            "pos": self.position
        }
        save_state(self.state)

# ======================
# SKIP TOGGLE
# ======================
    def toggle_skip(self, state):
        """Enable/disable automatic OP/ED skipping."""
        self.skip_op_enabled = bool(state)
        self.state.setdefault("skip_settings", {})["skip_op_enabled"] = self.skip_op_enabled
        save_state(self.state)
        # Sync menu action
        if hasattr(self, 'skip_op_action'):
            with QSignalBlocker(self.skip_op_action):
                self.skip_op_action.setChecked(self.skip_op_enabled)

# ======================
# FILES
# ======================
    def open_folder(self, folder=None):
        """Open a folder and load all video files."""
        if isinstance(folder, list):
            if not folder:
                return
            folder = folder[0]
        
        if not folder:
            # Open file dialog to select folder
            folder = QFileDialog.getExistingDirectory(self, "Folder")
            if not folder:
                return
        
        # 👉 ВСЕГДА добавляем папку в историю
        try:
            add_to_folder_history(folder)
        except Exception as e:
            logging.error(f"Error adding to folder history: {e}")
            # Даже если сохранение не удалось, продолжаем работу

        # Обновляем локальный список и UI
        self.folder_history = load_folder_history()

        # Supported video file extensions
        exts = {".mkv", ".mp4", ".avi"}

        files = []
        # Recursively walk through folder to find video files
        for r, _, fs in os.walk(folder):
            for f in fs:
                if os.path.splitext(f)[1].lower() in exts:
                    files.append(os.path.join(r, f))

        # Sort files by season/episode order
        files.sort(key=anime_sort_key)

        self.playlist = files
        self.update_folder_history_ui()

        if not files:
            return

        # =========================
        # FIND LAST WATCHED FILE
        # =========================
        # Find the file with saved position > 0
        last_watched_index = -1

        for i, f in enumerate(files):
            st = self.state.get(f, {})
            if st.get("pos", 0) > 0:
                last_watched_index = i

        # If no watched files found, start from beginning
        if last_watched_index == -1:
            self.index = 0
        else:
            self.index = last_watched_index

        if self.player:
            self.player.stop()
        
        self.load()
        self.toggle()

    def load(self):
        """Load current file into player and restore position."""
        if not self.playlist:
            return
        self.init_mpv()
        self.current_file = self.playlist[self.index]

        # Extract episode number from filename
        self.current_episode = get_episode(self.current_file)

        # Search for anime info
        self.search_anime(self.current_file)
        self.player.loadfile(self.current_file)

        self.statusBar.showMessage(f"Loading: {os.path.basename(self.current_file)}")

        # Restore saved position
        pos = self.state.get(self.current_file, {}).get("pos", 0)

        if pos > 0:
            QTimer.singleShot(700, lambda: self.player.seek(pos, reference="absolute"))

    def next(self):
        """Play next episode in playlist."""
        # Делаем проверку, если файл просмотрен менее чем на 90%, не сохраняем прогресс и не отправляем на Шики, 
        # а просто запускаем следующий эпизод. Если же просмотрен более чем на 90%, сохраняем прогресс, 
        # отправляем на Шики и запускаем следующий эпизод.
        t = self.position 
        l = self.duration

        status_update_rate = False
        if l > 0 and t / l >= 0.9:
            status_update_rate = True

        if not self.playlist:
            return
        if self.index >= len(self.playlist) - 1:
            if status_update_rate: 
                self.update_user_rate_if_needed()
            return
            
        # Save current position before switching
        self.save_progress()
        self.index += 1
        # Reset OP/ED skipping state
        self.skipping_op_ed = False
        self.load() # Load next episode
        # вернуть фокус на видео
        self.video.setFocus()
        # Update user progress on Shikimori
        if status_update_rate: 
            self.update_user_rate_if_needed()

    def prev(self):
        """Play previous episode in playlist."""
        if not self.playlist:
            return
        # Save current position before switching
        self.save_progress()
        self.index = (self.index - 1) % len(self.playlist)
        self.load()
        # вернуть фокус на видео
        self.video.setFocus()

    def closeEvent(self, event):
        # Wait for all tracked workers to finish (including orphaned ones)
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.requestInterruption()
                    worker.wait(3000)
            except RuntimeError:
                pass
        self._workers.clear()

        self.worker = None
        self.anime_worker = None
        self.rate_worker = None

        save_folder_history(self.folder_history)
        event.accept()

    def toggle(self):
        """Toggle playback pause/resume."""
        if self.player:
            self.player.pause = not self.player.pause
            self._update_play_button()

    def _update_play_button(self):
        """Update play button icon based on state."""
        if self.player and not self.player.pause:
            self.btn_play.setText("⏸")
            self.btn_play.setToolTip("Pause (Space)")
        else:
            self.btn_play.setText("▶")
            self.btn_play.setToolTip("Play (Space)")

    def set_volume(self, v):
        """Set player volume (0-100)."""
        if self.is_muted:
            self.is_muted = False
            self.vol_icon.setToolTip("Volume")
        if self.player:
            self.player.volume = v
        self._update_vol_icon(v)

    def seek_start(self):
        """Handle seek slider press."""
        self.user_seeking = True

    def seek_end(self):
        """Handle seek slider release and seek to position."""
        self.user_seeking = False
        if self.player:
            target = (self.seek.value() / 1000) * self.duration
            self.player.seek(target, reference="absolute")

    def _seek_relative(self, seconds):
        """Seek forward or backward by the given number of seconds."""
        if self.player:
            self.player.seek(seconds)

    def update_ui(self):
        """Update UI elements: time labels, seek slider, and handle OP/ED skipping."""
        if not self.player:
            return

        if self.duration > 0:
            # Update play/pause button state
            self._update_play_button()
            
            t = self.position
            l = self.duration

            t_str = f"{int(t//60):02}:{int(t%60):02}"
            l_str = f"{int(l//60):02}:{int(l%60):02}"

            self.time_start.setText(t_str)
            self.time_end.setText(l_str)
            self.time_total.setText(f"/ {l_str}")

            # Update seek slider position
            if not self.user_seeking:
                self.seek.blockSignals(True)
                self.seek.setValue(int((t / l) * 1000))
                self.seek.blockSignals(False)

        # Throttled state save (every 1 second)
        now = time.time()
        if now - self.last_save_time > 1.0:
            self.last_save_time = now
            self.save_progress()

        # ======================
        # SKIP OP/ED AUTO-SEEK
        # ======================
        if self.skip_op_enabled and self.duration > 0:
            t = self.position

            # Get current episode's OP/ED timestamps
            get_anilibria_episode = self.anilibria_episode_select_op_end
            op_start = (get_anilibria_episode or {}).get("opening", {}).get("start") or 0
            op_end = (get_anilibria_episode or {}).get("opening", {}).get("stop") or 0

            ed_start = (get_anilibria_episode or {}).get("ending", {}).get("start") or 0
            ed_end   = (get_anilibria_episode or {}).get("ending", {}).get("stop") or 0

            # If currently skipping OP/ED, check if we've passed it
            if self.skipping_op_ed:
                if t > float(op_end) + 1 and t > float(ed_end) + 1:
                    self.skipping_op_ed = False
                return

            # Auto-skip opening
            if float(op_start) <= t <= float(op_end):
                self.player.seek(float(op_end) + 1, reference="absolute")
                self.skipping_op_ed = True
                return

            # Auto-skip ending
            if float(ed_start) <= t <= float(ed_end):
                self.player.seek(float(ed_end) + 1, reference="absolute")
                self.skipping_op_ed = True
                return


SHIKIMORI_TOKEN = os.getenv("SHIKIMORI_TOKEN")

async def run_oauth_flow():
    """Run OAuth authorization flow."""
    global SHIKIMORI_TOKEN
    logging.info("Starting OAuth flow...")

    authorization_url = await get_authorization_url()
    logging.info(f"Open this URL in browser for authorization: {authorization_url}")
    logging.info("Waiting for authorization code...")

    webbrowser.open(authorization_url)
    code = await get_authorization_code(timeout=600)

    if code:
        logging.info("Authorization code received")
        token_data = await get_access_token(code)
        
        if "access_token" in token_data:
            SHIKIMORI_TOKEN = token_data["access_token"]
            stored_refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in")
            
            logging.info(f"Access token received. Expires in: {expires_in} seconds")
            
            with open(f"{pathname}/.env", "r") as f:
                env_lines = f.readlines()
            
            token_updated = False
            refresh_updated = False
            
            for i, line in enumerate(env_lines):
                if line.startswith("SHIKIMORI_TOKEN="):
                    env_lines[i] = f"SHIKIMORI_TOKEN={SHIKIMORI_TOKEN}\n"
                    token_updated = True
                elif line.startswith("REFRESH_TOKEN="):
                    env_lines[i] = f"REFRESH_TOKEN={stored_refresh_token}\n" if stored_refresh_token else ""
                    refresh_updated = True
            
            if not token_updated:
                env_lines.append(f"SHIKIMORI_TOKEN={SHIKIMORI_TOKEN}\n")
            
            if stored_refresh_token and not refresh_updated:
                env_lines.append(f"REFRESH_TOKEN={stored_refresh_token}\n")
            
            with open(f"{pathname}/.env", "w") as f:
                f.writelines(env_lines)
            
            logging.info("Tokens saved to .env file")
            return token_data
        else:
            logging.error(f"Failed to get access token: {token_data}")
            return None
    else:
        logging.error("Authorization code not received")
        return None

async def refresh_token_task():
    """Background task for refreshing token at 11 PM."""
    stored_refresh_token = None
    if os.path.exists(f"{pathname}/.env"):
        with open(f"{pathname}/.env", "r") as f:
            for line in f:
                if line.startswith("REFRESH_TOKEN="):
                    stored_refresh_token = line.strip().split("=", 1)[1]
                    break

    while True:        
        if stored_refresh_token:
            if os.path.exists(f"{pathname}/.env"):
                with open(f"{pathname}/.env", "r") as f:
                    for line in f:
                        if line.startswith("SHIKIMORI_TOKEN="):
                            global SHIKIMORI_TOKEN
                            SHIKIMORI_TOKEN = line.strip().split("=", 1)[1]
                            break
            
            if SHIKIMORI_TOKEN and stored_refresh_token:
                try:
                    token_data = await refresh_access_token(stored_refresh_token)
                    if "access_token" in token_data:
                        SHIKIMORI_TOKEN = token_data["access_token"]
                        new_refresh_token = token_data.get("refresh_token", stored_refresh_token)
                        logging.info("Token refreshed successfully")
                        
                        with open(f"{pathname}/.env", "r") as f:
                            env_lines = f.readlines()
                        
                        token_updated = False
                        refresh_updated = False
                        
                        for i, line in enumerate(env_lines):
                            if line.startswith("SHIKIMORI_TOKEN="):
                                env_lines[i] = f"SHIKIMORI_TOKEN={SHIKIMORI_TOKEN}\n"
                                token_updated = True
                            elif line.startswith("REFRESH_TOKEN="):
                                env_lines[i] = f"REFRESH_TOKEN={new_refresh_token}\n"
                                refresh_updated = True
                        
                        if not token_updated:
                            env_lines.append(f"SHIKIMORI_TOKEN={SHIKIMORI_TOKEN}\n")
                        if not refresh_updated:
                            env_lines.append(f"REFRESH_TOKEN={new_refresh_token}\n")
                        
                        with open(f"{pathname}/.env", "w") as f:
                            f.writelines(env_lines)
                        
                        stored_refresh_token = new_refresh_token
                except Exception as e:
                    logging.error(f"Token refresh error: {e}")
        
        await asyncio.sleep(60)

async def main():
    """Main async function to start web server, oauth flow, and Qt app."""
    global SHIKIMORI_TOKEN
    loop = asyncio.get_event_loop()
    global_refresh_token = None

    runner = await start_oauth_server(port=3000)
    logging.info("OAuth callback server started on port 3000")

    if not SHIKIMORI_TOKEN:
        logging.info("No SHIKIMORI_TOKEN found, starting OAuth flow...")
        token_data = await run_oauth_flow()
        if not token_data:
            logging.error("OAuth flow failed")
            sys.exit(1)
    else:
        logging.info("Validating existing SHIKIMORI_TOKEN...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://shikimori.io/api/users/whoami",
                    headers={"Authorization": f"Bearer {SHIKIMORI_TOKEN}"}
                ) as resp:
                    if resp.status == 401:
                        logging.info("Token expired, attempting refresh...")
                        refresh_token = os.getenv("REFRESH_TOKEN")
                        if refresh_token:
                            try:
                                token_data = await refresh_access_token(refresh_token, session)
                                await refresh_and_update_tokens(refresh_token, session)
                                SHIKIMORI_TOKEN = token_data["access_token"]
                                logging.info("Token refreshed successfully at startup")
                            except (ValueError, aiohttp.ClientError) as e:
                                logging.warning(f"Refresh token invalid: {e}. Starting OAuth flow...")
                                token_data = await run_oauth_flow()
                                if not token_data:
                                    logging.error("OAuth flow failed")
                                    sys.exit(1)
                        else:
                            logging.warning("No REFRESH_TOKEN found, starting OAuth flow...")
                            token_data = await run_oauth_flow()
                            if not token_data:
                                logging.error("OAuth flow failed")
                                sys.exit(1)
                    elif resp.status != 200:
                        logging.warning(f"Token validation returned {resp.status}, proceeding anyway")
                    else:
                        logging.info("Token is valid")
        except Exception as e:
            logging.error(f"Token validation error: {e}")
            logging.warning("Proceeding with existing token")

    refresh_task = loop.create_task(refresh_token_task())

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(f"{pathname}/icon.png"))

    w = Player()
    app.installEventFilter(w)

    if len(sys.argv) > 1:
        paths = sys.argv[1:]
        try:
            w.open_folder(paths)
        except Exception as e:
            print(f"Error opening folder: {e}")
    else:
        if w.folder_history and w.folder_combo.count() > 0:
            w.folder_combo.setCurrentIndex(0)
            w.on_folder_selected(0)

    w.show()

    try:
        result = app.exec()
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass
        await runner.cleanup()
        sys.exit(result)
    except Exception as e:
        logging.error(f"Application error: {e}")
        refresh_task.cancel()
        await runner.cleanup()
        sys.exit(1)

if __name__ == "__main__":
    aiomisc.run(main())
