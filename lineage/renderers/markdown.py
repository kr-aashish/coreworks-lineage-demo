"""The report renderer — a PDF is this plus one pandoc call, and nothing else.

    markdown.render(answers) -> a full report body
    a PDF = `pandoc report.md -o report.pdf`, or weasyprint over the HTML.

⇒ The reason the PDF story is short is that this file computes NOTHING. It reads the same
  Answer objects the terminal reads, and the appendix is the provenance those Answers were
  already carrying. That is the seam working, demonstrated rather than promised.
"""
from __future__ import annotations

from ..model import Answer


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


def render(answers: list[Answer], title: str = "Data analysis report",
           source_file: str = "", **_) -> str:
    out = [f"# {title}", ""]
    if source_file:
        out += [f"Source workbook: `{source_file}`", ""]
    out += ["Every figure below is followed by the spreadsheet cells it was computed from. "
            "Questions the workbook cannot answer are marked as refused rather than estimated.",
            "", "---", ""]

    for i, a in enumerate(answers, start=1):
        out.append(f"## {i}. {a.question}")
        out.append("")
        if a.abstained:
            out += ["> **Not answerable from this file.**", ">",
                    f"> {a.abstain_reason}", ""]
            continue

        out += [a.prose, ""]
        res = a.result
        out.append("| " + " | ".join(res.columns) + " |")
        out.append("|" + "|".join("---" for _ in res.columns) + "|")
        for row in res.rows[:25]:
            out.append("| " + " | ".join(_fmt(c.value) for c in row) + " |")
        if len(res.rows) > 25:
            out.append(f"| … {len(res.rows) - 25} more rows | " +
                       " | ".join("" for _ in res.columns[1:]) + " |")
        out.append("")

        out.append("<details><summary>Where these numbers came from</summary>")
        out.append("")
        for r_i, row in enumerate(res.rows[:25]):
            label = _fmt(row[0].value)
            for col, cell in zip(res.columns, row):
                if not cell.provenance.cells:
                    continue
                cells = sorted(cell.provenance.cells)
                shown = ", ".join(f"`{c}`" for c in cells[:8])
                more = f" … and {len(cells) - 8} more cells" if len(cells) > 8 else ""
                note = f" — {cell.provenance.note}" if cell.provenance.note else ""
                out.append(f"- **{label} · {col}** ← {shown}{more}{note}")
        out.append("")
        out.append(f"Computed as: {res.computed}")
        out.append("")
        out.append("</details>")
        out.append("")
    return "\n".join(out)
