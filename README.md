# A data-analysis assistant that cannot state a number it can't point at

Answers questions over a spreadsheet, shows the cells behind every figure, and refuses when the
file can't support an answer. Built for the Coreworks AI take-home.

```bash
make setup      # venv + openpyxl + pytest
make demo       # the five questions, end to end, with cell-level sources
make test       # 31 tests — the two guarantees, asserted
```

No API key needed to run it. No network. ~1,900 lines.

---

## The one-paragraph version

The model never touches a number. It reads a **schema card** — table and column names, types,
and which columns are derived — and emits a **query plan** in a small closed algebra. The plan
is validated against that schema before anything runs; everything after that is deterministic
Python. Every value carries the spreadsheet cells it came from, through filters, joins and
aggregations, so `1,426,304.31` expands into the 156 cells that produced it. Then four gates
run, and the last one re-reads the finished sentence, extracts every numeral, and requires each
one to be a faithful rendering of something actually computed. A number that isn't fails the
answer, and the system says *"I can't answer this from the file."*

## What it does, in the terminal

```
Q1. What was total net revenue by region in Q3 FY2025?

  Across 4 region values where fiscal_year = 2025, fiscal_quarter = Q3,
  the largest net_revenue is South at 1,426,304.31.

  region_norm  net_revenue
  -----------  ------------
  South        1,426,304.31
      region_norm ← Sales!C320, Sales!C324, Sales!C336, … +30 more cells
      net_revenue ← Sales!F320, Sales!G320, Sales!H320, … +102 more cells
  East         1,233,819.40
      net_revenue ← Sales!F314, Sales!G314, … +108 more  [cell is TEXT '5,109.58', read as number]

  gates:
    PASS  plan bound to the schema
    PASS  result has supporting rows
    PASS  all 4 numeric outputs carry source cells
    PASS  every number in the answer reconciles to the result
```

```
Q4. What was our customer churn rate in FY2025?

  I can't answer this from the file.
  planner abstained: This workbook has no churn, subscription, cancellation or retention
  column on any sheet — Sales records orders, not subscription state.
```

Point at any cell and ask what happened to it:

```
$ python demo.py --lineage "Sales!F35"
  column      units
  raw         N/A
  value       None
  note        cell holds 'N/A'; read as missing, not 0
```

---

## Architecture

```
  question
     │
     ▼
 ┌─────────┐   schema card (names and types ONLY — never a value)
 │ planner │◄──────────────────────────────────────────────────┐
 └────┬────┘                                                   │
      │  QueryPlan  — a closed algebra, not SQL                 │
      ▼                                                        │
 ┌──────────┐  binds every name against the schema, or REFUSES  │
 │ validate │                                                  │
 └────┬─────┘                                              ┌───┴────┐
      ▼                                                    │ Store  │
 ┌──────────┐  deterministic. carries CellRefs through     │ cells +│
 │ execute  │  every filter, join and fold                 │ lineage│
 └────┬─────┘                                              └────────┘
      │  ResultSet — every value beside the cells that made it
      ▼
 ┌──────────┐  templated prose, assembled from the plan + the result
 │ compose  │
 └────┬─────┘
      ▼
 ┌──────────┐  4 gates. any one refuses.
 │  verify  │  ① plan bound  ② has support  ③ every number has cells
 └────┬─────┘  ④ every numeral in the prose reconciles to the result
      ▼
   Answer ──────►  renderers/  ·  text  ·  markdown → PDF  ·  slides → PPT
```

| file | what it owns |
|---|---|
| `lineage/model.py` | `CellRef`, `QueryPlan`, `Answer` — the four objects everything is built from |
| `lineage/ingest.py` | XLSX/CSV → typed values, each beside its cell. Where the messy-data judgment lives |
| `lineage/store.py` | derived columns, joins, and the schema card the planner is shown |
| `lineage/plan.py` | the only place a model is involved. `LLMPlanner` + `CachedPlanner` |
| `lineage/execute.py` | validation and the deterministic executor. Provenance survives the fold here |
| `lineage/verify.py` | the four gates |
| `lineage/quality.py` | what the ingester found wrong with the workbook |
| `lineage/renderers/` | text · markdown · slides — three consumers of one `Answer` |

---

## The three decisions worth arguing about

### 1. Text-to-**plan**, not text-to-SQL

The obvious build is: give the model the schema, take back a `SELECT`, run it. I didn't, for one
reason:

> **The set of SQL strings a model can emit is not enumerable, so you cannot validate one.** You
> can only run it and hope. When it's wrong it doesn't crash — it returns *a number*, and a
> wrong number inside a confident sentence is the exact failure this assignment is about.

A closed algebra inverts that. Every name in a `QueryPlan` is bound against the published schema
*before* anything executes, so an unbindable plan is refused rather than run. And because the
executor knows the shape of every operation it performs, it can carry cell provenance through
them — which free SQL forecloses, since you'd be parsing arbitrary SQL to work out which cells
fed which output.

