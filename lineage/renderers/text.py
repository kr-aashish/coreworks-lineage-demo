"""The terminal renderer — what the demo shows on screen.

⭐ THE PROSE IS TEMPLATED, NOT GENERATED, AND THAT IS A DELIBERATE NARROWING.
    A second LLM call could write a nicer sentence. It would also be a second place a claim can
    be invented, and verify.py's gate 4 only constrains NUMBERS -- it cannot catch "North grew
    because of the launch", which carries no numeral and is not in the data.
    ⇒ So the sentence is assembled from the plan and the result. Every noun in it is a column
      name the plan named, and every figure in it came out of the executor. The system is
      slightly less charming and it cannot say anything the data did not say.
    ⚠️ The LLM is NOT removed from the product -- it does the hard half, which is understanding
      the question. It is removed from the half where being wrong is undetectable.
"""
from __future__ import annotations

from ..model import Answer

BOLD, DIM, RED, GREEN, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m")


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        if abs(v - round(v)) < 1e-9 and abs(v) < 1e15:
            return f"{int(round(v)):,}"
        return f"{v:,.2f}"
    return str(v)


def _table(answer: Answer, show_sources: bool, max_rows: int) -> list[str]:
    res = answer.result
    widths = [len(c) for c in res.columns]
    body = []
    for row in res.rows[:max_rows]:
        vals = [_fmt(c.value) for c in row]
        widths = [max(w, len(v)) for w, v in zip(widths, vals)]
        body.append((vals, row))

    out = ["  " + "  ".join(c.ljust(w) for c, w in zip(res.columns, widths)),
           "  " + "  ".join("-" * w for w in widths)]
    for vals, row in body:
        out.append("  " + "  ".join(v.ljust(w) for v, w in zip(vals, widths)))
        if show_sources:
            for col, cell in zip(res.columns, row):
                if not cell.provenance.cells:
                    continue
                n = len(cell.provenance.cells)
                head = ", ".join(str(c) for c in sorted(cell.provenance.cells)[:6])
                more = f" … +{n - 6} more cells" if n > 6 else ""
                note = f"  [{cell.provenance.note}]" if cell.provenance.note else ""
                out.append(f"      {DIM}{col} ← {head}{more}{note}{RESET}")
    if len(res.rows) > max_rows:
        out.append(f"  {DIM}… {len(res.rows) - max_rows} more row(s){RESET}")
    return out


def render(answers: list[Answer], show_sources: bool = True, show_trail: bool = True,
           max_rows: int = 12, **_) -> str:
    out: list[str] = []
    for i, a in enumerate(answers, start=1):
        out.append("")
        out.append(f"{BOLD}Q{i}. {a.question}{RESET}")
        out.append("")

        if a.abstained:
            out.append(f"  {RED}I can't answer this from the file.{RESET}")
            out.append(f"  {a.abstain_reason}")
        else:
            out.append(f"  {GREEN}{a.prose}{RESET}")
            out.append("")
            out.extend(_table(a, show_sources, max_rows))

        if show_trail:
            out.append("")
            out.append(f"  {DIM}gates:{RESET}")
            for t in a.trail:
                colour = GREEN if t.startswith("PASS") else RED
                out.append(f"    {colour}{t}{RESET}")
            if a.result is not None and a.result.computed:
                out.append(f"    {DIM}computed: {a.result.computed}{RESET}")
        out.append("")
        out.append(DIM + "─" * 78 + RESET)
    return "\n".join(out)
