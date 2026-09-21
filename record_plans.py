#!/usr/bin/env python3
"""Re-record every question's plan through the live Anthropic API.

    ANTHROPIC_API_KEY=... python record_plans.py            # overwrite plans/
    ANTHROPIC_API_KEY=... python record_plans.py --diff     # show what changed, write nothing

⭐ Why this is a script and not a note: the shipped plans were written by a model but not
   through the API on this machine (see lineage/plan.py). That is a provenance gap, so the
   repo carries the one command that closes it rather than a sentence asking you to trust it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo import DATA, load_questions                       # noqa: E402
from lineage import Store                                   # noqa: E402
from lineage.execute import PlanError, validate             # noqa: E402
from lineage.plan import PLAN_DIR, LLMPlanner, _slug        # noqa: E402

ROOT = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", action="store_true", help="compare, do not write")
    ap.add_argument("--file", default=str(DATA))
    args = ap.parse_args()

    store = Store(args.file)
    planner = LLMPlanner(record=not args.diff)
    changed = 0
    for q in load_questions(ROOT / "questions.txt"):
        old_path = PLAN_DIR / f"{_slug(q)}.json"
        old = json.loads(old_path.read_text())["plan"] if old_path.exists() else None
        plan = planner.plan(q, store)
        status = "ok"
        if not plan.abstain:
            try:
                validate(plan, store)
            except PlanError as e:
                status = f"DOES NOT BIND — {e}"
        new = plan.to_dict()
        same = old == new
        changed += 0 if same else 1
        print(f"{'=' if same else '≠'} {q}")
        print(f"    {status}")
        if not same and old is not None:
            print(f"    was: {json.dumps(old, sort_keys=True)[:160]}")
            print(f"    now: {json.dumps(new, sort_keys=True)[:160]}")
    print(f"\n{changed} plan(s) differ from what is committed"
          + ("  (nothing written — --diff)" if args.diff else "  (plans/ updated)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
