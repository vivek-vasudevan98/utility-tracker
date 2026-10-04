"""Extract suite events from a Salesforce "Ops report" Excel export.

The report has a title/filter block above the table, group rows such as
"Event Start Year: 2026 (197 records)" inside it, and totals/footer rows
below it. This script finds the header row, keeps only real data rows and
writes the matching events to a new workbook, grouped by event name.

Several reports can be given at once; their rows are merged into one
workbook. A booking event that appears in more than one report is kept
once, using the report listed last, so list older reports first.

Usage:
    python scripts/extract_events.py report.xlsx [more_reports.xlsx ...] [-o output.xlsx]
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

STATUS = "Definite"
ROOMS = [
    "Gateshead Suite",
    "Gateshead Suite Foyer",
    "Hillgate Suite",
    "Oakwellgate Suite",
    "Pipewellgate Suite",
    "Oakwellgate/Pipewellgate Suite",
    "Hillgate/Oakwellgate Suite",
    "Pipewellgate/Oakwellgate Suite"
]
# Values of the output "Event Type" column to leave out.
EXCLUDED_TYPES = ["Teardown", "Dance"]

# Report column -> output column. Either "Date" or "Event Start Date" is
# accepted for the date column.
DATE_COLUMNS = ("Date", "Event Start Date")
COLUMN_MAP = {
    "Booking Event ID": "Event Id",
    "Booking Post As": "Event Name",
    "Function Room: Function Room Name": "Event Location",
    "Event Classification: Name": "Event Type",
}
REQUIRED = ["Event Status", "Expected", *COLUMN_MAP]
TYPE_COLUMN = next(src for src, dst in COLUMN_MAP.items() if dst == "Event Type")
ID_COLUMN = next(src for src, dst in COLUMN_MAP.items() if dst == "Event Id")
OUTPUT_COLUMNS = ["Event Id", "Date", "Event Name", "Event Location", "Event Type"]


def _norm(value):
    """Lower-case and collapse whitespace (including non-breaking spaces)."""
    return " ".join(str(value).replace("\xa0", " ").split()).lower()


def _room_key(value):
    """Normalise a room name so "A/B Suite" matches "B/A Suite"."""
    name = _norm(value)
    if name.endswith(" suite") and "/" in name:
        parts = sorted(p.strip() for p in name[: -len(" suite")].split("/"))
        name = "/".join(parts) + " suite"
    return name


ROOM_KEYS = {_room_key(r) for r in ROOMS}
EXCLUDED_TYPE_KEYS = {_norm(t) for t in EXCLUDED_TYPES}


def find_header_row(raw):
    """Return the index of the row that holds the table's column names."""
    for idx, row in raw.iterrows():
        cells = {_norm(v) for v in row if pd.notna(v)}
        if all(_norm(c) in cells for c in REQUIRED):
            return idx
    raise ValueError(
        "Could not find the table header row; expected columns: "
        + ", ".join(REQUIRED)
    )


def load_table(path):
    raw = pd.read_excel(path, header=None, dtype=object)
    header_idx = find_header_row(raw)
    table = raw.iloc[header_idx + 1 :].copy()
    # Match headers case-insensitively, e.g. "Booking Event Id" or "ID".
    known = {_norm(c): c for c in (*REQUIRED, *DATE_COLUMNS)}
    table.columns = [
        known.get(_norm(c), str(c).replace("\xa0", " ").strip())
        if pd.notna(c) else f"col{i}"
        for i, c in enumerate(raw.iloc[header_idx])
    ]
    date_col = next((c for c in DATE_COLUMNS if c in table.columns), None)
    if date_col is None:
        raise ValueError("Could not find a 'Date' or 'Event Start Date' column")
    table = table.rename(columns={date_col: "Date"})
    # Group headers, blank rows, totals and footer only fill the first cell.
    table["Date"] = pd.to_datetime(table["Date"], errors="coerce", dayfirst=True)
    table = table[table["Date"].notna()].copy()
    table[ID_COLUMN] = table[ID_COLUMN].map(
        lambda v: str(v).replace("\xa0", " ").strip() if pd.notna(v) else None
    )
    return table


