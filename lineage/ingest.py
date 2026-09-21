"""XLSX/CSV -> a tidy store where every value still knows which cell it came from.

THE ONE IDEA
    A normal loader turns a sheet into a DataFrame and the cell addresses are gone. Here every
    value is stored beside its CellRef, so the address survives every filter, join and SUM. It
    costs one extra column per data column and it is the reason "where did this number come
    from?" has a real answer at the far end of a pipeline rather than a plausible one.

WHAT IT REFUSES TO DO
    * It never guesses that a sheet is a table. Notes is prose; the header finder rejects it and
      the sheet is recorded as UNSTRUCTURED, which is a fact the planner can then use to abstain
      rather than a sheet silently missing from the schema.
    * It never coerces "N/A" to 0. It coerces to NULL and records the note. A zero invented here
      is a wrong number three layers downstream with a perfect-looking lineage trail.
    * It never drops a row it did not understand. A row it cannot type is kept, flagged, and
      excluded from aggregates -- and `store.excluded()` will list them in the room.
"""
from __future__ import annotations

import csv
import datetime as _dt
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from .model import CellRef, Column, Provenance, Table

#: a subtotal row parked inside the data (pathology 6). Matched on the LABEL column, never on
#: a numeric heuristic -- "this row is bigger than the others" is how a real month gets dropped.
SUBTOTAL_LABELS = {"total", "totals", "subtotal", "sub-total", "grand total", "sum"}

_NUM_RE = re.compile(r"^-?[\d,]*\.?\d+$")
_NULLISH = {"", "n/a", "na", "-", "--", "null", "none", "nil", "#n/a", "tbd"}


class Value:
    """One typed value plus where it came from and what was done to it."""

    __slots__ = ("value", "prov", "raw", "excluded")

    def __init__(self, value, prov: Provenance, raw=None, excluded: bool = False):
        self.value = value
        self.prov = prov
        self.raw = raw
        self.excluded = excluded

    def __repr__(self):
        return f"Value({self.value!r} @ {self.prov})"


def _coerce(raw, ref: CellRef) -> Value:
    """Type one cell. The NOTE is the product here, as much as the value."""
    if raw is None:
        return Value(None, Provenance((ref,), "empty cell"))

    if isinstance(raw, bool):
        return Value(raw, Provenance((ref,)))

    if isinstance(raw, (int, float)):
        return Value(float(raw), Provenance((ref,)))

    if isinstance(raw, (_dt.datetime, _dt.date)):
        d = raw.date() if isinstance(raw, _dt.datetime) else raw
        return Value(d, Provenance((ref,)))

    s = str(raw).strip()

    if s.lower() in _NULLISH:
        # pathology 3 -- "N/A" is MISSING, and missing is not zero.
        return Value(None, Provenance((ref,), f"cell holds {raw!r}; read as missing, not 0"),
                     raw=raw)

    if s.startswith("="):
        # pathology 4 -- a formula with no cached value. We keep the formula text so the room
        # can see it, and we do NOT evaluate it: an evaluator here is a second spreadsheet
        # engine that has to agree with Excel forever.
        return Value(None, Provenance((ref,), f"formula {s} with no cached value"), raw=s,
                     excluded=True)

    cleaned = s.replace(",", "").replace(" ", "")
    if _NUM_RE.match(cleaned):
        # pathology 1 -- a number typed as text. The coercion is recorded, never silent.
        return Value(float(cleaned), Provenance((ref,), f"cell is TEXT {raw!r}, read as number"),
                     raw=raw)

    try:
        return Value(_dt.date.fromisoformat(s), Provenance((ref,)))
    except ValueError:
        pass

    return Value(s, Provenance((ref,)))


def _normalise_text(v: str) -> str:
    """pathology 2 -- 'north ', 'NORTH' and 'North' are one region.

    Stored as a SEPARATE normalised column, never over the top of the source value, so the
    room can still see what was actually typed in the cell.
    """
    return re.sub(r"\s+", " ", v).strip().title()


