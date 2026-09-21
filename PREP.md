# PREP — the Coreworks walkthrough, in active recall

**How to use this.** Every heading is a question you will actually be asked. **Answer it out
loud before you open the toggle.** Reading the answer feels like preparation and isn't — the
whole point is production under a cold start, which is the only thing the room tests.

Three passes: **① cold**, no toggles, mark what you couldn't produce · **② only the marked
ones** · **③ the four Numbers cards, verbatim, until they arrive without effort.**

> **The round:** office, laptop, short demo → architecture and implementation discussion.
> Stated probes: *"where did this number come from?"*, *"what happens if I ask X?"*,
> *"why this approach over Y?"* — plus the one the Team Lead already told you is coming:
> ***"if you had to build this from scratch, how would you?"***

---

## §0 · The three things that cost you R0 — read this before anything else

R0's verdict was **not** "he doesn't know the material." It was *"I can't tell how much of this is
his, how big any of it is, or whether he checks what already exists before building."*

Three habits, each with a mechanical fix. **They matter more in this round than any architecture
answer, because this round has an artifact and R0 didn't.**

| # | The habit | The fix, mechanically |
|---|---|---|
| 1 | **Six systems described, not one scale number spoken.** The only figure in 23 minutes was `$38K → $18K`. | **Every system you name gets a number in the same breath.** Not the next sentence — the same one. §5 drills the four. |
| 2 | **The boundary was never drawn.** The deep-research engine, price-comparison engine and top-N ranking that #27 consumes are **not yours**, and under a direct *"hard to believe one person built so many things"* you answered with more of what you built. | **Volunteer the boundary before you're asked.** "I built X; Y was already there and I consumed it." Saying what isn't yours is the single fastest credibility move available to you. |
| 3 | **Build-vs-buy probed three times; you named alternatives once.** "I wrote it myself" twice, with no alternative named. | **Every build decision ships with the thing you rejected and why.** This repo is now full of them — §2 and §3 are nothing else. |

> **The frame for the whole round:** *you optimised for coverage; the round scored conviction.*
> **One system proven beats six listed.** This time you have one system, and it is proven —
> so the trade is already made. Don't reopen it by listing.

---

## §1 · The demo — drive it, don't narrate it

<details><summary><b>Q. Open the demo. What do you run, in what order, and why that order?</b></summary>

```bash
make schema      # 1. what the planner sees — and it is not the data
make quality     # 2. what's wrong with this workbook
make demo        # 3. the five questions
make test        # 4. the guarantees, as tests
```

**Say why the order is the order:** it walks the trust chain backwards from their scepticism.
First *the model never sees a value* (schema). Then *I know what's broken in here* (quality).
Only then the answers — so by the time a number appears they already know what it survived.
Ending on `make test` closes it: **the two claims are tests, not adjectives.**

⛔ Don't start with `make demo`. A number arriving before the provenance story is a number
they have to take on trust, which is the thing you're there to disprove.
</details>

<details><summary><b>Q. Which single screen do you want them looking at longest?</b></summary>

**Q1's output with sources on.** It carries all four proofs at once:

- the lineage lines (`net_revenue ← Sales!F320, Sales!G320, Sales!H320, … +102 more cells`)
- a **coercion surfaced inside the answer** — `[cell is TEXT '5,109.58', read as number]`
- the four gates, listed, passing
- `computed: 601 rows → filter → 156 rows → grouped by region_norm → 4 groups`

Then say the one sentence that makes it land: **"a naive `GROUP BY region` on this file returns
eight regions, not four."** That's the moment the messy-data handling becomes a fact instead of a
claim.
</details>

<details><summary><b>Q. They say "pick a number — where did that come from?" What do you do with your hands?</b></summary>

Don't explain. **Run it.**

```bash
python demo.py --lineage "Sales!G9"
#   column      unit_price
#   raw         4,284.48
#   value       4284.48
#   note        cell is TEXT '4,284.48', read as number
```

Then open the workbook at `G9` and let them see the same thing. **The answer to "where did this
come from" is a cell reference and an open spreadsheet, not a paragraph.**
</details>

<details><summary><b>Q. "What happens if I ask X?" — they pick something you've never run. What's the move?</b></summary>

`python demo.py --ask "<their question>"` — and **say the constraint out loud before you press
enter**, because it turns a possible failure into a demonstration either way:

