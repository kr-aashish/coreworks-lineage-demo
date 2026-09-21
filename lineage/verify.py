"""The abstention gates. Four of them, in order, and any one of them can refuse the answer.

WHY THERE IS A GATE AFTER THE PROSE IS WRITTEN
    Gates 1-3 stop the system answering a question it cannot serve. None of them stop the LAST
    failure, which is the one that actually happens: the numbers are computed correctly and the
    sentence around them is wrong -- a figure rounded into a different number, a total quoted as
    a regional figure, a number that simply was not in the result at all.

    Gate 4 re-reads the finished prose, pulls every numeral out of it, and requires each one to
    be reconcilable with the executed result. An uncited number fails the answer. That makes
    "zero hallucination" a property that is CHECKED on every response rather than a property
    the prompt asks for politely.

    ⚠️ Honest limit, and it is the first thing to say when it is probed in the room: gate 4
    constrains NUMBERS, not claims. "North grew because of the marketplace launch" carries no
    numeral and passes. Causal language is handled by keeping the renderer's prose templated
    rather than free -- see renderers/text.py -- which is a narrower promise than the gate and
    is stated as such.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Answer, QueryPlan, ResultSet

#: numerals in prose, including 1,234.56 / 12.5% / -3
#: ⚠️ The group MUST NOT end on a comma. `-?\d[\d,]*` matched "2025," out of "...= 2025, and"
#: and then float("2025,") raised, so the numeral was skipped -- or worse, matched a digit run
#: that spanned a sentence boundary. A thousands separator is only a separator BETWEEN digits.
_NUM_IN_PROSE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


@dataclass
class GateResult:
    ok: bool
    gate: str
    detail: str = ""


def gate_plan_bound(plan: QueryPlan, error: Exception | None) -> GateResult:
    """Gate 1 — the plan binds to the schema. `error` is whatever validate() raised."""
    if plan.abstain:
        return GateResult(False, "planner abstained", plan.abstain)
    if error is not None:
        return GateResult(False, "plan did not bind to the schema", str(error))
    return GateResult(True, "plan bound to the schema")


def gate_has_support(result: ResultSet) -> GateResult:
    """Gate 2 — the query returned rows. An empty result is not a zero."""
    if result.is_empty():
        return GateResult(
            False, "no supporting rows",
            "the query bound to the schema but matched no rows — which is a statement about "
            "the filters, not a value of zero")
    return GateResult(True, "result has supporting rows")


def gate_every_number_has_cells(result: ResultSet) -> GateResult:
    """Gate 3 — no numeric output may exist without source cells behind it."""
    orphans = []
    for r_i, row in enumerate(result.rows):
        for c_i, cell in enumerate(row):
            if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                if not cell.provenance.cells:
                    orphans.append(f"row {r_i}, column {result.columns[c_i]}")
    if orphans:
        return GateResult(False, "a number had no provenance",
                          "; ".join(orphans[:5]))
    return GateResult(True, f"all {len(result.numbers())} numeric outputs carry source cells")


def _decimals(raw: str) -> int:
    return len(raw.split(".")[1]) if "." in raw else 0


def _reconcilable(n: float, raw: str, pool: list[float]) -> bool:
    """Is the numeral `raw` (parsed as `n`) a faithful rendering of something we computed?

    ⭐ THE PRIMARY TEST IS ROUNDING AT THE DISPLAYED PRECISION, not a percentage tolerance.
      A margin of 47.42 shown as "47" is honest; a percentage band wide enough to admit it
      would also admit 47.2, which we never computed. Asking "is `raw` what you get when you
      round a computed value to the number of decimals `raw` actually shows" accepts the first
      and rejects the second, and needs no arbitrary constant.
    """
    d = _decimals(raw)
    for p in pool:
        if round(p, d) == n:
            return True
    # A figure legitimately quoted in thousands / lakhs / millions / crores. The scale is
    # explicit and small; the rounding test is applied again at the displayed precision.
    for p in pool:
        for scale in (1e3, 1e5, 1e6, 1e7):
            if round(p / scale, d) == n:
                return True
    # ⛔ THERE IS NO PERCENTAGE-TOLERANCE FALLBACK, AND THAT IS DELIBERATE.
    # An earlier version allowed anything within 0.5%. Against a computed 46.52 that admitted
    # "46.7" -- a number we never produced, inside the band, reading as fine. A tolerance wide
    # enough to be useful is wide enough to pass a wrong figure, so the only question asked is
    # "is this what one of our numbers rounds to at the precision shown".
    return n == 0 and any(abs(p) < 1e-9 for p in pool)


def gate_prose_numbers_cited(prose: str, result: ResultSet,
                             allow: tuple[float, ...] = ()) -> GateResult:
    """Gate 4 — every numeral in the prose reconciles to the executed result.

    `allow` carries numerals the renderer legitimately introduced that are not data values —
    a row count, a year taken from the question. They are passed EXPLICITLY, one at a time,
    because a general "ignore small integers" rule is how a wrong count gets through.
    """
    pool = result.numbers() + list(allow)
    # ⭐ Numerals that are part of a TEXT value the query returned -- "Cast Iron Skillet 10in",
    # "Q3", "SKU-1004". They are not claims about quantity; they are names, and they arrived
    # from the data carrying the same cell provenance as everything else. Excluding them would
    # make the gate refuse every honest answer whose label happens to contain a digit.
    for row in result.rows:
        for cell in row:
            if isinstance(cell.value, str):
                for tok in _NUM_IN_PROSE.findall(cell.value):
                    try:
                        pool.append(float(tok.replace(",", "")))
                    except ValueError:
                        pass
    bad = []
    for m in _NUM_IN_PROSE.finditer(prose):
        raw = m.group(0)
        try:
            n = float(raw.replace(",", ""))
        except ValueError:
            continue
        if not _reconcilable(n, raw, pool):
            bad.append(raw)
    if bad:
        return GateResult(
            False, "a number in the answer is not in the result",
            f"{', '.join(bad)} — present in the sentence, absent from what was computed")
    return GateResult(True, "every number in the answer reconciles to the result")


def run_gates(answer: Answer, plan_error: Exception | None = None,
              allow: tuple[float, ...] = ()) -> Answer:
    """Apply gates 1-4 in order, recording the trail. First failure abstains."""
    checks = [gate_plan_bound(answer.plan, plan_error)] if answer.plan else [
        GateResult(False, "no plan", "the planner produced nothing")]

    if checks[-1].ok and answer.result is not None:
        checks.append(gate_has_support(answer.result))
        if checks[-1].ok:
            checks.append(gate_every_number_has_cells(answer.result))
        if checks[-1].ok and answer.prose:
            checks.append(gate_prose_numbers_cited(answer.prose, answer.result, allow))

    answer.trail = [f"{'PASS' if c.ok else 'REFUSE'}  {c.gate}"
                    + (f" — {c.detail}" if c.detail else "") for c in checks]
    failed = next((c for c in checks if not c.ok), None)
    if failed:
        answer.abstained = True
        answer.abstain_reason = f"{failed.gate}: {failed.detail}" if failed.detail else failed.gate
        answer.prose = ""
    return answer
