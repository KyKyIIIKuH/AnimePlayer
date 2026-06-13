"""Episode parsing and sorting utilities."""
import os
import re


def get_episode(path: str) -> int:
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


def anime_sort_key(path: str) -> tuple | str:
	"""Generate sort key for anime files based on season and episode numbers."""
	name = os.path.basename(path).lower()
	match = re.search(r"(s(\d+))?e?(\d+)", name)
	if match:
		# Extract season (default 0) and episode (default 0)
		season = int(match.group(2)) if match.group(2) else 0
		episode = int(match.group(3)) if match.group(3) else 0
		return (season, episode)
	return name
