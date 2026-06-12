import os, sys
from core.utils import pathname
sys.path.insert(0, pathname)  # Добавляем путь к корневой папке в sys.path
import asyncio
from aiohttp import web
from dotenv import load_dotenv

print(f"Original AppImage directory3: {pathname}")

load_dotenv(f"{pathname}/.env")

authorization_code = None
oauth_callback_future = None

async def handle_oauth_callback(request):
    """Handle OAuth callback from Shikimori."""
    global authorization_code, oauth_callback_future
    
    code = request.query.get("code")
    
    if code:
        authorization_code = code
        if oauth_callback_future and not oauth_callback_future.done():
            oauth_callback_future.set_result(code)
        
        return web.Response(
            text="Authorization successful! You can close this window."
        )
    
    return web.Response(text="Authorization failed", status=400)


async def get_authorization_code(timeout=300):
    """Wait for authorization code with timeout."""
    global oauth_callback_future
    
    loop = asyncio.get_running_loop()
    oauth_callback_future = loop.create_future()
    
    try:
        code = await asyncio.wait_for(oauth_callback_future, timeout=timeout)
        return code
    except asyncio.TimeoutError:
        return None


async def start_oauth_server(host="localhost", port=3000):
    """Start the web server for OAuth callback."""
    app = web.Application()
    app.router.add_get("/oauth/callback", handle_oauth_callback)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    return runner
