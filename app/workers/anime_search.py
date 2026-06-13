"""Worker for searching anime and fetching episode opening/endings data."""
import asyncio
import aiohttp
from PyQt6.QtCore import QThread, pyqtSignal as Signal
from app.core import auth
from app.core.oauth_manager import check_and_refresh_on_401


class AnimeSearchWorker(QThread):
	"""Background thread to search for anime and fetch episode opening/endings data."""
	result = Signal(dict)

	def __init__(self, query: str):
		super().__init__()
		self.query = query

	async def _search_anime(self):
		async with aiohttp.ClientSession() as session:
			headers_auth = {
				"User-Agent": "AnimePlayer",
				"Authorization": f"Bearer {auth.SHIKIMORI_TOKEN}",
			}
			headers_no_auth = {
				"User-Agent": "AnimePlayer",
			}

			headers = headers_auth if auth.SHIKIMORI_TOKEN else headers_no_auth

			async with session.get(
				"https://shikimori.io/api/animes",
				params={"search": self.query},
				headers=headers,
				timeout=aiohttp.ClientTimeout(total=10)
			) as response:
				if response.status == 401:
					is_refreshed, new_token_data = await check_and_refresh_on_401(response, None)
					if is_refreshed and new_token_data:
						auth.SHIKIMORI_TOKEN = new_token_data["access_token"]
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
						auth.SHIKIMORI_TOKEN = new_token_data["access_token"]
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
