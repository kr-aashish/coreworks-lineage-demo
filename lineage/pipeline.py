"""question -> Answer. The whole flow, in one readable function.

    plan  →  validate  →  execute  →  compose prose  →  gate  →  Answer

⛔ THE LINE THIS FILE DEFENDS: the pipeline returns Answers and stops. It does not print, it
   does not format, it knows nothing about slides or PDFs. Everything a renderer could need is
   inside the Answer by the time it is returned, which is what makes a new output format one
   file in renderers/ instead of a second pipeline.
"""
from __future__ import annotations

import re

from .execute import PlanError, execute, validate
from .model import Answer, QueryPlan, ResultSet
from .store import Store
from .verify import run_gates


def _describe_filters(plan: QueryPlan) -> str:
    if not plan.filters:
        return ""
    bits = []
    for f in plan.filters:
        if f.op == "between":
            bits.append(f"{_label(f.column)} from {f.value[0]} to {f.value[1]}")
        elif f.op == "=":
            bits.append(f"{f.column} = {f.value}")
        else:
            bits.append(f"{_label(f.column)} {f.op} {f.value}")
    return " where " + ", ".join(bits)


def _label(col: str) -> str:
    """`region_norm` reads as `region` in a sentence. The column keeps its real name
    everywhere a number is traced; only the prose drops the suffix."""
    return col[:-5] if col.endswith("_norm") else col


def _filter_literals(plan: QueryPlan) -> list[float]:
    """Numerals that came out of the PLAN, not out of the data.

    `fiscal_year = 2025` puts a 2025 in the sentence which is not a computed value and never
    will be in the result. It is still fully traceable -- it is a literal the plan named, and
    the plan is printed beside the answer -- so it is declared to gate 4 rather than excused.
    ⛔ Declared one literal at a time; never a blanket "ignore 4-digit numbers" rule.
    """
    out: list[float] = []
    for f in plan.filters:
        vals = f.value if isinstance(f.value, (list, tuple)) else [f.value]
        for v in vals:
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out.append(float(v))
            elif isinstance(v, str):
                for tok in re.findall(r"-?\d+(?:\.\d+)?", v):
                    out.append(float(tok))
    if plan.limit:
        out.append(float(plan.limit))
    return out


def _compose(question: str, plan: QueryPlan, result: ResultSet) -> tuple[str, tuple[float, ...]]:
    """Templated prose. Returns the sentence and the numerals it legitimately introduced.

    Those numerals are handed to gate 4 EXPLICITLY. A renderer that wants to say "across 4
    regions" must declare the 4, because the alternative -- letting the gate ignore small
    integers -- is exactly how a wrong count would get through.
    """
    allow: list[float] = _filter_literals(plan)
    scope = _describe_filters(plan)

    if plan.group_by and len(result.rows) > 1:
        allow.append(float(len(result.rows)))
        head = result.rows[0]
        label = head[0].value
        metric = result.columns[len(plan.group_by)]
        top = head[len(plan.group_by)].value
        sentence = (f"Across {len(result.rows)} {_label(plan.group_by[0])} values{scope}, "
                    f"the largest {metric} is {label} at ")
        sentence += (f"{top:,.2f}." if isinstance(top, float) else f"{top}.")
        return sentence, tuple(allow)

    if len(result.rows) == 1:
        parts = []
        for col, cell in zip(result.columns, result.rows[0]):
            v = cell.value
            parts.append(f"{col} = " + (f"{v:,.2f}" if isinstance(v, float) else str(v)))
        return f"From {plan.table}{scope}: " + "; ".join(parts) + ".", tuple(allow)

    allow.append(float(len(result.rows)))
    return (f"{len(result.rows)} row(s) from {plan.table}{scope}; "
            f"the full result is below."), tuple(allow)


def answer(question: str, store: Store, planner) -> Answer:
    plan: QueryPlan | None = None
    plan_error: Exception | None = None
    result: ResultSet | None = None
    prose, allow = "", ()

    try:
        plan = planner.plan(question, store)
    except Exception as e:                       # a planner that fails is an abstention
        a = Answer(question, "", None, None)
        a.abstained = True
        a.abstain_reason = f"the planner could not produce a plan: {e}"
        a.trail = [f"REFUSE  planner failed — {e}"]
        return a

    if not plan.abstain:
        try:
            validate(plan, store)
            result = execute(plan, store)
        except PlanError as e:
            plan_error = e
        except Exception as e:                   # an executor bug must not become an answer
            plan_error = PlanError(f"execution failed: {e}")

    if result is not None and not result.is_empty():
        prose, allow = _compose(question, plan, result)

    a = Answer(question=question, prose=prose, result=result, plan=plan)
    return run_gates(a, plan_error, allow)


def answer_all(questions: list[str], store: Store, planner) -> list[Answer]:
    return [answer(q, store, planner) for q in questions]
