#!/usr/bin/env python3
"""Build the demo workbook — deterministically, and deliberately messy.

WHY THIS IS SYNTHESISED AND NOT A PUBLIC CSV
    The assignment asks for "something real-ish ... some formulas or messy cells". A public
    file gives you realism and takes away CONTROL: you get whatever pathologies it happens to
    contain, and you cannot prove to a reviewer that the one your demo survives is actually
    there. Here every pathology is planted, named in PATHOLOGIES below, and asserted by the
    test suite -- so "it handles messy cells" is a claim with a test behind it rather than a
    claim behind a lucky dataset.

    The shape is a mid-size D2C company's FY2025 operating review: the kind of workbook that
    actually shows up in a finance team's Drive, with the accidents that actually show up in
    one. Seeded, so the file regenerates byte-stable.

PATHOLOGIES PLANTED (each one is exercised by a question or a test)
    1.  Sales.unit_price      some cells are TEXT ("1,299.00") -- a naive sum silently skips them
    2.  Sales.region          casing and whitespace variants ("north ", "NORTH") -- naive GROUP BY
                              splits one region into three
    3.  Sales.units           some cells are the string "N/A" -- coerces to NULL, never to 0
    4.  Sales.net_revenue     a FORMULA column; openpyxl in data_only mode reads the CACHED value,
                              so we ingest both and flag disagreement rather than trusting either
    5.  Targets              a merged title row ABOVE the header row -- the header is not row 1
    6.  Headcount            a "Total" row INSIDE the data -- a naive SUM double-counts it
    7.  Headcount            fully blank spacer rows between departments
    8.  Products             two SKUs whose product_name differs only by case
    9.  Notes                a free-text sheet with no tabular structure at all
    10. Sales                one duplicated order_id (a genuine double-entry, not a re-order)
"""
import datetime as _dt
import random
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
OUT = HERE / "acme_operating_review.xlsx"
SEED = 20260921

REGIONS = ["North", "South", "East", "West"]
CHANNELS = ["D2C Web", "Marketplace", "Retail Partner"]

PRODUCTS = [
    # sku,      name,                     category,      cost_price, launch
    ("SKU-1001", "Aurora Table Lamp",      "Lighting",       1180.00, "2023-04-12"),
    ("SKU-1002", "Aurora Floor Lamp",      "Lighting",       2140.00, "2023-04-12"),
    ("SKU-1003", "Kettle 1.7L Steel",      "Kitchen",         890.00, "2022-11-01"),
    ("SKU-1004", "Cast Iron Skillet 10in", "Kitchen",        1450.00, "2024-02-20"),
    ("SKU-1005", "Linen Duvet Queen",      "Bedding",        3100.00, "2023-08-05"),
    ("SKU-1006", "linen duvet queen",      "Bedding",        3100.00, "2025-01-15"),  # pathology 8
    ("SKU-1007", "Weighted Blanket 7kg",   "Bedding",        2480.00, "2024-09-30"),
    ("SKU-1008", "Ceramic Mug Set of 4",   "Kitchen",         520.00, "2022-06-18"),
    ("SKU-1009", "Oak Side Table",         "Furniture",      4200.00, "2024-05-22"),
    ("SKU-1010", "Rattan Armchair",        "Furniture",      7600.00, "2025-03-10"),
]

# Fiscal year 2025 runs Apr 2025 -> Mar 2026. Q3 FY2025 = Oct/Nov/Dec 2025.
FY_START = _dt.date(2025, 4, 1)
FY_END = _dt.date(2026, 3, 31)


def _quarter(d: _dt.date) -> str:
    """Fiscal quarter label for an April-start fiscal year."""
    idx = ((d.month - 4) % 12) // 3 + 1
    return f"Q{idx}"


