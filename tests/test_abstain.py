"""The refusal guarantee: the system says "I can't answer this from the file" rather than guess.

Each gate gets a test that makes it FIRE, because a gate nobody has seen fire is a gate nobody
knows works.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lineage import Store, answer                                          # noqa: E402
from lineage.model import Answer, Cell, Filter, Provenance, QueryPlan, \
    ResultSet, Selection                                                   # noqa: E402
from lineage.plan import CachedPlanner                                     # noqa: E402
from lineage.verify import gate_prose_numbers_cited, run_gates             # noqa: E402

DATA = ROOT / "data" / "acme_operating_review.xlsx"


@pytest.fixture(scope="module")
def store():
    return Store(DATA)


# ------------------------------------------------------------------ gate 1: planner abstains

def test_churn_is_refused_because_the_column_does_not_exist(store):
    a = answer("What was our customer churn rate in FY2025?", store, CachedPlanner())
    assert a.abstained
    assert a.prose == "", "an abstained answer must carry no prose at all"
    assert "churn" in a.abstain_reason.lower()
    assert any(t.startswith("REFUSE") for t in a.trail)


def test_a_forecast_is_refused_even_though_every_input_exists(store):
    """The sharper case: nothing is missing, the TASK is outside the data."""
    a = answer("What is the revenue forecast for Q1 FY2026?", store, CachedPlanner())
    assert a.abstained
    assert "forecast" in a.abstain_reason.lower() or "modelling" in a.abstain_reason.lower()


def test_an_unseen_question_is_refused_not_improvised(store):
    """CachedPlanner must never invent a plan. A demo that improvises is a puppet show."""
    a = answer("What is the average shoe size of our customers?", store, CachedPlanner())
    assert a.abstained
    assert "planner" in a.abstain_reason.lower()


# ------------------------------------------------------------------ gate 2: no support

def test_an_empty_result_is_not_reported_as_zero(store):
    a = answer("unused", store, type("P", (), {
        "name": "stub",
        "plan": lambda self, q, s: QueryPlan(
            table="Sales", select=[Selection("sum", "units")],
            filters=[Filter("region_norm", "=", "Antarctica")])})())
    assert a.abstained
    assert "no supporting rows" in a.abstain_reason
    assert "0" not in a.prose


# ------------------------------------------------------------------ gate 3: orphan number

def test_a_number_with_no_provenance_fails_the_answer():
    res = ResultSet(["total"], [[Cell(42.0, Provenance(()))]])
    a = run_gates(Answer("q", "total = 42.", res, QueryPlan("Sales", [])))
    assert a.abstained
    assert "provenance" in a.abstain_reason


# ------------------------------------------------------------------ gate 4: uncited number

def _res(*values):
    from lineage.model import CellRef
    ref = CellRef("Sales", 2, 7, "G2")
    return ResultSet(["v"], [[Cell(v, Provenance((ref,)))] for v in values])


def test_a_number_not_in_the_result_is_caught():
    g = gate_prose_numbers_cited("Revenue was 1,500,000.", _res(1_426_304.31))
    assert not g.ok
    assert "1,500,000" in g.detail


def test_an_honestly_rounded_number_is_accepted():
    """46.52 shown as '47' is a faithful rendering at the precision displayed."""
    assert gate_prose_numbers_cited("Margin was 47%.", _res(46.52)).ok
    assert gate_prose_numbers_cited("Margin was 46.52%.", _res(46.52)).ok


def test_a_nearby_but_different_number_is_still_caught():
    """The rounding rule must not become a tolerance wide enough to admit a wrong figure."""
    g = gate_prose_numbers_cited("Margin was 46.7%.", _res(46.52))
    assert not g.ok, "46.7 is not what 46.52 rounds to at one decimal place"


def test_a_scaled_quotation_is_accepted():
    assert gate_prose_numbers_cited("Revenue was 1.43 million.", _res(1_426_304.31)).ok


def test_a_numeral_inside_a_data_label_is_allowed():
    """'Cast Iron Skillet 10in' is a name that came from the data, not a claim."""
    from lineage.model import CellRef
    ref = CellRef("Products", 5, 2, "B5")
    res = ResultSet(["product", "m"],
                    [[Cell("Cast Iron Skillet 10in", Provenance((ref,))),
                      Cell(46.52, Provenance((ref,)))]])
    assert gate_prose_numbers_cited("The leader is Cast Iron Skillet 10in at 46.52.", res).ok


def test_a_declared_row_count_is_allowed_but_a_wrong_one_is_not():
    assert gate_prose_numbers_cited("Across 4 regions.", _res(1.0), allow=(4.0,)).ok
    assert not gate_prose_numbers_cited("Across 5 regions.", _res(1.0), allow=(4.0,)).ok


# ------------------------------------------------------------------ the whole set

def test_the_shipped_question_set_splits_three_and_two(store):
    qs = [ln.strip() for ln in (ROOT / "questions.txt").read_text().splitlines()
          if ln.strip() and not ln.startswith("#")]
    answers = [answer(q, store, CachedPlanner()) for q in qs]
    answered = [a for a in answers if not a.abstained]
    refused = [a for a in answers if a.abstained]
    assert len(answered) == 3, [a.question for a in refused]
    assert len(refused) == 2
    assert all(a.result is not None and a.result.rows for a in answered)
    assert all(a.abstain_reason for a in refused), "a refusal must always say why"
