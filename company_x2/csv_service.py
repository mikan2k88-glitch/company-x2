"""Deterministic first service: remove exactly identical CSV records."""
import csv
import io

MAX_BYTES = 1_000_000
MAX_ROWS = 10_000

def deduplicate_csv(text: str) -> dict:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("input too large")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    header = next(reader, None)
    if not header or any(not value.strip() for value in header):
        raise ValueError("nonempty column names required")
    if len(set(header)) != len(header):
        raise ValueError("duplicate column names")
    unique, seen, count = [], set(), 0
    for row in reader:
        count += 1
        if count > MAX_ROWS or len(row) != len(header):
            raise ValueError("row limit or column count violation")
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(unique)
    return {"csv": output.getvalue(), "input_rows": count,
            "output_rows": len(unique), "removed_rows": count - len(unique)}