Two properties fall out of the same decision: **lineage is total**, and **injection isn't a
category that exists**.

**The cost, stated plainly:** the algebra is narrower than SQL. No window functions, no
correlated subqueries, no arbitrary expressions. The answer to that is to *widen the algebra
deliberately* — each new operator arrives with its provenance rule — not to fall back to raw SQL
for the hard ones, which would put the guarantee back to zero.

### 2. Lineage is carried, not reconstructed

Every value in the store is a `(value, cells, note)` triple. A `SUM` over 47 rows folds 47
values and keeps the union of their `CellRef`s. So provenance isn't computed after the fact by
re-running a query with different flags — it's the same object the number is.

Derived values point at their **inputs**. `net_revenue` in the workbook is a formula with no
cached value, so the store re-derives it from `units × unit_price × (1 − discount_pct)`, and
its lineage is those three cells plus the arithmetic. That's a better answer than pointing at
the formula cell, because it names the cells the number is actually sensitive to.

I deliberately **don't evaluate spreadsheet formulas**. An evaluator here is a second spreadsheet
engine that has to agree with Excel forever, and when it disagrees it does so silently.

### 3. "Zero hallucination" is a check, not a prompt

Three gates stop the system answering a question it can't serve. None of them stop the failure
that actually happens: the numbers are computed correctly and *the sentence around them is
wrong*. So gate ④ re-reads the finished prose, pulls out every numeral, and requires each to be
a faithful rendering of something in the result.

The reconciliation rule is **rounding at the displayed precision**, not a tolerance band. `46.52`
shown as `47` passes; `46.7` fails. An earlier version used a 0.5% tolerance and it admitted
`46.7` — a number never computed, inside the band, reading as fine. A tolerance wide enough to
be useful is wide enough to pass a wrong figure. There's a test for exactly this
(`test_a_nearby_but_different_number_is_still_caught`).

**Two honest limits**, both worth raising before you do:

- Gate ④ constrains **numbers, not claims**. *"North grew because of the marketplace launch"*
  carries no numeral and would pass. That's why the prose is **templated rather than generated** —
  every noun in it is a column the plan named. Narrower promise, and stated as one.
- The planner can still mis-plan *bindably* — pick `gross_revenue` when you meant
  `net_revenue_calc`. Nothing here catches that, and nothing pretends to. The mitigation is that
  the plan and the row-by-row computation are printed beside the answer, so the mistake is
  visible rather than buried. The real fix is a plan-review step; see *What I'd do with another
  week*.

---

## The dataset, and why it's synthetic

`data/acme_operating_review.xlsx` — a mid-size D2C company's FY2025 operating review. Five
sheets, 601 order rows, formulas, and a merged banner.

A public CSV gives you realism and takes away **control**: you get whatever pathologies it
happens to contain, and you can't prove to a reviewer that the one your demo survives is
actually in there. Here every pathology is **planted, named, and asserted by a test** — so
"it handles messy cells" is a claim with a test behind it rather than a claim behind a lucky
file. `data/make_dataset.py` is seeded and regenerates byte-stable.

`make quality` prints what the ingester found:

| # | Pathology | Where | What the system does |
|---|---|---|---|
| 1 | prices stored as **text** (`"1,299.00"`) | `Sales.unit_price` ×8 | coerced, and the coercion shows up in the answer's source line |
| 2 | **casing/whitespace** variants (`"north "`, `"NORTH"`) | `Sales.region` ×8 | a separate `region_norm` column; the raw cell is never overwritten |
| 3 | `"N/A"` in a numeric column | `Sales.units` ×3 | → NULL, **never 0**; derived values go NULL too |
| 4 | a **formula column with no cached value** | `Sales.net_revenue` ×601 | reported as such, re-derived as a declared column |
| 5 | **merged banner above the header** | `Targets` | header found on row 3 |
| 6 | **`Total` rows inside the data** | `Headcount` ×4 | excluded, and the exclusion is stated |
| 7 | blank spacer rows | `Headcount` | skipped |
| 8 | two SKUs, same name different case | `Products` | collapses to 9 products under `product_name_norm` |
| 9 | a **prose sheet** with no table | `Notes` | held as free text, **not queryable**; the planner is told so |
| 10 | a **duplicated `order_id`** | `Sales` rows 252, 602 | reported, **not silently de-duplicated** — see below |

**The duplicate is the interesting one.** A repeated order id can be a double entry or a genuine
re-order, and the file doesn't say which. Dropping one would change a revenue total on a guess,
so the system reports it and leaves it. That's the whole posture in miniature: surface the
ambiguity, don't resolve it silently.

---

## The five questions