def load_tables(paths):
    """Read several reports into one table with one row per Booking Event ID.

    Duplicates are dropped before filtering so the latest report decides,
    e.g. a booking that has since been cancelled is not kept from an older
    report where it was still Definite.
    """
    table = pd.concat([load_table(p) for p in paths], ignore_index=True)
    has_id = table[ID_COLUMN].notna()
    deduped = pd.concat(
        [
            table[has_id].drop_duplicates(subset=ID_COLUMN, keep="last"),
            table[~has_id],
        ]
    ).sort_index()
    return deduped, len(table) - len(deduped)


def has_expected(value):
    """True when Expected is a number other than zero (not blank or "-")."""
    if pd.isna(value):
        return False
    number = pd.to_numeric(str(value).replace(",", "").strip(), errors="coerce")
    return pd.notna(number) and number != 0


def extract(table):
    mask = (
        (table["Event Status"].map(_norm) == _norm(STATUS))
        & table["Function Room: Function Room Name"].map(
            lambda v: pd.notna(v) and _room_key(v) in ROOM_KEYS
        )
        & table["Expected"].map(has_expected)
        & ~table[TYPE_COLUMN].map(lambda v: _norm(v) in EXCLUDED_TYPE_KEYS)
    )
    out = table.loc[mask, ["Date", *COLUMN_MAP]].rename(columns=COLUMN_MAP)
    for col in COLUMN_MAP.values():
        out[col] = out[col].map(lambda v: str(v).replace("\xa0", " ").strip())

    # Groups appear in order of their first date; rows inside by date.
    out["_first"] = out.groupby("Event Name")["Date"].transform("min")
    out = out.sort_values(["_first", "Event Name", "Date"], kind="stable")
    return out.drop(columns="_first").reset_index(drop=True)


def write_grouped(df, path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Events"
    columns = OUTPUT_COLUMNS
    date_col = columns.index("Date") + 1
    bold = Font(bold=True)
    group_fill = PatternFill("solid", fgColor="DDEBF7")

    ws.append(columns)
    for cell in ws[1]:
        cell.font = bold
    ws.freeze_panes = "A2"

    for name, rows in df.groupby("Event Name", sort=False):
        ws.append([f"{name} ({len(rows)})"])
        group_row = ws.max_row
        for col in range(1, len(columns) + 1):
            ws.cell(group_row, col).fill = group_fill
        ws.cell(group_row, 1).font = bold
        for rec in rows[columns].itertuples(index=False):
            ws.append([v.to_pydatetime() if isinstance(v, pd.Timestamp) else v for v in rec])
            ws.cell(ws.max_row, date_col).number_format = "DD/MM/YYYY"
            ws.row_dimensions[ws.max_row].outline_level = 1

    ws.sheet_properties.outlinePr.summaryBelow = False
    for i, col in enumerate(columns, 1):
        width = max([len(col)] + [len(str(v)) for v in df[col]]) if len(df) else len(col)
        ws.column_dimensions[get_column_letter(i)].width = min(max(width, 12) + 2, 60)
    wb.save(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "inputs",
        type=Path,
        nargs="+",
        help="report .xlsx file(s), oldest first",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output .xlsx file (default: <input>_events.xlsx for one report, "
        "consolidated_events.xlsx next to the first report for several)",
    )
    args = parser.parse_args(argv)
    first = args.inputs[0]
    if args.output:
        output = args.output
    elif len(args.inputs) == 1:
        output = first.with_name(f"{first.stem}_events.xlsx")
    else:
        output = first.with_name("consolidated_events.xlsx")

    table, duplicates = load_tables(args.inputs)
    events = extract(table)
    write_grouped(events, output)
    if duplicates:
        print(f"Skipped {duplicates} duplicate Booking Event ID row(s)")
    print(
        f"Wrote {len(events)} rows in {events['Event Name'].nunique()} "
        f"event groups from {len(args.inputs)} report(s) to {output}"
    )


if __name__ == "__main__":
    sys.exit(main())
