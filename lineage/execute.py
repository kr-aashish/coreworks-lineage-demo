"""Run a validated QueryPlan and carry provenance all the way to the output cell.

THE RULE THAT MAKES LINEAGE TOTAL
    Every output value is produced by folding over a set of input Values. The fold keeps the
    union of their CellRefs. So a SUM over 47 rows arrives at the renderer knowing all 47
    cells, and `sum_net_revenue = 4,812,300` can be expanded into the addresses that made it.

    There is no step in here where a number is produced from something other than cells. That
    is checked, not hoped for: `verify.py` refuses an Answer carrying a numeric output cell
    with an empty provenance set.

VALIDATION IS SEPARATE AND COMES FIRST
    `validate()` binds every name in the plan against the store's published schema. A plan that
    does not bind is REFUSED -- it never reaches the executor. That is the whole safety story
    and it is only available because the plan is a closed algebra (model.QueryPlan).
"""
from __future__ import annotations

import datetime as _dt

from .ingest import Value
from .model import AGGS, OPS, Cell, Filter, Provenance, QueryPlan, ResultSet
from .store import Store


class PlanError(Exception):
    """A plan that does not bind to the schema. Always surfaced, never repaired."""


# --------------------------------------------------------------------------- validate

def validate(plan: QueryPlan, store: Store) -> None:
    if plan.abstain:
        return
    tbl = store.table(plan.table)
    if tbl is None or not tbl.columns:
        raise PlanError(f"no queryable table named {plan.table!r}; "
                        f"have {[t.name for t in store.queryable()]}")

    known = {c.name for c in tbl.columns}
    for j in plan.joins:
        rt = store.table(j.table)
        if rt is None or not rt.columns:
            raise PlanError(f"cannot join to {j.table!r} — not a queryable table")
        allowed = store.join_targets(plan.table)
        if j.table not in allowed:
            raise PlanError(f"no key joins {plan.table} to {j.table}; "
                            f"available joins: {sorted(allowed)}")
        known |= {c.name for c in rt.columns}
        for d in (store.JOIN_DERIVATIONS if hasattr(store, "JOIN_DERIVATIONS") else {}).get(
                (plan.table, j.table), ()):
            known.add(d.name)
    from .store import JOIN_DERIVATIONS
    for j in plan.joins:
        for d in JOIN_DERIVATIONS.get((plan.table, j.table), ()):
            known.add(d.name)

    if not plan.select:
        raise PlanError("plan selects nothing")
    for s in plan.select:
        if s.agg is not None and s.agg not in AGGS:
            raise PlanError(f"unknown aggregate {s.agg!r}; allowed: {list(AGGS)}")
        if s.column != "*" and s.column not in known:
            raise PlanError(f"unknown column {s.column!r} on {plan.table}; "
                            f"have {sorted(known)}")
    for f in plan.filters:
        if f.op not in OPS:
            raise PlanError(f"unknown operator {f.op!r}; allowed: {list(OPS)}")
        if f.column not in known:
            raise PlanError(f"filter names unknown column {f.column!r}; have {sorted(known)}")
    for g in plan.group_by:
        if g not in known:
            raise PlanError(f"group_by names unknown column {g!r}; have {sorted(known)}")
    if plan.order_by:
        outs = {s.out_name for s in plan.select} | set(plan.group_by)
        if plan.order_by not in outs and plan.order_by not in known:
            raise PlanError(f"order_by {plan.order_by!r} is not selected; have {sorted(outs)}")


# --------------------------------------------------------------------------- filters

def _as_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None
    return None


def _cmp_key(a, b):
    """Compare a stored value against a filter literal, tolerating type mismatch honestly."""
    if isinstance(a, (_dt.date, _dt.datetime)) and isinstance(b, str):
        try:
            b = _dt.date.fromisoformat(b)
        except ValueError:
            return None, None
        a = a.date() if isinstance(a, _dt.datetime) else a
        return a, b
    na, nb = _as_number(a), _as_number(b)
    if na is not None and nb is not None:
        return na, nb
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower(), b.strip().lower()
    return a, b


def _match(v: Value, f: Filter) -> bool:
    val = v.value
    if val is None:
        return False           # a missing value matches no filter, including "!="
    if f.op == "in":
        return any(_match(v, Filter(f.column, "=", x)) for x in (f.value or []))
    if f.op == "between":
        lo, hi = f.value
        a, l = _cmp_key(val, lo)
        _b, h = _cmp_key(val, hi)
        try:
            return l <= a <= h
        except TypeError:
            return False
    if f.op == "contains":
        return isinstance(val, str) and str(f.value).strip().lower() in val.strip().lower()
    a, b = _cmp_key(val, f.value)
    if a is None and b is None:
        return False
    try:
        return {"=": a == b, "!=": a != b, ">": a > b,
                ">=": a >= b, "<": a < b, "<=": a <= b}[f.op]
    except TypeError:
        return False


# --------------------------------------------------------------------------- aggregate

