"""Root entry point for Job Crawler."""

import sys
from pathlib import Path

# Ensure src is on sys.path
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from crawler.cli import main

if __name__ == "__main__":
    main()
