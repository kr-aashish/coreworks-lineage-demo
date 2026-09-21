"""Question -> QueryPlan. The one place a language model is allowed to touch the problem.

⭐ THE LOAD-BEARING DECISION: TEXT-TO-PLAN, NOT TEXT-TO-SQL
    The obvious build is text-to-SQL: hand the model the schema, take back a SELECT, run it.
    It is rejected here for one reason that matters more than any other:

        The set of SQL strings a model can emit is not enumerable, so you cannot validate one.
        You can only run it and hope. When it is wrong it does not crash -- it returns a
        number, and a wrong number with a confident sentence around it is exactly the failure
        this assignment is about preventing.

    A closed algebra (model.QueryPlan) inverts that. Every name in the plan is bound against
    the published schema BEFORE anything executes, so an unbindable plan is refused rather
    than run. And because the executor knows the shape of every operation it performs, it can
    carry cell provenance through them -- which free SQL forecloses, because you would be
    parsing arbitrary SQL to work out which cells fed which output.

    ⇒ Two properties fall out of the same decision: lineage is total, and injection is not a
      category that exists. Neither is available in the text-to-SQL build at any price.

    Cost, stated honestly: the algebra is narrower than SQL. Window functions, correlated
    subqueries and arbitrary expressions are not expressible. The answer to that is to WIDEN
    THE ALGEBRA deliberately -- each new operator arrives with its provenance rule -- not to
    fall back to raw SQL for the hard ones, which would put the guarantee back to nothing.

TWO PLANNERS, SAME OUTPUT TYPE
    `LLMPlanner`    real. Anthropic Messages API, schema card in, JSON plan out.
    `CachedPlanner` a recorded plan per question, committed under plans/. It exists so the repo
                    runs end-to-end with no API key -- a reviewer can clone it and see it work,
                    and the demo cannot fail in the room because of a network.

    ⚠️ HONEST PROVENANCE OF THE SHIPPED PLANS, because this is exactly the kind of thing the
      system itself refuses to fudge: the five plans in plans/ were written by a Claude model
      following the SYSTEM prompt below against the real schema card, but NOT through the
      Anthropic API on the machine that built this repo -- there was no key on it. Each file
      says so in its own `recorded_by` field. `python record_plans.py` re-records all five
      through the live API and overwrites them; the plans it produces should be compared, and
      any difference is interesting rather than embarrassing.
    ⛔ CachedPlanner is NOT a rule engine pretending to be a model. It does no matching and no
      inference: an unseen question raises FileNotFoundError telling you to run with a key.
      A cached planner that could improvise would make the demo a puppet show.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .model import QueryPlan
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
PLAN_DIR = ROOT / "plans"

MODEL = "claude-sonnet-5"

SYSTEM = """\
You translate a question about a spreadsheet into a QUERY PLAN. You never answer the question
and you never state a number: you only say what should be computed.

You are given a schema card. It lists tables, columns, types, and which columns are derived.
You are NOT given the data. You cannot see any value.

Emit ONE JSON object and nothing else:

{
  "table":     "<the table to read>",
  "joins":     [{"table": "<other table>", "left_on": "<col>", "right_on": "<col>"}],
  "filters":   [{"column": "<col>", "op": "<= != > >= < <= in between contains>", "value": <lit>}],
  "group_by":  ["<col>"],
  "select":    [{"agg": "<sum|count|count_distinct|avg|min|max|null>", "column": "<col>",
                 "alias": "<optional>"}],
  "order_by":  "<an output name, or null>",
  "descending": true,
  "limit":     <int or null>,
  "abstain":   null
}

RULES
1. Use ONLY table and column names that appear in the schema card, spelled exactly.
2. If the question cannot be answered from these columns -- because the quantity is not in the
   workbook at all, because it asks for a forecast, an opinion, or anything outside the data --
   set "abstain" to a one-sentence reason naming what is missing, and leave the rest null/empty.
   Abstaining is a correct answer. Guessing a near-miss column is not.
3. Prefer a *_norm column for grouping or filtering on text. The raw column has casing and
   whitespace variants; the _norm column is the cleaned one and points at the same cells.
4. Never invent an aggregate over a text column.
5. A sheet marked "free text, NOT queryable" cannot be used for anything. If the answer would
   have to come from it, abstain.
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    depth, end = 0, None
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("unterminated JSON object in model output")
    return json.loads(text[start:end])


def _slug(question: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:70]


class LLMPlanner:
    """The real planner. Requires ANTHROPIC_API_KEY."""

    name = "llm"

    def __init__(self, model: str = MODEL, record: bool = True):
        self.model = model
        self.record = record

    def plan(self, question: str, store: Store) -> QueryPlan:
        from anthropic import Anthropic          # imported late: optional dependency
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model=self.model,
            max_tokens=1200,
            system=SYSTEM,
            messages=[{"role": "user", "content":
                       f"SCHEMA CARD\n-----------\n{store.schema_card()}\n\n"
                       f"QUESTION\n--------\n{question}"}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        raw = _extract_json(text)
        if self.record:
            PLAN_DIR.mkdir(exist_ok=True)
            (PLAN_DIR / f"{_slug(question)}.json").write_text(json.dumps(
                {"question": question, "model": self.model, "plan": raw}, indent=2) + "\n")
        return QueryPlan.from_dict(raw)


class CachedPlanner:
    """Replays a plan recorded by LLMPlanner, so the demo runs with no key and no network."""

    name = "cached"

    def plan(self, question: str, store: Store) -> QueryPlan:
        f = PLAN_DIR / f"{_slug(question)}.json"
        if not f.exists():
            raise FileNotFoundError(
                f"no recorded plan for {question!r}.\n"
                f"  This question has never been planned by a model. Run with a key:\n"
                f"    ANTHROPIC_API_KEY=... python demo.py --planner llm --ask '{question}'\n"
                f"  ⛔ The cached planner will not invent a plan — that is the whole point of it."
            )
        return QueryPlan.from_dict(json.loads(f.read_text())["plan"])


def get_planner(kind: str = "auto"):
    if kind == "llm":
        return LLMPlanner()
    if kind == "cached":
        return CachedPlanner()
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # noqa: F401
            return LLMPlanner()
        except ImportError:
            pass
    return CachedPlanner()
