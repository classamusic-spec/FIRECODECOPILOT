#!/usr/bin/env python3
"""Fallback CLI for the Hermes skill if you wire it as a script-tool instead of MCP.
Calls the local Fire Code CoPilot REST API. Everything stays on your machine.

Usage:
  python fire_code.py "sprinkler requirement existing 3-story R-2" \
      --mode answer --context "occupancy R-2; existing; 3 stories"
"""
import argparse, json, sys, urllib.request

DEFAULT_URL = "http://localhost:8000/ask"   # FastAPI backend (see backend/app/main.py)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--mode", default="answer", choices=["answer", "retrieve"])
    p.add_argument("--context", default="")
    p.add_argument("--url", default=DEFAULT_URL)
    args = p.parse_args()

    payload = json.dumps({
        "question": args.question,
        "mode": args.mode,
        "building_context": args.context,
    }).encode("utf-8")

    req = urllib.request.Request(args.url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            print(r.read().decode("utf-8"))
        return 0
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