| # | Question | Exercises |
|---|---|---|
| 1 | total net revenue by region in Q3 FY2025 | filter + group over pathologies 1, 2, 4 — a naive `GROUP BY` returns 8 regions |
| 2 | highest average margin % in FY2025 | a **join** + a derived metric spanning two sheets; collapses pathology 8 |
| 3 | Engineering fully-loaded cost across FY2025 | pathology 6 — a naive sum double-counts the `Total` rows |
| 4 | **customer churn rate** | ✋ refused — the quantity isn't in the workbook at all |
| 5 | **revenue forecast for Q1 FY2026** | ✋ refused — every input exists; the **task** is outside the data |

Two refusals for two different reasons, which matters: the first is a missing column, the second
is a question whose inputs are all present and which still can't be answered. A system that only
catches the first kind is doing schema-matching, not abstention.

---

## How PPT and PDF slot in

They're renderers, and the seam is **shipped, not described**.

A renderer is one function: `render(answers: list[Answer]) -> str | bytes`. It receives finished
`Answer` objects — claim, rows, cell provenance, abstention — and **may not compute anything**.
There is no store, no query and no model behind that line. `lineage/pipeline.py` returns
`Answer`s and stops; it doesn't know renderers exist.

Three ship today:

- **`text`** — the terminal demo.
- **`markdown`** → `make report` writes `report.md` with a per-answer *"where these numbers came
  from"* appendix. **A PDF is `pandoc report.md -o report.pdf`.** That's the whole PDF story, and
  it's short because this renderer computes nothing.
- **`slides`** → `make deck` builds the **complete deck structure** — `build(answers) -> list[Slide]`,
  one slide per answer with title, bullets, table and a sources footnote that compresses cell
  references into ranges (`Sales!F311:F466`). It stops one call short of `python-pptx`:

  ```python
  for s in build(answers):                       # ← this function is done and tested
      slide = prs.slides.add_slide(prs.slide_layouts[1])
      slide.shapes.title.text = s.title
      ...                                        # bullets, table, footnote
  ```

  ~40 lines against a structure that already exists, with **no decisions left in it**. All the
  risk in a deck generator is in deciding what a slide *is* for an answer — and that's the part
  that's built.

Two renderers weren't necessary; they're there because a seam with one consumer isn't a seam
you've tested.

**The rule that keeps it true:** a renderer that needs a number the `Answer` doesn't carry must
extend the **pipeline**, never reach past it. The moment a renderer opens the store, the seam is
gone and the next output format is a rewrite again.

**A refused question still gets a slide.** Dropping it would be misleading by selection, which is
the same failure as a wrong number arriving by a different route.

---

## Running it

```bash
make setup
make demo                                    # all five questions
make quality                                 # what's wrong with the workbook
make schema                                  # exactly what the planner sees — no data in it
make report                                  # report.md
make deck                                    # deck.txt
make test                                    # 31 tests

python demo.py --ask "How many orders came through Marketplace in Q2 FY2025?"
python demo.py --lineage "Sales!G9"          # what's in one cell, and what was done to it
```

### The planner, and an honest note about the shipped plans

`demo.py` uses `LLMPlanner` when `ANTHROPIC_API_KEY` is set, and `CachedPlanner` otherwise —
which is why this repo runs end-to-end on a clean clone, and why the demo can't fail in the room
because of a network.

**The five plans in `plans/` were written by a Claude model following `lineage/plan.py:SYSTEM`
verbatim against the real schema card, but not through the Anthropic API on the machine that
built this repo — there was no key on it.** Each file says so in its own `recorded_by` field.
`python record_plans.py` re-records all five through the live API; `--diff` compares without
writing. I'd rather ship the gap named than a sentence asking you to assume otherwise.

`CachedPlanner` does no matching and no inference — an unseen question raises `FileNotFoundError`
telling you to run with a key. A cached planner that could improvise would make the demo a
puppet show.

---

## What I'd do with another week

1. **A plan-review step.** The unguarded failure is a plan that binds but means the wrong thing
   (`gross_revenue` where you wanted `net_revenue_calc`). A second model call that sees only the
   plan and the question — never the data — and says *does this compute what was asked?* is
   cheap, and it's the highest-value thing missing.
2. **Widen the algebra**, with the provenance rule for each operator written first: time
   comparisons (`vs last quarter`), ratios across two aggregates, `HAVING`. Deliberately, one at
   a time, never by reaching for raw SQL.
3. **Ambiguity as a first-class answer.** Right now Q1 silently uses `region_norm`. It should be
   able to say *"there are 8 spellings of region; I grouped on 4 — here's the mapping"* as part
   of the answer rather than in a separate report.
4. **Ship the pptx writer**, against the `build()` that already exists.
5. **A cell-level index for the reverse direction** — *"which answers used `Sales!G158`?"* The
   data is already there; it just isn't indexed that way, and it's what makes the lineage useful
   for auditing rather than only for explaining.
6. **Multi-file joins.** Everything here is one workbook. The `Store` abstraction doesn't assume
   that, but nothing tests it.

---

## Impressions of the product

*(To be written after ~15 minutes on coreworks.ai — one paragraph, per the brief. This is the
one section of the assignment I haven't completed.)*