def build_sales(ws, rng):
    headers = [
        "order_date", "order_id", "region", "channel", "sku",
        "units", "unit_price", "discount_pct", "net_revenue", "customer",
    ]
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        ws.cell(row=1, column=c).font = Font(bold=True)

    customers = [f"CUST-{n:04d}" for n in range(1, 181)]
    span = (FY_END - FY_START).days
    rows = []
    for i in range(600):
        d = FY_START + _dt.timedelta(days=rng.randrange(span + 1))
        sku, _name, _cat, cost, _launch = PRODUCTS[rng.randrange(len(PRODUCTS))]
        units = rng.randint(1, 14)
        price = round(cost * rng.uniform(1.35, 2.30), 2)
        disc = rng.choice([0.0, 0.0, 0.0, 0.05, 0.10, 0.15, 0.20])
        rows.append({
            "order_date": d,
            "order_id": f"ORD-{100000 + i}",
            "region": REGIONS[rng.randrange(len(REGIONS))],
            "channel": CHANNELS[rng.randrange(len(CHANNELS))],
            "sku": sku,
            "units": units,
            "unit_price": price,
            "discount_pct": disc,
            "customer": customers[rng.randrange(len(customers))],
        })
    rows.sort(key=lambda r: r["order_date"])

    # ---- plant the pathologies, at fixed indices so the tests can name them ----
    text_price_rows = {7, 44, 91, 158, 203, 310, 402, 511}      # pathology 1
    dirty_region_rows = {12, 13, 58, 59, 120, 277, 399, 450}    # pathology 2
    na_unit_rows = {33, 188, 471}                               # pathology 3
    for i in dirty_region_rows:
        r = rows[i]
        r["region"] = rng.choice([r["region"].lower() + " ", r["region"].upper(), " " + r["region"]])

    for i, r in enumerate(rows):
        excel_row = i + 2
        ws.cell(row=excel_row, column=1, value=r["order_date"]).number_format = "yyyy-mm-dd"
        ws.cell(row=excel_row, column=2, value=r["order_id"])
        ws.cell(row=excel_row, column=3, value=r["region"])
        ws.cell(row=excel_row, column=4, value=r["channel"])
        ws.cell(row=excel_row, column=5, value=r["sku"])

        if i in na_unit_rows:
            ws.cell(row=excel_row, column=6, value="N/A")
        else:
            ws.cell(row=excel_row, column=6, value=r["units"])

        if i in text_price_rows:
            ws.cell(row=excel_row, column=7, value=f"{r['unit_price']:,.2f}")   # TEXT, with a comma
        else:
            ws.cell(row=excel_row, column=7, value=r["unit_price"]).number_format = "#,##0.00"

        ws.cell(row=excel_row, column=8, value=r["discount_pct"]).number_format = "0%"
        # pathology 4 -- a real formula. openpyxl writes the formula; there is no cached value
        # until Excel opens it, which is exactly the situation the ingester has to survive.
        ws.cell(row=excel_row, column=9,
                value=f"=F{excel_row}*G{excel_row}*(1-H{excel_row})").number_format = "#,##0.00"
        ws.cell(row=excel_row, column=10, value=r["customer"])

    # pathology 10 -- one genuine double-entry: same order_id, same everything, entered twice.
    dup_src = 2 + 250
    last = ws.max_row + 1
    for c in range(1, 11):
        src = ws.cell(row=dup_src, column=c)
        val = src.value
        if isinstance(val, str) and val.startswith("="):
            val = val.replace(str(dup_src), str(last))
        ws.cell(row=last, column=c, value=val).number_format = src.number_format

    for c, w in zip(range(1, 11), (12, 12, 10, 16, 11, 8, 11, 12, 13, 12)):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"
    return rows


