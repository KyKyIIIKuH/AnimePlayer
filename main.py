"""Thin bootstrap script for AnimePlayer."""
import sys
import os
import io

# Ensure the application path is in sys.path
from app.core.utils import pathname
sys.path.insert(0, pathname)

# Redirect stdout/stderr if they are None (prevents crashes in some environments)
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

# Qt environment variables for Wayland/X11 compatibility
os.environ["QT_WAYLAND_DISABLE_WINDOWDECORATION"] = "1"
os.environ["QT_QPA_PLATFORM"] = "xcb"

import aiomisc
from app.entrypoint import main

if __name__ == "__main__":
    aiomisc.run(main())
