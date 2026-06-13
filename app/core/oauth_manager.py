"""OAuth token management for Shikimori API."""
import os
import sys
import asyncio
import aiohttp
import logging
from datetime import datetime, time
from dotenv import load_dotenv
from app.core.utils import pathname
from app.core.config import SHIKIMORI_BASE_URL

# Ensure environment variables are loaded
load_dotenv(f"{pathname}/.env")

print(f"Original AppImage directory2: {pathname}")


async def get_access_token(authorization_code):
	"""Exchange authorization code for access token."""
	url = f"{SHIKIMORI_BASE_URL}/oauth/token"

	data = {
		"code": authorization_code,
	}

	headers = {
		"User-Agent": "Anime MPV Player",
	}

	async with aiohttp.ClientSession() as session:
		async with session.post(url, data=data, headers=headers) as response:
			result = await response.json()
			return result


async def refresh_access_token(refresh_token=None, session=None):
	"""Refresh access token using refresh token.

	Args:
		refresh_token: Optional refresh token. If None, reads from .env
		session: Optional aiohttp ClientSession. If None, creates new one

	Returns:
		dict: Token data with access_token, refresh_token, expires_in

	Raises:
		aiohttp.ClientError: Network errors
		ValueError: If refresh token is invalid or missing
	"""
	if refresh_token is None:
		refresh_token = os.getenv("REFRESH_TOKEN")
		if not refresh_token:
			raise ValueError("No refresh token provided and none found in .env")

	url = f"{SHIKIMORI_BASE_URL}/oauth/refresh_token"

	data = {
		"refresh_token": refresh_token,
	}

	headers = {
		"User-Agent": "Anime MPV Player",
	}

	use_own_session = session is None
	if use_own_session:
		session = aiohttp.ClientSession()

	try:
		async with session.post(url, data=data, headers=headers) as response:
			result = await response.json()

			if response.status == 401:
				error = result.get("error", "")
				error_desc = result.get("error_description", "")

				if error == "invalid_token" and "The access token is invalid" in error_desc:
					raise ValueError("The access token is invalid - refresh token may be expired or revoked")
				elif error == "invalid_grant":
					raise ValueError("The refresh token is invalid or has been revoked")

			if response.status not in (200, 201):
				raise aiohttp.ClientError(f"Unexpected status {response.status}: {result}")

			return result
	finally:
		if use_own_session:
			await session.close()


async def refresh_and_update_tokens(refresh_token=None, session=None):
	"""Refresh tokens and update .env file with new values.

	Args:
		refresh_token: Optional refresh token. If None, reads from .env
		session: Optional aiohttp ClientSession. If None, creates new one

	Returns:
		dict: Token data with access_token, refresh_token, expires_in, token_type

	Raises:
		aiohttp.ClientError: Network errors
		ValueError: If refresh token is invalid or missing
	"""
	if refresh_token is None:
		refresh_token = os.getenv("REFRESH_TOKEN")
		if not refresh_token:
			raise ValueError("No refresh token provided and none found in .env")

	token_data = await refresh_access_token(refresh_token, session)

	new_access_token = token_data.get("access_token")
	new_refresh_token = token_data.get("refresh_token", refresh_token)

	env_path = f"{pathname}/.env"

	if not os.path.exists(env_path):
		raise FileNotFoundError(f".env file not found at {env_path}")

	with open(env_path, "r", encoding="utf-8") as f:
		lines = f.readlines()

	token_updated = False
	refresh_updated = False

	for i, line in enumerate(lines):
		if line.startswith("SHIKIMORI_TOKEN="):
			lines[i] = f"SHIKIMORI_TOKEN={new_access_token}\n"
			token_updated = True
		elif line.startswith("REFRESH_TOKEN="):
			lines[i] = f"REFRESH_TOKEN={new_refresh_token}\n"
			refresh_updated = True

	if not token_updated:
		lines.append(f"SHIKIMORI_TOKEN={new_access_token}\n")
	if not refresh_updated:
		lines.append(f"REFRESH_TOKEN={new_refresh_token}\n")

	with open(env_path, "w", encoding="utf-8") as f:
		f.writelines(lines)

	return token_data


def is_token_expired_error(response_data):
	"""Check if response indicates token expiration.

	Args:
		response_data: dict containing API response

	Returns:
		bool: True if token is expired, False otherwise
	"""
	if not isinstance(response_data, dict):
		return False

	error = response_data.get("error")
	error_description = response_data.get("error_description")

	if error == "invalid_token" and error_description:
		return "The access token is invalid" in error_description

	return False


async def get_authorization_url():
	"""Generate Shikimori authorization URL."""
	url = f"{SHIKIMORI_BASE_URL}/oauth/authorize"
	return url


def is_time_to_run(target_hour=23):
	"""Check if current time has reached target hour."""
	now = datetime.now()
	target_time = time(target_hour, 0, 0)
	current_time = now.time()
	return current_time >= target_time


async def schedule_token_refresh(refresh_callback, check_interval=60):
	"""Schedule token refresh at 11 PM daily."""
	while True:
		if is_time_to_run(23):
			try:
				await refresh_callback()
			except Exception as e:
				logging.info(f"Token refresh error: {e}")

		await asyncio.sleep(check_interval)


async def check_and_refresh_on_401(response, refresh_token=None):
	"""Check if response indicates expired token and auto-refresh.

	Args:
		response: aiohttp Response object
		refresh_token: Optional refresh token. If None, reads from .env

	Returns:
		tuple: (bool indicating if refresh happened, new token data if refreshed)

	Raises:
		aiohttp.ClientResponseError: If refresh fails or token is invalid
	"""
	if response.status != 401:
		return False, None

	try:
		response_data = await response.json()
	except Exception:
		return False, None

	if not is_token_expired_error(response_data):
		return False, None

	try:
		new_token_data = await refresh_and_update_tokens(refresh_token)
		return True, new_token_data
	except Exception as e:
		raise aiohttp.ClientResponseError(
			request_info=response.request_info,
			history=response.history,
			status=response.status,
			message=f"Token expired and refresh failed: {e}",
			headers=response.headers
		)