> "Without a key it'll replay a recorded plan, and if it's never seen this question it'll
> refuse rather than improvise — that's deliberate. With a key it plans live."

- **Refuses:** that *is* the abstention story. `CachedPlanner` does no matching and no
  inference — a cached planner that could improvise would make the whole demo a puppet show.
- **Live (key set):** even better — the plan is printed, and the gates run on it.

⛔ Never say "it should work." Either set `ANTHROPIC_API_KEY` before you walk in, or state the
cached behaviour up front. **A surprise in your own demo is the one thing that cannot be
recovered.**
</details>

---

## §2 · Architecture — the decisions, and what you rejected

<details><summary><b>Q. Describe the architecture in under 60 seconds.</b></summary>

> "A question goes to a planner that only ever sees a **schema card** — table and column names,
> types, which columns are derived. Never a value. It emits a **query plan** in a small closed
> algebra, not SQL. The plan is **validated against that schema before anything runs**;
> everything after that is deterministic Python. Every value in the store carries the cells it
> came from, and that provenance survives filters, joins and aggregation — so a sum over 156
> rows arrives knowing all 156 cells. Then four gates run. The last one re-reads the finished
> sentence, pulls out every numeral, and requires each to be a faithful rendering of something
> actually computed. Anything that fails, the system says *I can't answer this from the file.*"

**Then stop.** Don't tour the files.
</details>

<details><summary><b>Q. ⭐ "Why this approach over text-to-SQL?" — the question they will definitely ask</b></summary>

**The one sentence:**

> "The set of SQL strings a model can emit isn't enumerable, so you can't validate one — you can
> only run it and hope. And when it's wrong it doesn't crash, it returns *a number*."

Then the two consequences, which are the same decision seen twice:

1. **Validation becomes total.** Every name in a plan binds against the published schema *before*
   execution. Unbindable ⇒ refused, not run.
2. **Lineage becomes possible at all.** The executor knows the shape of every operation it
   performs, so it can carry cell references through them. With free SQL you'd be parsing
   arbitrary SQL to work out which cells fed which output.

Injection stops being a category that exists — say that **third**, as a by-product, not as the
headline. It's the weakest of the three and leading with it makes the answer sound like security
theatre.

