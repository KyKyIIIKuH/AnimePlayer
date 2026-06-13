"""Workers for managing user rates on Shikimori."""
import asyncio
import aiohttp
import logging
from PyQt6.QtCore import QThread, pyqtSignal as Signal
from app.core import auth
from app.core.oauth_manager import check_and_refresh_on_401


class UserRateEnsureWorker(QThread):
	"""Background thread to check and create user rate on Shikimori if not exists."""
	result = Signal(dict)

	def __init__(self, user_id: int, anime_id: int, token: str):
		super().__init__()
		self.user_id = user_id
		self.anime_id = anime_id
		self.token = token

	async def _ensure_user_rate(self):
		async with aiohttp.ClientSession() as session:
			headers = {
				"User-Agent": "AnimePlayer",
				"Authorization": f"Bearer {self.token or auth.SHIKIMORI_TOKEN}",
				"Content-Type": "application/json"
			}

			# 1. Проверяем наличие записи
			url_check = f"https://shikimori.io/api/v2/user_rates?user_id={self.user_id}&target_id={self.anime_id}&target_type=Anime"

			async with session.get(url_check, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
				if response.status == 401:
					is_refreshed, new_token_data = await check_and_refresh_on_401(response, None)
					if is_refreshed and new_token_data:
						self.token = new_token_data["access_token"]
						auth.SHIKIMORI_TOKEN = new_token_data["access_token"]
						return await self._ensure_user_rate()
					else:
						return {"error": "401 Unauthorized - token invalid or expired"}
				response.raise_for_status()
				data = await response.json()

			# Если запись уже есть, возвращаем её
			if data and len(data) > 0:
				return data[0]

			# 2. Если записи нет, создаем её
			url_create = "https://shikimori.io/api/v2/user_rates"
			payload = {
				"user_rate": {
					"status": "planned",
					"target_id": self.anime_id,
					"target_type": "Anime",
					"user_id": self.user_id
				}
			}

			async with session.post(url_create, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
				if response.status == 401:
					is_refreshed, new_token_data = await check_and_refresh_on_401(response, None)
					if is_refreshed and new_token_data:
						self.token = new_token_data["access_token"]
						auth.SHIKIMORI_TOKEN = new_token_data["access_token"]
						return await self._ensure_user_rate()
					else:
						return {"error": "401 Unauthorized - token invalid or expired"}
				response.raise_for_status()
				return await response.json()

	def run(self):
		try:
			data = asyncio.run(self._ensure_user_rate())
			self.result.emit(data)
		except Exception as e:
			self.result.emit({"error": str(e)})


class UserRateWorker(QThread):
	"""Background thread to increment user's anime progress on Shikimori."""
	result = Signal(dict)

	def __init__(self, user_id: int, anime_id: int, id_rate: int, episode: int, token: str):
		super().__init__()
		self.user_id = user_id
		self.anime_id = anime_id
		self.id_rate = id_rate
		self.episode = episode
		self.token = token

	async def _update_user_rate(self):
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
						auth.SHIKIMORI_TOKEN = new_token_data["access_token"]
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
						auth.SHIKIMORI_TOKEN = new_token_data["access_token"]
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
			logging.info(f"USER_RATE RESPONSE: {data}")
			self.result.emit(data)

		except Exception as e:
			logging.error(f"USER_RATE ERROR: {e}")
			self.result.emit({"error": str(e)})
