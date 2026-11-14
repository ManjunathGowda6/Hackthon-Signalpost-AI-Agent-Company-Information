#!/usr/bin/env python3
"""Signalpost Web Runner — Starts the Signalpost Explorer & Intelligence Web App."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from signalpost.web.app import create_app


def main():
    parser = argparse.ArgumentParser(description="Start Signalpost Explorer web server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5001, help="Port to listen on (default: 5001)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    app = create_app()
    print("=" * 70)
    print("  🚀 SIGNALPOST EXPLORER — NORWEGIAN COMPANY INTELLIGENCE")
    print(f"  Web UI:       http://{args.host}:{args.port}/")
    print(f"  Explorer:     http://{args.host}:{args.port}/explorer")
    print(f"  Prototype:    http://{args.host}:{args.port}/prototype")
    print(f"  Chat Copilot: http://{args.host}:{args.port}/chat")
    print("=" * 70)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