**⭐ Then volunteer the cost before they find it** (this is fix #3 from §0, executed):

> "It's narrower than SQL. No window functions, no correlated subqueries, no arbitrary
> expressions. The answer is to widen the algebra deliberately — each new operator arrives with
> its provenance rule — not to fall back to raw SQL for the hard ones, because that puts the
> guarantee back to zero."
</details>

<details><summary><b>Q. "Why not just have the LLM read the data and answer?"</b></summary>

Three reasons, in ascending order of how much they matter:

1. **It doesn't fit.** 601 rows here; a real workbook is 100k.
2. **It's not reproducible.** Same question, different arithmetic, no way to diff.
3. **⭐ It destroys lineage, which is the actual requirement.** A number produced inside a
   context window has no cell behind it — you can ask the model where it came from and it will
   *say* a cell, which is strictly worse than not answering, because now it looks sourced.

Land it: **"the model does the half where being wrong is detectable — understanding the
question. It's removed from the half where being wrong is invisible."**
</details>

<details><summary><b>Q. "Why is the prose templated? Wouldn't a second LLM call read better?"</b></summary>

> "It would, and it would also be a second place a claim can be invented. Gate ④ constrains
> **numbers**, not claims — *'North grew because of the marketplace launch'* carries no numeral
> and would sail through. So the sentence is assembled from the plan and the result: every noun
> in it is a column the plan named. It's a narrower promise than the gate, and I'd rather state
> it than have it quietly not hold."

**This is a strong answer because it volunteers a limitation.** Deliver it as a decision, not an
apology.
</details>

<details><summary><b>Q. Why derive <code>net_revenue</code> instead of evaluating the formula?</b></summary>

The workbook's `net_revenue` is `=F2*G2*(1-H2)` with **no cached value** — openpyxl's
`data_only` view returns `None`, because a file written by a library never had Excel populate
the cache.

> "I read the workbook twice — once for cached values, once for formulas — so the store can say
> *'this is a formula the workbook never cached'*, which is true and useful, instead of *'this
> column is empty'*, which isn't."

**Why not evaluate it:**

> "An evaluator here is a second spreadsheet engine that has to agree with Excel forever, and
> when it disagrees it does so silently."

So it's re-derived as a **declared** derived column, and its lineage is the three input cells
plus the arithmetic — **which is a better answer than pointing at the formula cell, because it
names the cells the number is actually sensitive to.**
</details>

<details><summary><b>Q. "Where does the model fit? What exactly does it see?"</b></summary>

`make schema` — show them. Then:

> "Names, types, descriptions, which columns are derived and which joins key. **Not one value.**
> It emits JSON. It never sees a number and it never writes one."

⭐ **The fact to have ready:** the schema card *also* advertises columns that only exist **after
a join** (`margin_pct`, `gross_profit`). They were missing from the first version and the margin
question planned against `unit_price` alone — a plan that bound cleanly and computed the wrong
thing. **Offer this unprompted.** It shows you found it, and it's a real bug with a real fix.
</details>

---

## §3 · Lineage and abstention — the two guarantees

<details><summary><b>Q. How does provenance survive a <code>SUM</code>?</b></summary>

Every value is `(value, cells, note)`. An aggregate **folds** over the contributing values and
keeps the **union of their `CellRef`s** — so a sum over 47 rows carries 47 cells.

> "Provenance isn't reconstructed after the fact by re-running the query with a flag. It's the
> same object the number is."

There's a test that asserts a 12-month Engineering sum names exactly 12 cells —
`test_a_sum_names_every_cell_that_fed_it`.
</details>

<details><summary><b>Q. A derived value has no cell of its own. What does it point at?</b></summary>

**Its inputs, and it must never point at nothing.** `net_revenue_calc` → the `units`,
`unit_price` and `discount_pct` cells of that row. `margin_pct` spans **two sheets** —
`Sales.unit_price` and `Products.cost_price` — and the test asserts the provenance set contains
both sheet names.

Gate ③ makes it structural: **a numeric output with an empty provenance set fails the answer.**
</details>

<details><summary><b>Q. ⭐ Name the four gates, in order.</b></summary>

1. **plan bound** — the plan binds to the schema (or the planner abstained outright)
2. **has support** — the query matched rows. *An empty match is not a zero.*
3. **every number has cells** — no numeric output without provenance
4. **every numeral reconciles** — re-read the prose; each numeral must be a faithful rendering
   of something computed

**First failure wins, and the prose is discarded** — an abstained answer carries no sentence at
all, so there's nothing to misread.
</details>

<details><summary><b>Q. ⭐ Gate ④: why rounding-at-displayed-precision and not a tolerance band?</b></summary>

**This is your best single anecdote. Have it ready and tell it as a bug you found.**

> "It started as a 0.5% tolerance. Against a computed 46.52 that admits **46.7** — a number I
> never produced, sitting inside the band, reading as perfectly fine. A tolerance wide enough to
> be useful is wide enough to pass a wrong figure. So the only question asked now is *is this
> what one of our numbers rounds to at the precision it's shown to* — 46.52 displayed as 47
> passes, 46.7 fails. There's a test named exactly that."

`test_a_nearby_but_different_number_is_still_caught`.

**Why it lands:** it's a real defect, found by your own test, with a fix that made the guarantee
*stronger* rather than more permissive. That is the shape of answer this interviewer scored you
down for not having in R0.
</details>

<details><summary><b>Q. Why are there two unanswerable questions, not one?</b></summary>

Because they fail for **different reasons**, and a system that only catches the first is doing
schema-matching rather than abstention.

- **Churn** — the quantity isn't in the workbook at all. A missing column.
- **Q1 FY2026 forecast** — **every input exists.** Orders, dates, regions, all there. The
  **task** is outside the data: producing a number would be modelling, not reading.

> "The second one is the harder case, and it's the one that separates abstention from
> schema-matching."
</details>

<details><summary><b>Q. "What if it refuses something it could have answered?"</b></summary>

Concede it immediately, then bound it:

> "It will, and that's the trade I chose. A false refusal costs a follow-up; a false answer costs
> the trust in every other number on the screen. **The gates are ordered so refusals are
> explainable** — it always says which gate fired and why, so a wrong refusal is a bug report
> with a stack trace, not a shrug."

⭐ And volunteer the mitigation: *"the fix for over-refusal is a wider algebra, which is item 2
on my week-two list — not a looser gate."*
</details>

<details><summary><b>Q. ⛔ The hardest question they can ask: "what does this NOT protect against?"</b></summary>

**Answer it fully and first — do not let them extract it.** Volunteering this is worth more than
any feature.

> "A plan that **binds but means the wrong thing.** If it picks `gross_revenue` where you meant
> `net_revenue_calc`, every gate passes: the plan is valid, the rows exist, the cells are real,
> the prose reconciles. The number is right for the query it ran and wrong for the question you
> asked. **Nothing here catches that.**
>
> What it does is make it **visible** — the plan and the row-by-row computation are printed
> beside the answer, so it's an inspectable mistake rather than a buried one. The real fix is a
> **plan-review step**: a second model call that sees only the question and the plan, never the
> data, and answers *does this compute what was asked?* That's item 1 on the week-two list, and
> it's the highest-value thing missing."

Second, smaller one: **gate ④ constrains numbers, not causal claims** — handled by templating the
prose, which is a narrower promise and stated as one.
</details>

---

## §4 · Extensibility — the "not a rewrite" claim

<details><summary><b>Q. "Convince me PPT generation isn't a rewrite."</b></summary>

⛔ **Don't argue. Run `make deck`.** It prints the full deck structure — slides, titles,
bullets, tables, source footnotes.

> "A renderer is one function: finished `Answer` objects in, bytes out. It **may not compute
> anything** — no store, no query, no model behind that line. The pipeline returns `Answer`s and
> stops; it doesn't know renderers exist."

Then the concrete part:

> "`build(answers) -> list[Slide]` is done and tested. What's left is the python-pptx loop —
> about forty lines, against a structure that already exists, **with no decisions left in it.**
> All the risk in a deck generator is deciding what a slide *is* for an answer, and that's the
> part that's built."

**And the PDF:** `make report` → `report.md` with a per-answer *"where these numbers came from"*
appendix. **`pandoc report.md -o report.pdf`.** That's the whole story, *and it's short because
that renderer computes nothing.*
</details>

<details><summary><b>Q. Why did you build two renderers when the brief asked for zero?</b></summary>

> "A seam with one consumer isn't a seam you've tested. Three of them share one input and none
> of them touch the store — there's a test that runs all three over the same answers."
</details>

<details><summary><b>Q. What stops the seam rotting in six months?</b></summary>

One rule, written in `renderers/__init__.py`:

> "A renderer that needs a number the `Answer` doesn't carry must extend the **pipeline**, never
> reach past it. The moment a renderer opens the store, the seam is gone and the next output
> format is a rewrite again."
</details>

<details><summary><b>Q. Why does a refused question get a slide?</b></summary>

> "Dropping it would be misleading by **selection**, which is the same failure as a wrong number
> arriving by a different route. A question the data couldn't answer is a finding about the
> dataset."

This is a small point that reads as unusually careful. **Use it.**
</details>

---

## §5 · ⭐ The numbers — say them in the same breath as the system

**This is failure #1 from R0 and it is the highest-leverage thing on this page.** Drill these
until they arrive without effort. Every one is already written down; none of them got said.

<details><summary><b>Q. Say all four systems with their magnitude. Cold.</b></summary>

| System | The number — **same sentence, not the next one** |
|---|---|
| #27 home-page agent | **~10M** on the home page |
| #21 assistant | **1.4M monthly** |
| #18 catalogue / dedup | **~1M products**; dedup **80.5% → 98.4%** |
| #20 search | **~100K searches/day** |
| cost work | **$38K → $18K** *(the only figure you said in R0)* |

**The rule:** *"I built the home-page agent — that's about 10M users"* — **one sentence.** Not
"I built the home-page agent." … "how big?" … "about 10M."
</details>

<details><summary><b>Q. ⭐ Draw the boundary on #27. Unprompted.</b></summary>

> "I built the agent and the orchestration. The **deep-research engine**, the **price-comparison
> engine** and the **top-N ranking** it consumes were already there — I integrated them, I didn't
> build them."

⭐ **Say this before anyone asks.** In R0 the direct probe — *"hard to believe one person built so
many things"* — was answered with more of what you built, and that is the exact moment the round
turned. **Volunteering what isn't yours is the fastest credibility move available to you**, and
it costs nothing, because the part that *is* yours survives it intact.
</details>

<details><summary><b>Q. ⛔ Who is in the room, and what does that change?</b></summary>

**Kesharee Nandan Vishwakarma** — IIT-K, Unbxd from 2018, Senior Principal Engineer → **Director
of Engineering, AI**. Ran NLP, personalization and computer vision. Unbxd **is** e-commerce
search and personalization over product catalogues; it powered ~5% of US e-commerce search
traffic and was acquired by Netcore for ~$100M in 2022.

**⇒ Your hybrid search over ~1M products, your embedding+LLM dedup, your entity resolution and
your LLM-as-judge evals are that man's entire career.**

**What it changes, concretely:**

- ⛔ **Never explain a fundamental to him.** Don't define hybrid search, don't explain what a
  reranker does. It reads as not knowing who you're talking to.
- ⭐ **Go one level deeper than feels natural, immediately.** Not "we used embeddings for dedup" —
  **"80.5% to 98.4%, and the remaining failures were <specific category>."**
- ⭐ **Ask him something only he can answer.** *"At Unbxd's scale, where did your catalogue dedup
  break down — was it the blocking stage or the threshold?"* That was the largest single miss of
  R0 — not a leak, an **opportunity cost**. He is the best free consultation in your pipeline and
  R0 spent none of it.
</details>

<details><summary><b>Q. "Why this dataset?" — Judgment is explicitly on their grading list.</b></summary>

> "Synthetic, deliberately. A public CSV gives you realism and takes away control — you get
> whatever pathologies it happens to contain, and you can't prove to a reviewer that the one your
> demo survives is actually in there. Every pathology in this file is **planted, named in the
> generator, and asserted by a test.** So *'it handles messy cells'* is a claim with a test behind
> it rather than a claim behind a lucky file. It's seeded and regenerates byte-stable."

⭐ **Volunteer the counter-argument** (fix #3 again):

> "The honest cost is that I chose the adversary. With a real export I'd have found pathologies I
> didn't think of — which is a good reason to run this against a real sheet of yours, and the
> ingester doesn't assume anything about the schema."

**That last clause turns the weakest point of your dataset choice into an offer to demo on
their data.**
</details>

<details><summary><b>Q. Name the ten pathologies without looking.</b></summary>

1. prices stored as **text** (`"1,299.00"`) ×8
2. **casing/whitespace** region variants ×8 — *naive `GROUP BY` returns 8 regions, not 4*
3. `"N/A"` in a numeric column ×3 — **→ NULL, never 0**
4. a **formula column with no cached value** ×601
5. **merged banner above the header** — `Targets` header is on **row 3**
6. **`Total` rows inside the data** ×4 — *a naive sum double-counts them*
7. blank spacer rows
8. two SKUs, same name different case — **10 products collapse to 9**
9. a **prose sheet** with no table — held as text, **not queryable**
10. a **duplicated `order_id`** (rows 252, 602) — **reported, not dropped**

⭐ **The one to tell as a story is #10:**

> "A repeated order id can be a double entry or a genuine re-order, and the file doesn't say
> which. Dropping one would change a revenue total **on a guess** — so it's reported and left.
> That's the whole posture in miniature: surface the ambiguity, don't resolve it silently."
</details>

---

## §6 · The question he already told you is coming

<details><summary><b>Q. ⭐⭐ "If you had to build this from scratch, how would you?"</b></summary>

**He said this is coming. It is not a trick — it's an invitation to show judgment, and the wrong
answer is to re-describe what you built.**

Structure it as **what I'd keep / what I'd change / what I'd add**:

**Keep — and say why each survives:**
- **The closed plan algebra.** It's what makes validation total and lineage possible; everything
  else in the design follows from it.
- **Provenance carried, not reconstructed.** Retrofitting lineage onto a system that didn't have
  it is a rewrite; this is the decision you cannot defer.
- **Refusal as a first-class output**, with the reason attached.

**Change:**
- **A plan-review step from day one**, not week two. It's the only unguarded failure and it's
  cheap.
- **Ambiguity as part of the answer**, not a separate report — *"there are 8 spellings of region;
  I grouped on 4, here's the mapping"* belongs in the answer.
- **The store would be columnar** (DuckDB/Arrow) with provenance as a parallel column, rather
  than Python dicts. Same model, holds at 100k rows. **Say this before they ask about scale.**

**Add:**
- **The reverse index** — *"which answers used `Sales!G158`?"* The data's already there, it just
  isn't indexed that way. **That's what makes lineage an audit tool rather than an explanation
  feature**, and it's the direction their product actually cares about.

⛔ **Do not say "I'd do it the same way."** It reads as not having thought since.
⛔ **Do not list six things you'd add.** Three, with reasons. **One system proven beats six
listed** — the same rule that lost you R0 applies to the roadmap too.
</details>

<details><summary><b>Q. "How does this hold at 100,000 rows? A million?"</b></summary>

**Be precise about where it breaks — don't wave.**

> "Ingestion is O(cells) and fine. What breaks is that provenance is a Python tuple of
> `CellRef`s per value — a sum over a million rows holds a million objects, and that's memory,
> not time."

Then the fix, which is a **representation** change and not an architecture change:

> "Provenance becomes **ranges** rather than cell lists — `Sales!F2:F600001` with the exclusions
> named. The slide renderer already does exactly this compression for display, so the
> representation exists; it just isn't the storage form. Columnar store underneath, provenance as
> a parallel column."

⭐ **The point to land:** *"nothing about the guarantee changes — it's a representation change, not
an architecture change."*
</details>

<details><summary><b>Q. "What would you do differently with another week?" — have exactly three</b></summary>

1. **The plan-review step.** The one unguarded failure. Highest value, cheapest.
2. **Widen the algebra** — time comparisons, ratios across two aggregates, `HAVING` — **with the
   provenance rule for each operator written first**, one at a time, never by reaching for raw SQL.
3. **The reverse cell index**, which is what makes this an auditing tool rather than an explaining
   tool.

(The README lists six. **Say three.** Offer the rest only if asked.)
</details>

---

## §7 · The last five minutes — questions you ask

⛔ R0's largest miss was an **opportunity cost**: the best-qualified person you could ask about
your own domain was in the room, and you asked him nothing. **Do not repeat it.**

<details><summary><b>Q. Have three ready. What are they?</b></summary>

**The domain question — the one only he can answer, and the one that repairs R0:**
> "At Unbxd's scale, where did catalogue dedup actually break down for you — the blocking stage,
> or the threshold? I got 80.5% to 98.4% on ~1M products and I'm fairly sure I was one order of
> magnitude away from the problems you had."

**The product question — shows you used the product, not just read the site:**
> "Your positioning is *every number traceable to source*. Where does that get hardest — is it the
> ERP connectors, or is it keeping lineage intact through the **template** layer when a number
> lands in a slide?"

**The role question — asks what you'd own, which is the boundary question pointed forwards:**
> "With 6–7 in engineering, what's the first thing you'd want this person to own end to end?"

⭐ And the one that costs nothing and is still unresolved on your side:
> "Is there a **US entity**, or is the team India-only for now?"
</details>

---

## §8 · Pre-flight — the morning of

- [ ] `make setup && make test` on **this laptop**, on **battery**, with **wifi off**
- [ ] `ANTHROPIC_API_KEY` exported, **or** decide the cached line and say it up front (§1)
- [ ] The workbook **open in Excel/Numbers** on a second window, at the `Sales` sheet
- [ ] `--lineage "Sales!G9"` run once so the command is in shell history
- [ ] Terminal font size up. They're reading cell references across a table.
- [ ] **⛔ The README's *"Impressions of the product"* section is still a placeholder.** Sign up at
      coreworks.ai, spend the 15 minutes, write the paragraph. **It is the one item of the brief
      that is not done**, and it's the cheapest one.
- [ ] Re-read §0 and §5 in the car. **Numbers, boundary, alternatives.** Nothing else.

---

<details><summary><b>The whole page in six lines, for the last two minutes</b></summary>

1. **A number and a boundary in every system sentence.** Same breath.
2. **Text-to-plan, not text-to-SQL** — you can't validate a string you can't enumerate.
3. **Lineage is carried through the fold**, never reconstructed.
4. **Four gates; the last one re-reads the prose.** Rounding at displayed precision, not a
   tolerance — *46.7 was the bug.*
5. **The unguarded failure is a plan that binds and means the wrong thing.** Say it first.
6. **Ask him the Unbxd dedup question.** It is the round's free consultation.
</details>