def build_products(ws):
    headers = ["sku", "product_name", "category", "cost_price", "launch_date"]
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        ws.cell(row=1, column=c).font = Font(bold=True)
    for i, (sku, name, cat, cost, launch) in enumerate(PRODUCTS):
        r = i + 2
        ws.cell(row=r, column=1, value=sku)
        ws.cell(row=r, column=2, value=name)
        ws.cell(row=r, column=3, value=cat)
        ws.cell(row=r, column=4, value=cost).number_format = "#,##0.00"
        ws.cell(row=r, column=5,
                value=_dt.date.fromisoformat(launch)).number_format = "yyyy-mm-dd"
    for c, w in zip(range(1, 6), (11, 24, 12, 12, 13)):
        ws.column_dimensions[get_column_letter(c)].width = w


def build_targets(ws, sales_rows):
    """pathology 5 -- a merged title banner occupying row 1; the header is on row 3."""
    ws.merge_cells("A1:C1")
    t = ws.cell(row=1, column=1, value="FY2025 Regional Revenue Targets (INR) — approved 28 Mar 2025")
    t.font = Font(bold=True, size=13)
    ws.cell(row=2, column=1, value=None)

    headers = ["region", "quarter", "revenue_target"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=3, column=c, value=h).font = Font(bold=True)

    # Targets are set a little above/below actuals so "did we hit it" has both answers in it.
    actual = {}
    for r in sales_rows:
        q = _quarter(r["order_date"])
        rev = r["units"] * r["unit_price"] * (1 - r["discount_pct"])
        actual[(r["region"], q)] = actual.get((r["region"], q), 0.0) + rev

    bump = {("North", "Q3"): 1.12, ("South", "Q3"): 0.88, ("East", "Q3"): 1.04, ("West", "Q3"): 0.93}
    row = 4
    for region in REGIONS:
        for q in ("Q1", "Q2", "Q3", "Q4"):
            base = actual.get((region, q), 0.0)
            factor = bump.get((region, q), 1.0)
            ws.cell(row=row, column=1, value=region)
            ws.cell(row=row, column=2, value=q)
            ws.cell(row=row, column=3,
                    value=round(base * factor, -3) or 500000).number_format = "#,##0"
            row += 1
    for c, w in zip(range(1, 4), (12, 10, 16)):
        ws.column_dimensions[get_column_letter(c)].width = w


