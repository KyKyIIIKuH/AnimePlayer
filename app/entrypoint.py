"""Application entrypoint and OAuth flow orchestration."""
import os
import sys
import logging
import asyncio
import aiohttp
import webbrowser

from app.core.utils import pathname
from app.core import auth
from app.core.oauth_server import start_oauth_server, get_authorization_code
from app.core.oauth_manager import (
    get_access_token,
    refresh_access_token,
    refresh_and_update_tokens,
    get_authorization_url,
)
from app.ui.player import Player

logging.basicConfig(level=logging.INFO)


async def run_oauth_flow():
    """Run OAuth authorization flow."""
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
            auth.SHIKIMORI_TOKEN = token_data["access_token"]
            stored_refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in")

            logging.info(f"Access token received. Expires in: {expires_in} seconds")

            env_path = f"{pathname}/.env"
            with open(env_path, "r") as f:
                env_lines = f.readlines()

            token_updated = False
            refresh_updated = False

            for i, line in enumerate(env_lines):
                if line.startswith("SHIKIMORI_TOKEN="):
                    env_lines[i] = f"SHIKIMORI_TOKEN={auth.SHIKIMORI_TOKEN}\n"
                    token_updated = True
                elif line.startswith("REFRESH_TOKEN="):
                    env_lines[i] = f"REFRESH_TOKEN={stored_refresh_token}\n" if stored_refresh_token else ""
                    refresh_updated = True

            if not token_updated:
                env_lines.append(f"SHIKIMORI_TOKEN={auth.SHIKIMORI_TOKEN}\n")

            if stored_refresh_token and not refresh_updated:
                env_lines.append(f"REFRESH_TOKEN={stored_refresh_token}\n")

            with open(env_path, "w") as f:
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
    env_path = f"{pathname}/.env"
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("REFRESH_TOKEN="):
                    stored_refresh_token = line.strip().split("=", 1)[1]
                    break

    while True:
        if stored_refresh_token:
            if os.path.exists(env_path):
                with open(env_path, "r") as f:
                    for line in f:
                        if line.startswith("SHIKIMORI_TOKEN="):
                            auth.SHIKIMORI_TOKEN = line.strip().split("=", 1)[1]
                            break

            if auth.SHIKIMORI_TOKEN and stored_refresh_token:
                try:
                    token_data = await refresh_access_token(stored_refresh_token)
                    if "access_token" in token_data:
                        auth.SHIKIMORI_TOKEN = token_data["access_token"]
                        new_refresh_token = token_data.get("refresh_token", stored_refresh_token)
                        logging.info("Token refreshed successfully")

                        await refresh_and_update_tokens(stored_refresh_token)
                        stored_refresh_token = new_refresh_token
                except Exception as e:
                    logging.error(f"Token refresh error: {e}")

        await asyncio.sleep(60)


async def main():
    """Main async function to start web server, oauth flow, and Qt app."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon

    loop = asyncio.get_event_loop()

    runner = await start_oauth_server(port=3000)
    logging.info("OAuth callback server started on port 3000")

    if not auth.SHIKIMORI_TOKEN:
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
                    headers={"Authorization": f"Bearer {auth.SHIKIMORI_TOKEN}"}
                ) as resp:
                    if resp.status == 401:
                        logging.info("Token expired, attempting refresh...")
                        refresh_token = os.getenv("REFRESH_TOKEN")
                        if refresh_token:
                            try:
                                token_data = await refresh_access_token(refresh_token, session)
                                await refresh_and_update_tokens(refresh_token, session)
                                auth.SHIKIMORI_TOKEN = token_data["access_token"]
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
