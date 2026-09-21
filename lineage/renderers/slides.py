"""The deck renderer — the full slide STRUCTURE, stopping one call short of python-pptx.

⭐ WHY IT STOPS THERE, ON PURPOSE
    The assignment says the slide generator does not have to be built, but that it should be
    believable that building it is not a rewrite. A paragraph asserting that is worth nothing.
    So this file does the part that actually carries the risk -- deciding what a slide IS for
    an Answer, where the table goes, what the sources footnote says, what happens to a REFUSED
    answer -- and leaves only the mechanical part undone.

    `build(answers) -> list[Slide]` is complete and tested. `render()` prints those Slides as
    text so the deck is inspectable today. The remaining work is one function:

        for s in build(answers):
            layout = prs.slide_layouts[1]
            slide  = prs.slides.add_slide(layout)
            slide.shapes.title.text = s.title
            ...                                   # bullets, a table, the footnote

    ⇒ ~40 lines of python-pptx against a structure that already exists, with no decisions left
      in it. That is the claim, and it is checkable by reading this file rather than by
      trusting the README.

⛔ THE REFUSAL GETS A SLIDE TOO, and that is the design point most decks would drop. A question
   the data could not answer is a finding about the dataset, not an empty space -- silently
   omitting it is how a deck starts lying by selection rather than by arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..model import Answer


@dataclass
class Slide:
    title: str
    subtitle: str = ""
    bullets: list[str] = field(default_factory=list)
    table_columns: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)
    footnote: str = ""
    kind: str = "finding"          # finding | refusal | title | appendix


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


def _sources_footnote(answer: Answer, limit: int = 5) -> str:
    """The provenance, compressed to something that fits under a chart.

    Ranges rather than addresses: 47 cell references do not fit on a slide, and
    "Sales!I2:I601" is the honest compression of a contiguous column read.
    """
    cells = sorted({c for row in answer.result.rows for cell in row
                    for c in cell.provenance.cells})
    if not cells:
        return ""
    by_col: dict[tuple[str, int], tuple[str, list[int]]] = {}
    for c in cells:
        # ⚠️ The letter must come from THIS cell's own column. Looking it up by row instead
        # returned whichever column happened to share the row, so a four-column citation
        # rendered as the same range four times — wrong, and wrong in a way that still looks
        # like a citation, which is the worst kind.
        letter = "".join(ch for ch in c.addr if ch.isalpha())
        entry = by_col.setdefault((c.sheet, c.col), (letter, []))
        entry[1].append(c.row)
    parts = []
    for (sheet, _col), (letter, rows) in sorted(by_col.items()):
        parts.append(f"{sheet}!{letter}{min(rows)}:{letter}{max(rows)}"
                     if len(rows) > 1 else f"{sheet}!{letter}{min(rows)}")
    extra = f" (+{len(parts) - limit} more)" if len(parts) > limit else ""
    return "Source: " + ", ".join(parts[:limit]) + extra


def build(answers: list[Answer], title: str = "Operating review",
          source_file: str = "") -> list[Slide]:
    """The whole deck, as structure. No rendering library is involved."""
    deck: list[Slide] = [Slide(
        title=title,
        subtitle=f"Generated from {source_file}" if source_file else "",
        bullets=[f"{sum(1 for a in answers if not a.abstained)} questions answered from the data",
                 f"{sum(1 for a in answers if a.abstained)} refused as unanswerable",
                 "Every figure carries the cells it was computed from"],
        kind="title")]

    for a in answers:
        if a.abstained:
            deck.append(Slide(
                title=a.question,
                subtitle="Not answerable from this workbook",
                bullets=[a.abstain_reason,
                         "No estimate is shown, because the data does not support one."],
                kind="refusal"))
            continue

        res = a.result
        deck.append(Slide(
            title=a.question,
            subtitle=a.prose,
            bullets=[f"{len(res.rows)} row(s) in the result",
                     f"Computed as: {res.computed}"],
            table_columns=list(res.columns),
            table_rows=[[_fmt(c.value) for c in row] for row in res.rows[:8]],
            footnote=_sources_footnote(a),
            kind="finding"))

    deck.append(Slide(
        title="How to check any number on these slides",
        bullets=["Each slide's footnote names the sheet and cell range behind it.",
                 "Open the workbook at that range; the figure is the fold over those cells.",
                 "Refused questions are shown, not omitted — selection is a way to mislead too."],
        kind="appendix"))
    return deck


def render(answers: list[Answer], title: str = "Operating review",
           source_file: str = "", **_) -> str:
    """Text preview of the deck. Same `build()` a pptx writer would consume."""
    out = []
    for i, s in enumerate(build(answers, title, source_file), start=1):
        out.append(f"┌─ slide {i}  [{s.kind}] " + "─" * max(0, 56 - len(s.kind)))
        out.append(f"│ {s.title}")
        if s.subtitle:
            out.append(f"│ {s.subtitle}")
        for b in s.bullets:
            out.append(f"│   • {b}")
        if s.table_columns:
            out.append("│   " + " | ".join(s.table_columns))
            for r in s.table_rows:
                out.append("│   " + " | ".join(r))
        if s.footnote:
            out.append(f"│ {s.footnote}")
        out.append("└" + "─" * 70)
        out.append("")
    return "\n".join(out)
