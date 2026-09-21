"""The two guarantees, asserted rather than asserted-about.

    test_lineage.py   every number the system emits is traceable to real cells
    test_abstain.py   the system refuses rather than guesses

⛔ These are the tests that matter. If a change makes one of them fail, the change removed the
   only thing this project claims.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lineage import Store, answer                                   # noqa: E402
from lineage.execute import PlanError, execute, validate            # noqa: E402
from lineage.model import Filter, QueryPlan, Selection              # noqa: E402
from lineage.plan import CachedPlanner                              # noqa: E402

DATA = ROOT / "data" / "acme_operating_review.xlsx"


@pytest.fixture(scope="module")
def store():
    return Store(DATA)


# ------------------------------------------------------------------ the pathologies exist

def test_text_formatted_prices_are_read_as_numbers(store):
    """pathology 1 — 8 unit_price cells are TEXT. They must be summed, and flagged."""
    coerced = [(xr, row["unit_price"].prov.note)
               for row, xr in zip(store.sheets["Sales"].rows, store.sheets["Sales"].excel_rows)
               if "read as number" in (row["unit_price"].prov.note or "")]
    assert len(coerced) == 8, f"expected 8 text-formatted prices, found {len(coerced)}"
    assert all(isinstance(row["unit_price"].value, float)
               for row in store.sheets["Sales"].rows
               if row["unit_price"].value is not None)


def test_region_variants_collapse_to_four(store):
    """pathology 2 — a naive GROUP BY region returns more than four regions."""
    raw = {r["region"].value for r in store.sheets["Sales"].rows}
    norm = {r["region_norm"].value for r in store.sheets["Sales"].rows}
    assert len(raw) > 4, "the dirty variants were not planted"
    assert norm == {"North", "South", "East", "West"}


def test_na_units_are_missing_not_zero(store):
    """pathology 3 — 'N/A' must never become 0; a 0 here silently deflates every average."""
    nulls = [r for r in store.sheets["Sales"].rows if r["units"].value is None]
    assert len(nulls) == 3
    assert all("not 0" in r["units"].prov.note for r in nulls)
    assert all(r["net_revenue_calc"].value is None for r in nulls), \
        "a derived value must be NULL when its input is missing, not 0"


def test_formula_column_is_reported_as_such_not_as_empty(store):
    """pathology 4 — net_revenue is a formula with no cached value."""
    col = store.table("Sales").column("net_revenue")
    assert "EMPTY" in col.description and "formula" in col.description
    cell = store.sheets["Sales"].rows[0]["net_revenue"]
    assert cell.raw.startswith("="), "the formula text must survive ingestion"


def test_targets_header_is_found_below_a_merged_banner(store):
    """pathology 5 — the header is on row 3."""
    t = store.table("Targets")
    assert t.header_row == 3
    assert {c.name for c in t.columns if c.origin == "source"} == {
        "region", "quarter", "revenue_target"}


def test_subtotal_rows_are_excluded(store):
    """pathology 6 — four 'Total' rows sit inside Headcount and must not be summed."""
    assert "subtotal" in store.table("Headcount").note
    labels = {r["department"].value for r in store.sheets["Headcount"].rows}
    assert "Total" not in labels
    assert store.table("Headcount").row_count == 48, "4 depts x 12 months, no totals"


def test_notes_sheet_is_not_invented_into_a_table(store):
    """pathology 9 — prose must not become a one-column table the planner can query."""
    assert "Notes" in store.unstructured()
    assert store.table("Notes").columns == ()
    assert all(t.name != "Notes" for t in store.queryable())


def test_duplicate_order_id_is_reported_not_dropped(store):
    from lineage.quality import report
    r = report(store)
    assert "duplicated" in r and "ORD-" in r
    assert "NOT de-duplicated" in r


# ------------------------------------------------------------------ lineage is total

def test_every_number_in_every_answer_has_source_cells(store):
    """THE GUARANTEE. Run all five questions; no numeric output may lack provenance."""
    planner = CachedPlanner()
    qs = [ln.strip() for ln in (ROOT / "questions.txt").read_text().splitlines()
          if ln.strip() and not ln.startswith("#")]
    checked = 0
    for q in qs:
        a = answer(q, store, planner)
        if a.result is None:
            continue
        for row in a.result.rows:
            for cell in row:
                if isinstance(cell.value, float):
                    assert cell.provenance.cells, f"{q}: a number with no source cells"
                    checked += 1
    assert checked > 0


def test_a_sum_names_every_cell_that_fed_it(store):
    """A SUM over N rows must carry N source cells — not one, not a range, all of them."""
    plan = QueryPlan(table="Headcount",
                     select=[Selection("sum", "fully_loaded_cost", "total")],
                     filters=[Filter("department_norm", "=", "Engineering")])
    res = execute(plan, store)
    cell = res.rows[0][0]
    assert len(cell.provenance.cells) == 12, \
        f"12 monthly cells fed this sum; provenance names {len(cell.provenance.cells)}"
    assert all(c.sheet == "Headcount" for c in cell.provenance.cells)


def test_derived_value_points_at_its_inputs_not_at_nothing(store):
    """net_revenue_calc has no cell of its own; its provenance is units + price + discount."""
    row = next(r for r in store.sheets["Sales"].rows if r["net_revenue_calc"].value is not None)
    cells = row["net_revenue_calc"].prov.cells
    assert len(cells) == 3
    assert {c.addr[0] for c in cells} == {"F", "G", "H"}


def test_join_derived_margin_spans_both_sheets(store):
    """margin_pct comes from Sales.unit_price and Products.cost_price — provenance must say so."""
    plan = QueryPlan(table="Sales",
                     select=[Selection("avg", "margin_pct", "m")],
                     joins=[__import__("lineage.model", fromlist=["Join"]).Join(
                         "Products", "sku", "sku")],
                     group_by=["sku_norm"])
    res = execute(plan, store)
    sheets = {c.sheet for row in res.rows for cell in row for c in cell.provenance.cells}
    assert sheets == {"Sales", "Products"}


# ------------------------------------------------------------------ the plan is closed

def test_an_unknown_column_is_refused_not_guessed(store):
    with pytest.raises(PlanError, match="unknown column"):
        validate(QueryPlan(table="Sales", select=[Selection("sum", "revenue")]), store)


def test_an_unknown_table_is_refused(store):
    with pytest.raises(PlanError, match="no queryable table"):
        validate(QueryPlan(table="Revenue", select=[Selection("sum", "units")]), store)


def test_a_join_without_a_key_is_refused(store):
    from lineage.model import Join
    with pytest.raises(PlanError):
        validate(QueryPlan(table="Sales", select=[Selection("sum", "units")],
                           joins=[Join("Headcount", "sku", "department")]), store)


def test_the_notes_sheet_cannot_be_queried(store):
    with pytest.raises(PlanError, match="no queryable table"):
        validate(QueryPlan(table="Notes", select=[Selection("count", "*")]), store)


# ------------------------------------------------------------------ the renderers

def test_every_renderer_consumes_the_same_answers(store):
    """The seam: three renderers, one input, none of them touching the store."""
    from lineage.renderers import REGISTRY
    planner = CachedPlanner()
    qs = [ln.strip() for ln in (ROOT / "questions.txt").read_text().splitlines()
          if ln.strip() and not ln.startswith("#")]
    answers = [answer(q, store, planner) for q in qs]
    for name, fn in REGISTRY.items():
        out = fn(answers, title="t", source_file="f.xlsx")
        assert isinstance(out, str) and out.strip(), f"{name} rendered nothing"


def test_slide_citations_name_the_right_columns(store):
    """A footnote that cites the same range four times is not a citation."""
    from lineage.renderers.slides import build
    a = answer("What was total net revenue by region in Q3 FY2025?", store, CachedPlanner())
    slide = next(s for s in build([a]) if s.kind == "finding")
    ranges = [r.strip() for r in slide.footnote.replace("Source: ", "").split(",")]
    assert len(ranges) == len(set(ranges)), f"duplicate ranges in citation: {ranges}"
    # a range is "C311:C466" -- take the letters of its START only, not of both ends
    letters = {"".join(ch for ch in r.split("!")[1].split(":")[0] if ch.isalpha())
               for r in ranges}
    assert letters == {"C", "F", "G", "H"}, f"wrong columns cited: {letters}"


def test_a_refused_question_still_gets_a_slide(store):
    """Dropping refusals from a deck is misleading by selection."""
    from lineage.renderers.slides import build
    a = answer("What was our customer churn rate in FY2025?", store, CachedPlanner())
    deck = build([a])
    assert any(s.kind == "refusal" for s in deck)
