# The five things worth running. `make demo` is the one for the room.
PY ?= python3

setup:            ## create a venv and install what the demo needs
	$(PY) -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt
	@echo "→ run: ./.venv/bin/python demo.py"

demo:             ## the five questions, end to end, with cell-level sources
	$(PY) demo.py

quality:          ## what the ingester found wrong with the workbook
	$(PY) demo.py --quality

schema:           ## exactly what the planner is shown — it never sees the data
	$(PY) demo.py --explain

report:           ## the same answers as a report body (a PDF is one pandoc call from here)
	$(PY) demo.py --render markdown --out report.md && echo "wrote report.md"

deck:             ## the same answers as deck structure
	$(PY) demo.py --render slides --out deck.txt && echo "wrote deck.txt"

test:             ## the guarantees: lineage is total, and the system refuses
	$(PY) -m pytest tests/ -q

data:             ## regenerate the workbook (deterministic — same bytes every time)
	$(PY) data/make_dataset.py

.PHONY: setup demo quality schema report deck test data
