#!/usr/bin/env python3
"""The demo. `python demo.py` runs the five questions end to end and shows the sources.

    python demo.py                          # all questions, terminal, with cell-level sources
    python demo.py --ask "..."              # one ad-hoc question  (this is the live-Q&A path)
    python demo.py --render markdown        # the same answers as a report body
    python demo.py --render slides          # the same answers as a deck structure
    python demo.py --explain                # print the schema card the planner is shown
    python demo.py --planner llm            # force the real model (needs ANTHROPIC_API_KEY)
    python demo.py --lineage "Sales!G158"   # what is in one cell, and what was done to it
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lineage import Store, answer_all                      # noqa: E402
from lineage.plan import get_planner                       # noqa: E402
from lineage.renderers import REGISTRY                     # noqa: E402

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "acme_operating_review.xlsx"


def load_questions(path: Path) -> list[str]:
    out = []
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln)
    return out


def show_cell(store: Store, ref: str):
    """`Sales!G158` -> the raw cell, the typed value, and any coercion that happened."""
    if "!" not in ref:
        print("give a reference like Sales!G158")
        return 2
    sheet_name, addr = ref.split("!", 1)
    sh = store.sheets.get(sheet_name)
    if sh is None:
        print(f"no sheet {sheet_name!r}; have {list(store.sheets)}")
        return 2
    for row, xr in zip(sh.rows, sh.excel_rows):
        for col, val in row.items():
            if any(c.addr.upper() == addr.upper() for c in val.prov.cells) and \
                    len(val.prov.cells) == 1:
                print(f"{ref}")
                print(f"  column      {col}")
                print(f"  excel row   {xr}")
                print(f"  raw         {val.raw if val.raw is not None else '(as stored)'}")
                print(f"  value       {val.value!r}")
                print(f"  note        {val.prov.note or '(no coercion)'}")
                return 0
    print(f"{ref} is not a data cell in the store "
          f"(it may be a header, a blank, or a subtotal row that was excluded)")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=str(DATA), help="workbook or CSV to load")
    ap.add_argument("--questions", default=str(ROOT / "questions.txt"))
    ap.add_argument("--ask", action="append", help="ask one question (repeatable)")
    ap.add_argument("--render", default="text", choices=sorted(REGISTRY))
    ap.add_argument("--planner", default="auto", choices=("auto", "llm", "cached"))
    ap.add_argument("--explain", action="store_true", help="print the planner's schema card")
    ap.add_argument("--lineage", help="inspect one cell, e.g. Sales!G158")
    ap.add_argument("--quality", action="store_true",
                    help="what the ingester found wrong with the workbook")
    ap.add_argument("--no-sources", action="store_true")
    ap.add_argument("--out", help="write the rendered output to a file")
    args = ap.parse_args()

    store = Store(args.file)

    if args.explain:
        print(store.schema_card())
        return 0
    if args.quality:
        from lineage.quality import report
        print(report(store))
        return 0
    if args.lineage:
        return show_cell(store, args.lineage)

    planner = get_planner(args.planner)
    questions = args.ask or load_questions(Path(args.questions))

    print(f"workbook : {Path(args.file).name}")
    print(f"planner  : {planner.name}"
          + ("   (no ANTHROPIC_API_KEY — replaying recorded plans)"
             if planner.name == "cached" else ""))
    print(f"questions: {len(questions)}")

    answers = answer_all(questions, store, planner)
    text = REGISTRY[args.render](
        answers,
        show_sources=not args.no_sources,
        title="ACME FY2025 operating review",
        source_file=Path(args.file).name,
    )
    if args.out:
        Path(args.out).write_text(text)
        print(f"\nwrote {args.out}")
    else:
        print(text)

    refused = sum(1 for a in answers if a.abstained)
    print(f"answered {len(answers) - refused}/{len(answers)} · refused {refused}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