def _find_header(ws, max_scan: int = 12) -> int | None:
    """The header row, which is not always row 1 (pathology 5).

    A header row is the first row that is at least 2 cells wide, entirely text, has no blanks
    inside its span, and is followed by a row that is NOT entirely text. The last clause is
    what stops a prose sheet from being read as a one-column table.
    """
    best = None
    for r in range(1, min(ws.max_row, max_scan) + 1):
        vals = [ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
        span = [v for v in vals if v is not None]
        if len(span) < 2:
            continue
        first = next(i for i, v in enumerate(vals) if v is not None)
        width = len(span)
        contiguous = all(v is not None for v in vals[first:first + width])
        if not contiguous or not all(isinstance(v, str) for v in span):
            continue
        nxt = [ws.cell(row=r + 1, column=c).value for c in range(first + 1, first + 1 + width)]
        if all(v is None for v in nxt):
            continue
        if all(isinstance(v, str) for v in nxt if v is not None) and len(
                [v for v in nxt if v is not None]) == width:
            # every cell under the header is text too -- prose, or a second banner
            continue
        best = r
        break
    return best


class Sheet:
    """One ingested sheet: typed rows, each carrying its own Excel row number."""

    def __init__(self, table: Table, rows: list[dict[str, Value]], excel_rows: list[int],
                 unstructured_text: str | None = None):
        self.table = table
        self.rows = rows
        self.excel_rows = excel_rows
        self.unstructured_text = unstructured_text

    @property
    def name(self) -> str:
        return self.table.name


def _ingest_worksheet(ws, ws_formula=None) -> Sheet:
    """`ws` is the data_only view (cached values); `ws_formula` is the same sheet loaded with
    formulas visible. Both are needed and neither is sufficient:

      * data_only gives you the number Excel last computed -- and NOTHING if the file was
        written by a library rather than by Excel, which is when the cache is never populated.
      * the formula view gives you "=F158*G158*(1-H158)", which tells you what the column MEANS
        but is not a value.

    Reading both lets the store say "this column is a formula the workbook never cached",
    which is a true and useful statement, instead of "this column is empty", which is not.
    """
    header_row = _find_header(ws)
    if header_row is None:
        # pathology 9 -- prose. Recorded as unstructured; NOT invented into a table.
        text = "\n".join(
            str(ws.cell(row=r, column=1).value or "") for r in range(1, ws.max_row + 1))
        tbl = Table(name=ws.title, sheet=ws.title, columns=(), row_count=0, header_row=0,
                    note="no tabular structure found — held as free text, not queryable")
        return Sheet(tbl, [], [], unstructured_text=text.strip())

    headers: list[tuple[int, str]] = []
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=header_row, column=c).value
        if isinstance(v, str) and v.strip():
            headers.append((c, v.strip()))

    rows: list[dict[str, Value]] = []
    excel_rows: list[int] = []
    skipped_subtotal = 0
    for r in range(header_row + 1, ws.max_row + 1):
        cells = {}
        blank = True
        for c, name in headers:
            ref = CellRef(ws.title, r, c, f"{get_column_letter(c)}{r}")
            raw = ws.cell(row=r, column=c).value
            formula = None
            if ws_formula is not None:
                fv = ws_formula.cell(row=r, column=c).value
                if isinstance(fv, str) and fv.startswith("="):
                    formula = fv
            if raw is not None and str(raw).strip() != "":
                blank = False
            elif formula is not None:
                blank = False
            v = _coerce(raw, ref)
            if formula is not None and v.value is None:
                # The cell IS a formula and the workbook carries no cached result for it.
                # ⛔ We do not evaluate it: an evaluator here is a second spreadsheet engine
                # that has to agree with Excel forever, and when it disagrees it does so
                # silently. The store re-derives the quantity as a DECLARED derived column
                # instead (store.DERIVATIONS), where the arithmetic is visible and tested.
                v = Value(None, Provenance((ref,),
                                           f"formula {formula} — workbook holds no cached "
                                           f"value; see the declared derived column"),
                          raw=formula, excluded=True)
            elif formula is not None:
                v = Value(v.value, Provenance((ref,), f"cached value of formula {formula}"),
                          raw=formula)
            cells[name] = v
        if blank:
            continue                                  # pathology 7 -- spacer row
        labels = [str(v.value).strip().lower() for v in cells.values()
                  if isinstance(v.value, str)]
        if any(l in SUBTOTAL_LABELS for l in labels):
            skipped_subtotal += 1                     # pathology 6 -- a Total row in the data
            continue
        rows.append(cells)
        excel_rows.append(r)

    columns: list[Column] = []
    for _c, name in headers:
        sample = [row[name].value for row in rows if row[name].value is not None][:40]
        if not sample:
            # Every cell in this column coerced to NULL. Reporting it as "text" would be a
            # lie the planner could act on, so it is reported as EMPTY with the reason -- the
            # workbook's net_revenue column lands here, being formulas with no cached value.
            reasons = sorted({row[name].prov.note for row in rows if row[name].prov.note})[:1]
            columns.append(Column(name=name, dtype="text", origin="source",
                                  description="EMPTY — no value in any row"
                                              + (f"; {reasons[0]}" if reasons else "")))
            continue
        if all(isinstance(v, float) for v in sample):
            dt = "number"
        elif all(isinstance(v, (_dt.date,)) for v in sample):
            dt = "date"
        elif all(isinstance(v, bool) for v in sample):
            dt = "bool"
        else:
            dt = "text"
        columns.append(Column(name=name, dtype=dt, origin="source"))
        if dt == "text":
            columns.append(Column(
                name=f"{name}_norm", dtype="text", origin="normalised",
                normalised_from=name,
                description=f"case- and whitespace-normalised {name}; groups on this, "
                            f"points at the same cell"))

    for row in rows:
        for col in columns:
            if col.origin == "normalised":
                src = row[col.normalised_from]
                row[col.name] = Value(
                    _normalise_text(src.value) if isinstance(src.value, str) else src.value,
                    src.prov)

    note = ""
    if skipped_subtotal:
        note = (f"{skipped_subtotal} subtotal row(s) inside the data were excluded from the "
                f"store — they would have been double-counted by any aggregate")
    if header_row > 1:
        note = (note + "; " if note else "") + f"header is on row {header_row}, not row 1"

    tbl = Table(name=ws.title, sheet=ws.title, columns=tuple(columns),
                row_count=len(rows), header_row=header_row, note=note)
    return Sheet(tbl, rows, excel_rows)


