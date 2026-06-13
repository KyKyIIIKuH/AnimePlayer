"""Worker for fetching user information from Shikimori API."""
import asyncio
import aiohttp
from PyQt6.QtCore import QThread, pyqtSignal as Signal
from app.core import auth
from app.core.oauth_manager import check_and_refresh_on_401


class UserInfoWorker(QThread):
	"""Background thread to fetch user information from Shikimori API."""
	result = Signal(dict)

	def __init__(self, token: str):
		super().__init__()
		self.token = token
		self.token_updated = False
		self.new_token = None

	async def _fetch_user_info(self):
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
						auth.SHIKIMORI_TOKEN = new_token_data["access_token"]
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
