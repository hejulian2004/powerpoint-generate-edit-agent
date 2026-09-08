"""PPT-Agent-Studio Launch Script."""

import sys
import os
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run PPT-Agent-Studio Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    # Check if frontend is built
    dist_dir = Path(__file__).resolve().parent / "frontend" / "dist"
    if not dist_dir.exists():
        print("[Notice] Frontend dist directory not found.")
        print("         To build production frontend: cd frontend && npm run build")
        print("         To run frontend dev server:   cd frontend && npm run dev (runs on http://localhost:5173)")
    else:
        print(f"[Ready] Production frontend is built and mounted at http://{args.host}:{args.port}")

    import uvicorn
    print(f">> Starting PPT-Agent-Studio on http://{args.host}:{args.port} ...")
    uvicorn.run("backend.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