def _ingest_csv(path: Path) -> Sheet:
    name = path.stem
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = list(csv.reader(fh))
    if not reader:
        return Sheet(Table(name, name, (), 0, 0, "empty file"), [], [])
    headers = [(i + 1, h.strip()) for i, h in enumerate(reader[0]) if h.strip()]
    rows, excel_rows = [], []
    for r_i, raw_row in enumerate(reader[1:], start=2):
        if not any(str(x).strip() for x in raw_row):
            continue
        cells = {}
        for c, hname in headers:
            raw = raw_row[c - 1] if c - 1 < len(raw_row) else None
            ref = CellRef(name, r_i, c, f"{get_column_letter(c)}{r_i}")
            cells[hname] = _coerce(raw, ref)
        labels = [str(v.value).strip().lower() for v in cells.values()
                  if isinstance(v.value, str)]
        if any(l in SUBTOTAL_LABELS for l in labels):
            continue
        rows.append(cells)
        excel_rows.append(r_i)

    columns = []
    for _c, hname in headers:
        sample = [row[hname].value for row in rows if row[hname].value is not None][:40]
        dt = "number" if sample and all(isinstance(v, float) for v in sample) else "text"
        columns.append(Column(hname, dt, "source"))
        if dt == "text":
            columns.append(Column(f"{hname}_norm", "text", "normalised", normalised_from=hname))
    for row in rows:
        for col in columns:
            if col.origin == "normalised":
                src = row[col.normalised_from]
                row[col.name] = Value(
                    _normalise_text(src.value) if isinstance(src.value, str) else src.value,
                    src.prov)
    return Sheet(Table(name, name, tuple(columns), len(rows), 1), rows, excel_rows)


def ingest(path: str | Path) -> list[Sheet]:
    """Read one workbook or CSV into sheets. No side effects, no network, no model."""
    p = Path(path)
    if p.suffix.lower() in (".csv", ".tsv"):
        return [_ingest_csv(p)]
    wb = load_workbook(p, data_only=True, read_only=False)
    wbf = load_workbook(p, data_only=False, read_only=False)
    return [_ingest_worksheet(wb[name], wbf[name]) for name in wb.sheetnames]
