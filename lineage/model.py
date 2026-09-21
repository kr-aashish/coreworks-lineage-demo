"""The four objects the whole system is built out of.

    CellRef     WHERE a value came from. One spreadsheet cell, addressable in the room:
                "Sales!G158". Everything downstream carries a set of these and nothing is
                allowed to exist without one.
    Column      a typed column in the tidy store, and the rule that produced it. A DERIVED
                column names the columns it was derived FROM, so its provenance resolves to
                real cells rather than to nothing -- that is the only reason a margin figure
                can answer "where did this come from?".
    QueryPlan   the CLOSED algebra the planner is allowed to emit. Not SQL. See plan.py for
                why, which is the load-bearing architectural decision in this repo.
    Answer      the one thing a renderer ever sees: a claim, the rows that support it, and
                the cells those rows came from. A deck, a PDF and a CLI print are three
                renderers over this -- which is the whole of the "not a rewrite" story.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, order=True)
class CellRef:
    """One cell, as a human would point at it on a screen."""
    sheet: str
    row: int          # 1-based, exactly as Excel shows it
    col: int          # 1-based
    addr: str         # "G158" -- precomputed so a renderer never has to do column maths

    def __str__(self) -> str:
        return f"{self.sheet}!{self.addr}"


@dataclass(frozen=True)
class Provenance:
    """Where a single value came from, and what happened to it on the way in.

    `note` is how a coercion stays visible. A price stored as the TEXT "1,299.00" becomes the
    number 1299.0, and the note says so -- so "where did this come from" answers with the cell
    AND with the fact that the cell did not contain a number.
    """
    cells: tuple[CellRef, ...]
    note: str = ""

    def __str__(self) -> str:
        head = ", ".join(str(c) for c in self.cells[:4])
        if len(self.cells) > 4:
            head += f", +{len(self.cells) - 4} more"
        return f"{head}{' — ' + self.note if self.note else ''}"


DType = Literal["number", "text", "date", "bool"]


@dataclass(frozen=True)
class Column:
    name: str
    dtype: DType
    origin: Literal["source", "derived", "normalised"]
    description: str = ""
    derived_from: tuple[str, ...] = ()
    #: the source column this one was cleaned from, for `origin="normalised"`
    normalised_from: str | None = None


@dataclass(frozen=True)
class Table:
    name: str
    sheet: str
    columns: tuple[Column, ...]
    row_count: int
    #: the Excel row each store row came from -- the spine of every lineage answer
    header_row: int
    note: str = ""

    def column(self, name: str) -> Column | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None


# --------------------------------------------------------------------------- the plan

AGGS = ("sum", "count", "count_distinct", "avg", "min", "max")
OPS = ("=", "!=", ">", ">=", "<", "<=", "in", "between", "contains")


@dataclass(frozen=True)
class Selection:
    agg: str | None          # None => a plain column projection
    column: str
    alias: str | None = None

    @property
    def out_name(self) -> str:
        if self.alias:
            return self.alias
        return f"{self.agg}_{self.column}" if self.agg else self.column


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: Any


@dataclass(frozen=True)
class Join:
    table: str
    left_on: str
    right_on: str


@dataclass
class QueryPlan:
    """A plan the executor can run and a human can read out loud.

    ⛔ There is no free-text SQL anywhere in this object and that is deliberate. Everything the
    planner can express is enumerable, so validation is TOTAL: a plan either binds to the
    published schema or it is refused. A text-to-SQL system cannot make that promise, because
    the space of strings it can emit is not enumerable and the failure mode is a query that
    runs and returns the wrong number.
    """
    table: str
    select: list[Selection]
    filters: list[Filter] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    joins: list[Join] = field(default_factory=list)
    order_by: str | None = None
    descending: bool = True
    limit: int | None = None
    #: set when the planner decides the question cannot be served from this schema at all
    abstain: str | None = None

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "select": [{"agg": s.agg, "column": s.column, "alias": s.alias} for s in self.select],
            "filters": [{"column": f.column, "op": f.op, "value": f.value} for f in self.filters],
            "group_by": list(self.group_by),
            "joins": [{"table": j.table, "left_on": j.left_on, "right_on": j.right_on}
                      for j in self.joins],
            "order_by": self.order_by,
            "descending": self.descending,
            "limit": self.limit,
            "abstain": self.abstain,
        }

    @staticmethod
    def from_dict(d: dict) -> "QueryPlan":
        return QueryPlan(
            table=d.get("table", ""),
            select=[Selection(s.get("agg"), s["column"], s.get("alias"))
                    for s in d.get("select", [])],
            filters=[Filter(f["column"], f["op"], f["value"]) for f in d.get("filters", [])],
            group_by=list(d.get("group_by", [])),
            joins=[Join(j["table"], j["left_on"], j["right_on"]) for j in d.get("joins", [])],
            order_by=d.get("order_by"),
            descending=bool(d.get("descending", True)),
            limit=d.get("limit"),
            abstain=d.get("abstain"),
        )


# --------------------------------------------------------------------------- the answer

@dataclass
class Cell:
    """One value in the result grid, with the source cells that produced it."""
    value: Any
    provenance: Provenance


@dataclass
class ResultSet:
    columns: list[str]
    rows: list[list[Cell]]
    #: a human-readable restatement of what was actually computed, for the room
    computed: str = ""

    def numbers(self) -> list[float]:
        out = []
        for row in self.rows:
            for c in row:
                if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                    out.append(float(c.value))
        return out

    def is_empty(self) -> bool:
        return not self.rows


@dataclass
class Answer:
    """What a renderer consumes. Nothing else crosses that line."""
    question: str
    prose: str
    result: ResultSet | None
    plan: QueryPlan | None
    abstained: bool = False
    abstain_reason: str = ""
    #: every gate the answer passed, in order, so the trail is inspectable in the room
    trail: list[str] = field(default_factory=list)
