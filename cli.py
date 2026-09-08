"""Root CLI entrypoint."""

import sys
import os

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pptx_agent_converter.cli import main

if __name__ == "__main__":
    sys.exit(main())