def _fold(agg: str, vals: list[Value]) -> Cell:
    """The fold. `vals` are the contributing Values; the output keeps all their cells."""
    present = [v for v in vals if v.value is not None]
    cells = tuple(c for v in present for c in v.prov.cells)
    notes = sorted({v.prov.note for v in present if v.prov.note and "derived" not in v.prov.note})
    missing = len(vals) - len(present)
    note_bits = list(notes)
    if missing:
        note_bits.append(f"{missing} row(s) had no value and were excluded")

    if agg == "count":
        out = float(len(present))
    elif agg == "count_distinct":
        out = float(len({v.value for v in present}))
    elif not present:
        out = None
    elif agg == "sum":
        out = sum(float(v.value) for v in present)
    elif agg == "avg":
        out = sum(float(v.value) for v in present) / len(present)
    elif agg == "min":
        out = min(v.value for v in present)
    elif agg == "max":
        out = max(v.value for v in present)
    else:
        raise PlanError(f"unknown aggregate {agg!r}")
    return Cell(out, Provenance(cells, "; ".join(note_bits)))


# --------------------------------------------------------------------------- execute

def execute(plan: QueryPlan, store: Store) -> ResultSet:
    validate(plan, store)
    sheet = store.sheets[plan.table]
    rows = [dict(r) for r in sheet.rows]

    steps = [f"{len(rows)} rows from {plan.table}"]

    for j in plan.joins:
        right = store.sheets[j.table]
        index = {}
        for rr in right.rows:
            k = rr[j.right_on].value
            if isinstance(k, str):
                k = k.strip().lower()
            index.setdefault(k, rr)
        joined = []
        for r in rows:
            k = r[j.left_on].value
            if isinstance(k, str):
                k = k.strip().lower()
            rr = index.get(k)
            if rr is None:
                continue                      # an unmatched left row is DROPPED, and counted
            merged = dict(r)
            for cname, cval in rr.items():
                merged.setdefault(cname, cval)
            joined.append(merged)
        dropped = len(rows) - len(joined)
        rows = joined
        store.apply_join_derivations(plan.table, j.table, rows)
        steps.append(f"joined {j.table} on {j.left_on} → {len(rows)} rows"
                     + (f" ({dropped} unmatched dropped)" if dropped else ""))

    for f in plan.filters:
        before = len(rows)
        rows = [r for r in rows if f.column in r and _match(r[f.column], f)]
        steps.append(f"filter {f.column} {f.op} {f.value!r}: {before} → {len(rows)} rows")

    if plan.group_by and not rows:
        steps.append("no rows matched — returning an EMPTY result, not a zero")
        return ResultSet(list(plan.group_by) + [s.out_name for s in plan.select], [],
                         computed=" · ".join(steps))

    if plan.group_by:
        groups: dict[tuple, list[dict]] = {}
        for r in rows:
            key = tuple(r[g].value for g in plan.group_by)
            groups.setdefault(key, []).append(r)
        out_cols = list(plan.group_by) + [s.out_name for s in plan.select]
        out_rows = []
        for key, members in groups.items():
            cells = []
            for g, kv in zip(plan.group_by, key):
                cells.append(Cell(kv, Provenance(
                    tuple(c for m in members for c in m[g].prov.cells))))
            for s in plan.select:
                if s.agg is None:
                    raise PlanError(f"{s.column!r} is selected raw beside a group_by; "
                                    f"give it an aggregate or drop the group_by")
                src = [m[s.column] for m in members] if s.column != "*" else [
                    Value(1.0, Provenance(tuple(c for m in members
                                                for c in next(iter(m.values())).prov.cells)))
                    for m in members]
                cells.append(_fold(s.agg, src))
            out_rows.append(cells)
        steps.append(f"grouped by {', '.join(plan.group_by)} → {len(out_rows)} groups")
    elif any(s.agg for s in plan.select):
        out_cols = [s.out_name for s in plan.select]
        if not rows:
            # ⛔ NOT a row of nulls, and ⛔ not count=0. Aggregating an empty match invents a
            # result row that gate 2 then sees as "supported". "No rows matched Antarctica" is
            # true; "Antarctica sold 0 units" is a claim the data does not make.
            steps.append("no rows matched — returning an EMPTY result, not a zero")
            return ResultSet(out_cols, [], computed=" · ".join(steps))
        cells = []
        for s in plan.select:
            src = ([r[s.column] for r in rows] if s.column != "*"
                   else [Value(1.0, next(iter(r.values())).prov) for r in rows])
            cells.append(_fold(s.agg, src))
        out_rows = [cells]
        steps.append("aggregated to 1 row")
    else:
        out_cols = [s.out_name for s in plan.select]
        out_rows = [[Cell(r[s.column].value, r[s.column].prov) for s in plan.select]
                    for r in rows]

    if plan.order_by and plan.order_by in out_cols:
        i = out_cols.index(plan.order_by)
        out_rows.sort(key=lambda row: (row[i].value is None, row[i].value),
                      reverse=plan.descending)
        steps.append(f"ordered by {plan.order_by} {'desc' if plan.descending else 'asc'}")
    if plan.limit:
        out_rows = out_rows[:plan.limit]
        steps.append(f"limit {plan.limit}")

    return ResultSet(out_cols, out_rows, computed=" · ".join(steps))
