"""Main application window for anime video playback — VLC-style UI."""
import os
import time
import logging
import json
from PyQt6.QtWidgets import (
	QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy,
	QPushButton, QFileDialog, QSlider, QLabel, QCheckBox, QComboBox,
	QMenuBar, QMenu, QMainWindow, QStatusBar, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, QSignalBlocker, QEvent
from PyQt6.QtGui import QIcon, QAction
import mpv

from app.core.utils import pathname
from app.core import auth
from app.utils.state_manager import (
	load_state, save_state, load_folder_history,
	save_folder_history, add_to_folder_history
)
from app.utils.episode_parser import get_episode, anime_sort_key
from app.workers.user_info import UserInfoWorker
from app.workers.anime_search import AnimeSearchWorker
from app.workers.user_rate import UserRateEnsureWorker, UserRateWorker


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
		QMessageBox.about(
			self, "About Anime Player",
			"Anime Player v1.2\n\n"
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
		if not (self.anime_id and self.user_id):
			return

		# Only increment if episode has progressed
		if self.current_episode <= self.last_sent_episode:
			return

		self.last_sent_episode = self.current_episode

		if self.user_rate:
			self._send_user_rate_increment()
		else:
			self._ensure_user_rate_first()

	def _ensure_user_rate_first(self):
		"""Check if user rate exists, create if not, then increment."""
		self.ensure_rate_worker = UserRateEnsureWorker(
			self.user_id,
			self.anime_id,
			auth.SHIKIMORI_TOKEN
		)
		self._workers.add(self.ensure_rate_worker)
		self.ensure_rate_worker.finished.connect(self.ensure_rate_worker.deleteLater)
		self.ensure_rate_worker.finished.connect(lambda w=self.ensure_rate_worker: self._workers.discard(w))
		self.ensure_rate_worker.result.connect(self.on_user_rate_ensured)
		self.ensure_rate_worker.start()

	def on_user_rate_ensured(self, data):
		"""Handle response from ensuring user rate."""
		if "error" in data:
			logging.error(f"Failed to ensure user rate: {data.get('error')}")
			return

		self.user_rate = data.get("id")
		logging.info(f"User rate ensured, ID: {self.user_rate}")
		self._send_user_rate_increment()

	def _send_user_rate_increment(self):
		"""Send increment request to Shikimori."""
		self.rate_worker = UserRateWorker(
			self.user_id,
			self.anime_id,
			self.user_rate,
			self.current_episode,
			auth.SHIKIMORI_TOKEN
		)
		self._workers.add(self.rate_worker)
		self.rate_worker.finished.connect(self.rate_worker.deleteLater)
		self.rate_worker.finished.connect(lambda w=self.rate_worker: self._workers.discard(w))
		self.rate_worker.result.connect(self.on_user_rate_updated)
		self.rate_worker.start()

	def on_user_rate_updated(self, data):
		"""Handle user rate update response."""
		if "error" in data:
			logging.error(f"User rate update error: {data.get('error')}")
		else:
			logging.info(f"User rate updated successfully")

	def load_user(self):
		"""Fetch and display current user information."""
		if not auth.SHIKIMORI_TOKEN:
			self.user_label.setText("No SHIKIMORI_TOKEN")
			return

		self.worker = UserInfoWorker(auth.SHIKIMORI_TOKEN)
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
		import re
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
		add_to_folder_history(folder)

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
