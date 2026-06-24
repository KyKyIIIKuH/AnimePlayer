"""Episode parsing and sorting utilities."""
import os
import re


def get_episode(path: str) -> int:
	"""Extract episode number from filename using various patterns."""
	name = os.path.basename(path).lower()

	# Match bracketed numbers like [05] or _05_ — common in fansub releases.
	# This is the highest-priority pattern because it's the most explicit.
	match = re.search(r"[\[_](\d+)[\]\)]", name)
	if match:
		return int(match.group(1))

	# Match s01e12 pattern (season + episode)
	match = re.search(r"s\d+e(\d+)", name)
	if match:
		return int(match.group(1))

	# Match e12, ep12, episode12 — require word boundary before the prefix
	# so a mid-word letter (like the 'e' in "future") doesn't get consumed
	# as an episode marker.
	match = re.search(r"(?:^|[\s_])(?:episode|ep|e)\s*(\d+)", name)
	if match:
		return int(match.group(1))

	# Fallback: first standalone number
	match = re.search(r"(\d+)", name)
	if match:
		return int(match.group(1))

	return 1


def anime_sort_key(path: str) -> tuple | str:
	"""Generate sort key for anime files based on season and episode numbers."""
	name = os.path.basename(path).lower()

	# s01e12 pattern (season + episode)
	match = re.search(r"s(\d+)e(\d+)", name)
	if match:
		return (int(match.group(1)), int(match.group(2)))

	# Bracketed numbers like [05] — high-confidence episode with no season
	match = re.search(r"[\[_](\d+)[\]\)]", name)
	if match:
		return (0, int(match.group(1)))

	# e12, ep12, episode12 — require word boundary before prefix
	match = re.search(r"(?:^|[\s_])(?:episode|ep|e)\s*(\d+)", name)
	if match:
		return (0, int(match.group(1)))

	# Fallback: first standalone number
	match = re.search(r"(\d+)", name)
	if match:
		return (0, int(match.group(1)))

	return name
