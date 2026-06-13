"""State management utilities for playback and folder history."""
import os
import json
import logging
from app.core.config import STATE_FILE, FOLDER_HISTORY_FILE


def load_state() -> dict:
	"""Load playback state from JSON file."""
	if not os.path.exists(STATE_FILE):
		return {}
	try:
		with open(STATE_FILE, "r", encoding="utf-8") as f:
			return json.load(f)
	except Exception:
		return {}


def save_state(state: dict):
	"""Save playback state to JSON file."""
	if getattr(save_state, '_in_progress', False):
		return
	save_state._in_progress = True
	try:
		with open(STATE_FILE, "w", encoding="utf-8") as f:
			json.dump(state, f, ensure_ascii=False, indent=2)
	except Exception:
		pass
	finally:
		save_state._in_progress = False


def load_folder_history() -> list:
	"""Load folder history from JSON file."""
	if not os.path.exists(FOLDER_HISTORY_FILE):
		return []
	try:
		with open(FOLDER_HISTORY_FILE, "r", encoding="utf-8") as f:
			return json.load(f)
	except Exception:
		return []


def save_folder_history(history: list):
	"""Save folder history to JSON file."""
	if getattr(save_folder_history, '_in_progress', False):
		return
	save_folder_history._in_progress = True
	try:
		with open(FOLDER_HISTORY_FILE, "w", encoding="utf-8") as f:
			json.dump(history, f, ensure_ascii=False, indent=2)
	except Exception:
		pass
	finally:
		save_folder_history._in_progress = False


def add_to_folder_history(folder: str):
	"""Add folder to history, keeping only the last 5."""
	if getattr(add_to_folder_history, '_in_progress', False):
		return
	add_to_folder_history._in_progress = True
	try:
		history = load_folder_history()
		if folder in history:
			history.remove(folder)
		history.insert(0, folder)
		history = history[:5]
		save_folder_history(history)
	except Exception as e:
		logging.error(f"Error adding to folder history: {e}")
	finally:
		add_to_folder_history._in_progress = False
