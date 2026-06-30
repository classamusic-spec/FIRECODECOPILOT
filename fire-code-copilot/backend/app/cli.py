"""Terminal chat — the fastest way to use Fire Code CoPilot, no frontend or server needed.

    python -m app.cli

Type a question; it retrieves from your code books, reranks, asks your LOCAL model, validates
citations, and prints the answer with sources. Type 'sources' to toggle showing full source
text, 'cycle' for adopted-edition status, or 'quit' to exit.
"""
from __future__ import annotations
import sys
from .settings import settings
from .agent import ask
from .cycles import active_cycle_block, cycle_reminder


def _print_sources(sources: list[dict]):
    for s in sources:
        m = s["metadata"]
        tag = " [CT-AMENDMENT]" if m.get("is_amendment") else ""
        print(f"  • {m.get('book')} {m.get('edition')} §{m.get('section')} p.{m.get('page')}{tag}")


def main() -> int:
    print(f"🔥 Fire Code CoPilot — {settings.jurisdiction}")
    print(f"   model: {settings.local_model} via {settings.local_base_url}")
    warn = cycle_reminder()
    if warn:
        print(f"   ⚠️  {warn}")
    print("   ask a question (or 'cycle', 'quit')\n")

    show_sources = True
    while True:
        try:
            q = input("› ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not q:
            continue
        if q.lower() in ("quit", "exit"):
            return 0
        if q.lower() == "sources":
            show_sources = not show_sources
            print(f"  (show sources: {show_sources})")
            continue
        if q.lower() == "cycle":
            print(active_cycle_block())
            continue

        try:
            res = ask(q, active_cycle_block=active_cycle_block())
        except Exception as e:
            print(f"  error: {e}\n  (is your local model server running? did you run "
                  f"`python -m app.ingest`?)\n")
            continue

        print()
        print(res.answer or "(retrieve mode — no answer composed)")
        if not res.citations_ok:
            print(f"\n  ⚠️ unverified citations: {', '.join(res.unverified)}")
        if show_sources and res.sources:
            print("\n  sources:")
            _print_sources(res.sources)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
