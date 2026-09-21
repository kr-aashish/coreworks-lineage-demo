"""The store: ingested sheets, the derived columns declared on top of them, and the schema
the planner is shown.

DERIVED COLUMNS ARE THE INTERESTING PART
    `net_revenue` is a formula column in the workbook with no cached value, so it arrives NULL.
    Rather than evaluate the spreadsheet, the store RE-DERIVES it from units x unit_price x
    (1 - discount_pct) and the derived value's provenance is the union of those three cells.
    ⇒ "where did 18,432 come from?" answers with Sales!F158, Sales!G158, Sales!H158 and the
    arithmetic -- which is a better answer than pointing at the formula cell, because it names
    the inputs the number is actually sensitive to.

    ⛔ A derived column is DECLARED, never inferred. An inferred metric is a number the system
    invented, and inventing numbers is the thing this assignment is about not doing.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from .ingest import Sheet, Value, ingest
from .model import Column, Provenance, Table


@dataclass(frozen=True)
class Derivation:
    """One declared derived column."""
    table: str
    name: str
    inputs: tuple[str, ...]
    fn: callable
    description: str
    dtype: str = "number"


def _fy_quarter(d) -> str | None:
    """April-start fiscal year, stated here once so no question has to restate it."""
    if not isinstance(d, (_dt.date, _dt.datetime)):
        return None
    d = d.date() if isinstance(d, _dt.datetime) else d
    return f"Q{((d.month - 4) % 12) // 3 + 1}"


def _fy_year(d) -> float | None:
    if not isinstance(d, (_dt.date, _dt.datetime)):
        return None
    d = d.date() if isinstance(d, _dt.datetime) else d
    return float(d.year if d.month >= 4 else d.year - 1)


DERIVATIONS: tuple[Derivation, ...] = (
    Derivation(
        "Sales", "net_revenue_calc", ("units", "unit_price", "discount_pct"),
        lambda u, p, d: None if (u is None or p is None) else u * p * (1 - (d or 0.0)),
        "units x unit_price x (1 - discount_pct). Re-derived because the workbook's "
        "net_revenue column is a formula with no cached value."),
    Derivation(
        "Sales", "fiscal_quarter", ("order_date",), _fy_quarter,
        "fiscal quarter, April-start fiscal year", dtype="text"),
    Derivation(
        "Sales", "fiscal_year", ("order_date",), _fy_year,
        "fiscal year label, April-start (FY2025 = Apr 2025 to Mar 2026)"),
    Derivation(
        "Sales", "gross_revenue", ("units", "unit_price"),
        lambda u, p: None if (u is None or p is None) else u * p,
        "units x unit_price, before discount"),
    Derivation(
        "Headcount", "fiscal_quarter", ("month",), _fy_quarter,
        "fiscal quarter of the headcount month", dtype="text"),
)

#: Columns that only exist once two sheets are joined. Declared the same way, for the same
#: reason -- and the provenance spans both sheets, which is what makes a margin answer honest.
JOIN_DERIVATIONS = {
    ("Sales", "Products"): (
        Derivation(
            "Sales", "unit_margin", ("unit_price", "cost_price"),
            lambda p, c: None if (p is None or c is None) else p - c,
            "unit_price (Sales) - cost_price (Products)"),
        Derivation(
            "Sales", "margin_pct", ("unit_price", "cost_price"),
            lambda p, c: None if (p is None or c is None or p == 0) else (p - c) / p * 100.0,
            "(unit_price - cost_price) / unit_price x 100, as a percentage"),
        Derivation(
            "Sales", "gross_profit", ("units", "unit_price", "cost_price"),
            lambda u, p, c: None if (u is None or p is None or c is None) else u * (p - c),
            "units x (unit_price - cost_price)"),
    ),
}


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.sheets: dict[str, Sheet] = {}
        for sh in ingest(self.path):
            self.sheets[sh.name] = sh
        self._apply_derivations()

    # ------------------------------------------------------------------ derivation

    def _apply_derivations(self):
        for d in DERIVATIONS:
            sh = self.sheets.get(d.table)
            if sh is None or not sh.rows:
                continue
            if any(sh.table.column(i) is None for i in d.inputs):
                continue
            for row in sh.rows:
                srcs = [row[i] for i in d.inputs]
                val = d.fn(*[s.value for s in srcs])
                cells = tuple(c for s in srcs for c in s.prov.cells)
                notes = [s.prov.note for s in srcs if s.prov.note]
                row[d.name] = Value(
                    val, Provenance(cells, "; ".join(notes) or f"derived: {d.description}"))
            cols = list(sh.table.columns) + [Column(
                d.name, d.dtype, "derived", d.description, tuple(d.inputs))]
            self.sheets[d.table] = Sheet(
                Table(sh.table.name, sh.table.sheet, tuple(cols), sh.table.row_count,
                      sh.table.header_row, sh.table.note),
                sh.rows, sh.excel_rows, sh.unstructured_text)

    def apply_join_derivations(self, left: str, right: str, rows: list[dict[str, Value]]):
        """Run after a join, on the joined rows, in place. Returns the columns added."""
        added = []
        for d in JOIN_DERIVATIONS.get((left, right), ()):
            for row in rows:
                if any(i not in row for i in d.inputs):
                    continue
                srcs = [row[i] for i in d.inputs]
                val = d.fn(*[s.value for s in srcs])
                cells = tuple(c for s in srcs for c in s.prov.cells)
                row[d.name] = Value(val, Provenance(cells, f"derived: {d.description}"))
            added.append(Column(d.name, d.dtype, "derived", d.description, tuple(d.inputs)))
        return added

    # ------------------------------------------------------------------ inspection

    def table(self, name: str) -> Table | None:
        sh = self.sheets.get(name)
        return sh.table if sh else None

    def queryable(self) -> list[Table]:
        return [sh.table for sh in self.sheets.values() if sh.table.columns]

    def unstructured(self) -> dict[str, str]:
        return {n: sh.unstructured_text for n, sh in self.sheets.items()
                if sh.unstructured_text}

    def excluded(self, table: str, column: str) -> list[tuple[int, str]]:
        """Rows whose value for `column` is missing, with the reason. This is what gets read
        out when someone asks why a count is 598 and not 601."""
        sh = self.sheets.get(table)
        if not sh:
            return []
        out = []
        for row, xr in zip(sh.rows, sh.excel_rows):
            v = row.get(column)
            if v is not None and v.value is None:
                out.append((xr, v.prov.note or "missing"))
        return out

    def join_targets(self, table: str) -> dict[str, tuple[str, str]]:
        """Joins the planner is allowed to ask for, keyed by the table joined TO.

        Inferred from shared column names, then filtered to pairs that actually key -- a
        shared name that does not key is a join that silently multiplies rows.
        """
        out = {}
        left = self.sheets.get(table)
        if not left or not left.rows:
            return out
        lcols = {c.name for c in left.table.columns if c.origin == "source"}
        for other, sh in self.sheets.items():
            if other == table or not sh.rows:
                continue
            rcols = {c.name for c in sh.table.columns if c.origin == "source"}
            for shared in sorted(lcols & rcols):
                rvals = [r[shared].value for r in sh.rows]
                if len(set(rvals)) == len(rvals):          # unique on the right => a real key
                    out[other] = (shared, shared)
                    break
        return out

    # ------------------------------------------------------------------ the schema card

    def schema_card(self) -> str:
        """Exactly what the planner is shown. Printed by `--explain` so the room can see that
        the model was never handed the data -- only the shape of it."""
        lines = [f"WORKBOOK  {self.path.name}", ""]
        for t in self.queryable():
            lines.append(f"TABLE {t.name}   ({t.row_count} rows)")
            if t.note:
                lines.append(f"  note: {t.note}")
            for c in t.columns:
                tag = {"source": "", "derived": "  [derived]",
                       "normalised": "  [normalised]"}[c.origin]
                desc = f"  — {c.description}" if c.description else ""
                lines.append(f"    {c.name:<24} {c.dtype:<7}{tag}{desc}")
            joins = self.join_targets(t.name)
            if joins:
                lines.append("    joins: " + ", ".join(
                    f"{k} on {v[0]}" for k, v in joins.items()))
                # ⛔ Columns that only exist AFTER a join must be advertised here, or the
                # planner cannot know they are available and will reach for a raw column and
                # compute the metric wrongly. They were missing from the first version of this
                # card and the margin question planned against `unit_price` alone.
                for other in joins:
                    for d in JOIN_DERIVATIONS.get((t.name, other), ()):
                        lines.append(f"      after join {other}: {d.name:<16} "
                                     f"{d.dtype:<7}  [derived]  — {d.description}")
            lines.append("")
        for name, _text in self.unstructured().items():
            lines.append(f"SHEET {name}   — free text, NOT queryable. "
                         f"Nothing may be computed from it.")
            lines.append("")
        return "\n".join(lines).rstrip()
