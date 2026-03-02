"""PyInstaller runtime hook — runs before the main script.

Sets environment variables so bundled data files are found correctly
inside the temporary _MEIPASS extraction folder.
"""

import os
import sys

if getattr(sys, "frozen", False):
    _meipass = sys._MEIPASS  # type: ignore[attr-defined]

    # tiktoken: point cache dir at bundled encodings
    os.environ["TIKTOKEN_CACHE_DIR"] = os.path.join(_meipass, "tiktoken_cache")

    # Ensure the project root is on sys.path so `from src.xxx` imports work
    if _meipass not in sys.path:
        sys.path.insert(0, _meipass)
