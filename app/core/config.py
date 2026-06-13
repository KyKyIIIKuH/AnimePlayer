"""Application configuration and constants."""
from app.core.utils import pathname

# File to store playback state (watched position, skip settings)
STATE_FILE = f"{pathname}/playback_state.json"

# File to store folder history
FOLDER_HISTORY_FILE = f"{pathname}/folder_history.json"

# Shikimori API base URL
SHIKIMORI_BASE_URL = "https://animeplayer.kykyiiikuh.xyz"