def build_headcount(ws):
    """pathologies 6 and 7 -- a Total row inside the data, and blank spacer rows."""
    headers = ["month", "department", "headcount", "fully_loaded_cost"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h).font = Font(bold=True)

    plan = {
        "Engineering":  (18, 19, 19, 21, 22, 22, 24, 24, 25, 26, 26, 27),
        "Operations":   (11, 11, 12, 12, 12, 13, 13, 13, 14, 14, 15, 15),
        "Marketing":    (6, 6, 7, 7, 8, 8, 8, 9, 9, 9, 10, 10),
        "Finance & Ops": (4, 4, 4, 4, 5, 5, 5, 5, 5, 6, 6, 6),
    }
    cost_per_head = {"Engineering": 265000, "Operations": 118000,
                     "Marketing": 152000, "Finance & Ops": 174000}
    months = [_dt.date(2025, 4, 1)]
    for _ in range(11):
        prev = months[-1]
        months.append(_dt.date(prev.year + (prev.month // 12), prev.month % 12 + 1, 1))

    row = 2
    for dept, series in plan.items():
        for m, hc in zip(months, series):
            ws.cell(row=row, column=1, value=m).number_format = "yyyy-mm"
            ws.cell(row=row, column=2, value=dept)
            ws.cell(row=row, column=3, value=hc)
            ws.cell(row=row, column=4,
                    value=hc * cost_per_head[dept]).number_format = "#,##0"
            row += 1
        # pathology 6 -- a subtotal row sitting in the same columns as the data
        ws.cell(row=row, column=2, value="Total")
        ws.cell(row=row, column=3, value=sum(series))
        ws.cell(row=row, column=4, value=sum(series) * cost_per_head[dept]).number_format = "#,##0"
        for c in range(1, 5):
            ws.cell(row=row, column=c).font = Font(bold=True)
        row += 1
        row += 1   # pathology 7 -- blank spacer

    for c, w in zip(range(1, 5), (11, 16, 12, 18)):
        ws.column_dimensions[get_column_letter(c)].width = w


def build_notes(ws):
    """pathology 9 -- prose, no table. The ingester must decline to make a table of it."""
    lines = [
        "FY2025 operating review — working notes",
        "",
        "Q2 was distorted by the marketplace outage in the second week of August; the",
        "recovery landed inside the same quarter so no restatement was made.",
        "",
        "SKU-1006 was opened as a separate line for the re-launched duvet. Finance has",
        "asked twice for the two lines to be merged and it has not happened yet.",
        "",
        "Regional targets were approved before the Rattan Armchair launch, so West's Q4",
        "target does not contain it.",
        "",
        "Churn is tracked in the subscriptions tool, not in this workbook.",
    ]
    for i, ln in enumerate(lines, start=1):
        ws.cell(row=i, column=1, value=ln)
    ws.column_dimensions["A"].width = 84


#: Every timestamp baked into the file, pinned. An .xlsx is a zip, and BOTH layers carry a
#: clock: openpyxl stamps docProps/core.xml, and ZipFile stamps every entry with localtime at
#: 2-second resolution. Pinning only the first made the file *look* stable when two runs landed
#: in the same 2-second window and unstable otherwise -- which is the worst kind of flaky.
FIXED_TIME = _dt.datetime(2026, 9, 21, 0, 0, 0)
FIXED_ZIP_TIME = (2026, 9, 21, 0, 0, 0)


def _normalise_zip(path: Path):
    """Rewrite the archive with a fixed timestamp on every entry, content untouched.

    ⚠️ `wb.properties.modified` is set here too, because openpyxl OVERWRITES it with the wall
    clock inside save() -- setting it on the workbook object has no effect at all. That one
    field is the reason two runs eleven seconds apart still differed after the zip entry times
    were pinned, and it is invisible unless you diff the archive member by member.
    """
    import re
    import zipfile
    stamp = FIXED_TIME.strftime("%Y-%m-%dT%H:%M:%SZ")
    with zipfile.ZipFile(path) as z:
        entries = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in entries:
            if info.filename == "docProps/core.xml":
                data = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                              rb"\g<1>" + stamp.encode() + rb"\g<2>", data)
            new = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            new.compress_type = info.compress_type
            new.external_attr = info.external_attr
            z.writestr(new, data)


def main():
    rng = random.Random(SEED)
    wb = Workbook()

    ws_sales = wb.active
    ws_sales.title = "Sales"
    sales_rows = build_sales(ws_sales, rng)

    build_products(wb.create_sheet("Products"))
    build_targets(wb.create_sheet("Targets"), sales_rows)
    build_headcount(wb.create_sheet("Headcount"))
    build_notes(wb.create_sheet("Notes"))

    # ⭐ BYTE-STABILITY. The sheet XML is already deterministic (seeded RNG), but openpyxl
    # stamps docProps/core.xml with the wall clock at save time, so two identical runs
    # produced two different files. Pinning created/modified makes `make data` a true no-op
    # in git -- which matters because the README claims it, and a claim the repo disproves
    # in one command is worse than no claim.
    wb.properties.created = FIXED_TIME
    wb.properties.modified = FIXED_TIME
    wb.properties.creator = "make_dataset.py"
    wb.properties.lastModifiedBy = "make_dataset.py"

    wb.save(OUT)
    _normalise_zip(OUT)
    print(f"wrote {OUT}  ({OUT.stat().st_size / 1024:.0f} KB)")
    print(f"  sheets: {', '.join(wb.sheetnames)}")
    print(f"  Sales rows: {ws_sales.max_row - 1} (601 = 600 orders + 1 planted duplicate)")


if __name__ == "__main__":
    main()
