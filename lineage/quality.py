"""What the ingester found wrong with the workbook, stated up front.

⭐ WHY THIS IS A FEATURE AND NOT A DEBUG SCRIPT
    In the room the question "what is messy in this file?" arrives before "what is the answer?",
    and the difference between a system that survives messy data and one that got lucky is
    whether it can TELL YOU what it survived. Everything below is a by-product of ingestion --
    the notes were already attached to the cells -- so this report costs one pass and invents
    nothing.

⛔ It does not clean anything. A report that silently fixed what it found would put the
   judgment back where nobody can see it.
"""
from __future__ import annotations

from collections import Counter

from .store import Store


def report(store: Store) -> str:
    out = [f"DATA QUALITY — {store.path.name}", ""]

    for sh in store.sheets.values():
        t = sh.table
        if sh.unstructured_text:
            out += [f"{t.name}", f"  free text, not queryable — "
                                 f"{len(sh.unstructured_text.splitlines())} lines held as-is",
                    "  ⛔ nothing may be computed from it, and the planner is told so", ""]
            continue
        out.append(f"{t.name}   ({t.row_count} rows kept)")
        if t.note:
            out.append(f"  structure: {t.note}")

        notes = Counter()
        for row in sh.rows:
            for col, v in row.items():
                n = v.prov.note
                if not n or n.startswith("derived"):
                    continue
                kind = ("TEXT read as number" if "read as number" in n else
                        "missing, not zero" if "read as missing" in n else
                        "formula, no cached value" if "no cached" in n else
                        "cached formula value" if "cached value of" in n else n[:40])
                notes[(col, kind)] += 1
        for (col, kind), n in sorted(notes.items(), key=lambda kv: -kv[1]):
            out.append(f"  {n:>4} x  {col}: {kind}")

        # text columns whose raw spelling varies but whose normalised form does not
        for col in [c.name for c in t.columns if c.origin == "normalised"]:
            src = t.column(col).normalised_from
            raw = {row[src].value for row in sh.rows if isinstance(row[src].value, str)}
            norm = {row[col].value for row in sh.rows if isinstance(row[col].value, str)}
            if len(raw) > len(norm):
                out.append(f"  {len(raw) - len(norm):>4} x  {src}: spelling variants collapsed "
                           f"by {col} ({len(raw)} raw -> {len(norm)} distinct)")

        # exact duplicate rows on a column that looks like an identifier
        for c in t.columns:
            if c.origin != "source" or not c.name.lower().endswith("_id"):
                continue
            vals = [row[c.name].value for row in sh.rows if row[c.name].value is not None]
            dupes = [v for v, n in Counter(vals).items() if n > 1]
            if dupes:
                where = []
                for d in dupes[:3]:
                    rows = [xr for row, xr in zip(sh.rows, sh.excel_rows)
                            if row[c.name].value == d]
                    where.append(f"{d} (rows {', '.join(map(str, rows))})")
                out.append(f"  {len(dupes):>4} x  {c.name}: duplicated — {'; '.join(where)}")
                out.append("         ⚠️  NOT de-duplicated. A repeated id can be a double entry "
                           "or a genuine re-order,")
                out.append("             and this file does not say which. Dropping one would "
                           "change a total on a guess.")
        out.append("")
    return "\n".join(out).rstrip()
