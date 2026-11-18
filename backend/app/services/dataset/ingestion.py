"""File validation, parsing and type inference for CSV / XLSX / XLS uploads."""
import csv
import io
import re
import warnings
import zipfile
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.core.errors import bad_request

ALLOWED_EXT = {".csv": "csv", ".xlsx": "xlsx", ".xls": "xls"}
NULL_TOKENS = {"", "na", "n/a", "null", "none", "nan", "-", "--", "#n/a", "nil"}
_CURRENCY = re.compile(r"[$€£₹¥]|\b(usd|eur|gbp|inr)\b", re.I)
_DATEISH = re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{4}-\d{2}|[a-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[a-z]{3,9}\s+\d{4}", re.I)
_BOOL_TRUE, _BOOL_FALSE = {"true", "yes", "y"}, {"false", "no", "n"}


def detect_format(filename: str, head: bytes) -> str:
    """Allow-list by extension AND verify the file signature. MIME types are not trusted."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = ALLOWED_EXT.get(ext)
    if not kind:
        raise bad_request("Only .csv, .xlsx and .xls files are supported", "unsupported_format")
    if kind == "xlsx":
        if not head.startswith(b"PK\x03\x04"):
            raise bad_request("This file is not a valid .xlsx workbook", "invalid_file")
    elif kind == "xls":
        if not head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise bad_request("This file is not a valid .xls workbook", "invalid_file")
    else:
        if b"\x00" in head[:4096] and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise bad_request("This file does not look like a text CSV file", "invalid_file")
        if head.startswith((b"PK\x03\x04", b"\xd0\xcf\x11\xe0")):
            raise bad_request("This looks like an Excel workbook. Rename it with the correct extension", "invalid_file")
    return kind


def verify_xlsx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            if "xl/workbook.xml" not in names:
                raise bad_request("This file is not a valid .xlsx workbook", "invalid_file")
            if "xl/vbaProject.bin" in names:
                raise bad_request("Macro-enabled workbooks are not accepted", "macros_not_allowed")
            total = sum(i.file_size for i in z.infolist())
            if total > get_settings().max_upload_bytes * 20:  # zip-bomb guard
                raise bad_request("Workbook expands beyond the allowed size", "file_too_large")
    except zipfile.BadZipFile:
        raise bad_request("This file is not a valid .xlsx workbook", "invalid_file")


# ----------------------------------------------------------------------------- workbook sheets
def list_sheets(data: bytes, kind: str) -> list[dict]:
    if kind == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            out.append({"name": ws.title, "rows": ws.max_row or 0, "columns": ws.max_column or 0,
                        "empty": not (ws.max_row and ws.max_row > 1)})
        wb.close()
        return out
    import xlrd
    book = xlrd.open_workbook(file_contents=data, on_demand=True)
    out = [{"name": s.name, "rows": s.nrows, "columns": s.ncols, "empty": s.nrows < 2} for s in book.sheets()]
    book.release_resources()
    return out


@dataclass
class RawTable:
    frame: pd.DataFrame
    report: dict = field(default_factory=dict)


def _clean_headers(raw: list) -> tuple[list[str], list[str]]:
    notes, headers, seen = [], [], {}
    for i, h in enumerate(raw):
        name = str(h).strip() if h is not None and str(h).strip() not in ("", "nan", "None") else ""
        if not name:
            name = f"Column {i + 1}"
            notes.append(f"Column {i + 1} had no header and was named '{name}'")
        if name.lower() in seen:
            seen[name.lower()] += 1
            new = f"{name} ({seen[name.lower()]})"
            notes.append(f"Duplicate header '{name}' renamed to '{new}'")
            name = new
        else:
            seen[name.lower()] = 1
        headers.append(name)
    return headers, notes


def read_excel(data: bytes, kind: str, sheet: str) -> RawTable:
    s = get_settings()
    rows: list[list] = []
    if kind == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)  # data_only: cached values, no macros
        if sheet not in wb.sheetnames:
            raise bad_request(f"Sheet '{sheet}' was not found in the workbook", "sheet_not_found")
        for r in wb[sheet].iter_rows(values_only=True):
            rows.append(list(r))
            if len(rows) > s.max_rows + 50:
                raise bad_request(f"The sheet has more than {s.max_rows:,} rows", "too_many_rows")
        wb.close()
    else:
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        try:
            sh = book.sheet_by_name(sheet)
        except xlrd.XLRDError:
            raise bad_request(f"Sheet '{sheet}' was not found in the workbook", "sheet_not_found")
        for i in range(sh.nrows):
            row = []
            for c in sh.row(i):
                if c.ctype == xlrd.XL_CELL_DATE:
                    row.append(xlrd.xldate.xldate_as_datetime(c.value, book.datemode))
                else:
                    row.append(c.value)
            rows.append(row)
    # Skip leading empty rows; first non-empty row is the header
    rows = [r for r in rows if any(v is not None and str(v).strip() != "" for v in r)]
    if not rows:
        raise bad_request(f"Sheet '{sheet}' is empty", "empty_sheet")
    width = max(len(r) for r in rows)
    rows = [list(r) + [None] * (width - len(r)) for r in rows]
    # Drop columns that are entirely empty (common in exported sheets)
    keep = [j for j in range(width) if any(r[j] is not None and str(r[j]).strip() != "" for r in rows)]
    rows = [[r[j] for j in keep] for r in rows]
    headers, notes = _clean_headers(rows[0])
    body = rows[1:]
    if not body:
        raise bad_request("The sheet has a header row but no data rows", "empty_sheet")
    frame = pd.DataFrame(body, columns=headers, dtype=object)
    return RawTable(frame, {"source": kind, "sheet": sheet, "header_notes": notes, "skipped_lines": 0,
                            "encoding": None, "delimiter": None})


def read_csv(data: bytes) -> RawTable:
    s = get_settings()
    text, encoding = None, None
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            text, encoding = data.decode(enc), enc
            break
        except UnicodeDecodeError:
            continue
    if text is None or not text.strip():
        raise bad_request("The CSV file is empty or could not be decoded", "empty_file")
    sample = text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        has_header = True
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    # Sniffer is conservative with all-text data; trust a first row without numbers as a header
    if not has_header and not re.search(r"\d", first_line):
        has_header = True
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        frame = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, keep_default_na=False,
                            header=0 if has_header else None, on_bad_lines="warn", skip_blank_lines=True,
                            quotechar='"', nrows=s.max_rows + 1)
    skipped = sum(str(w.message).count("Skipping line") or 1 for w in caught if "line" in str(w.message).lower())
    if len(frame) > s.max_rows:
        raise bad_request(f"The file has more than {s.max_rows:,} rows", "too_many_rows")
    if frame.empty:
        raise bad_request("The CSV file has no data rows", "empty_file")
    raw_headers = list(frame.columns) if has_header else [f"Column {i + 1}" for i in range(frame.shape[1])]
    headers, notes = _clean_headers(["" if str(h).startswith("Unnamed:") else h for h in raw_headers])
    frame.columns = headers
    frame = frame.astype(object)
    return RawTable(frame, {"source": "csv", "encoding": encoding, "delimiter": {"\t": "tab"}.get(delimiter, delimiter),
                            "header_detected": has_header, "header_notes": notes, "skipped_lines": int(skipped)})


# ----------------------------------------------------------------------------- type inference
def safe_identifier(name: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:56] or "column"
    if base[0].isdigit():
        base = "c_" + base
    cand, i = base, 2
    while cand in used:
        cand, i = f"{base}_{i}", i + 1
    used.add(cand)
    return cand


def _null_mask(s: pd.Series) -> pd.Series:
    return s.isna() | s.astype(str).str.strip().str.lower().isin(NULL_TOKENS)


def _to_number(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.strip()
    neg = t.str.match(r"^\(.*\)$")
    t = t.str.replace(_CURRENCY, "", regex=True).str.replace(r"[,\s()%]", "", regex=True)
    out = pd.to_numeric(t, errors="coerce")
    return out.where(~neg, -out)


def _to_datetime(s: pd.Series) -> pd.Series:
    best = None
    for kwargs in ({"format": "ISO8601"}, {"format": "mixed", "dayfirst": False}, {"format": "mixed", "dayfirst": True}):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                parsed = pd.to_datetime(s.astype(str).str.strip(), errors="coerce", **kwargs)
            except (ValueError, TypeError):
                continue
        if best is None or parsed.notna().sum() > best.notna().sum():
            best = parsed
    return best if best is not None else pd.Series(pd.NaT, index=s.index)


def infer_column(raw: pd.Series, name_hint: str) -> tuple[pd.Series, str, int]:
    """Returns (typed series, dtype, invalid_count). invalid = non-empty values that did not parse."""
    nulls = _null_mask(raw)
    present = raw[~nulls]
    n = len(present)
    if n == 0:
        return pd.Series([None] * len(raw), index=raw.index, dtype="string"), "string", 0
    # Native types from Excel
    if present.map(lambda v: isinstance(v, (pd.Timestamp, np.datetime64)) or hasattr(v, "year") and hasattr(v, "month")).mean() >= 0.95:
        parsed = pd.to_datetime(raw.where(~nulls), errors="coerce")
        return _finish_dt(parsed, nulls)
    if present.map(lambda v: isinstance(v, bool)).all():
        return raw.where(~nulls).astype("boolean"), "boolean", 0
    lowered = present.astype(str).str.strip().str.lower()
    if lowered.isin(_BOOL_TRUE | _BOOL_FALSE).all() and lowered.nunique() <= 2:
        return raw.astype(str).str.strip().str.lower().map(lambda v: True if v in _BOOL_TRUE else False if v in _BOOL_FALSE else None).astype("boolean"), "boolean", 0
    nums = _to_number(present)
    num_ok = nums.notna().mean()
    if num_ok >= 0.95:
        full = pd.Series(np.nan, index=raw.index, dtype="float64")
        full[~nulls] = nums
        invalid = int(nums.isna().sum())
        vals = full.dropna()
        if len(vals) and (vals % 1 == 0).all() and vals.abs().max() < 2**53:
            return full.astype("Int64"), "integer", invalid
        return full, "float", invalid
    looks_date = lowered.head(500).str.contains(_DATEISH).mean() >= 0.8 or re.search(r"date|time|day|month|period", name_hint, re.I)
    if looks_date and not lowered.head(200).str.fullmatch(r"-?\d+(\.\d+)?").all():
        dt = _to_datetime(present)
        if dt.notna().mean() >= 0.9:
            full = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns]")
            full[~nulls] = dt
            typed, dtype, _ = _finish_dt(full, nulls)
            return typed, dtype, int(dt.isna().sum())
    return raw.map(lambda v: None if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip()).where(~nulls, None).astype("string"), "string", 0


def _finish_dt(parsed: pd.Series, nulls: pd.Series):
    parsed = pd.to_datetime(parsed, errors="coerce")
    valid = parsed.dropna()
    has_time = len(valid) and ((valid.dt.hour != 0) | (valid.dt.minute != 0) | (valid.dt.second != 0)).any()
    invalid = int((parsed.isna() & ~nulls).sum())
    if has_time:
        return parsed.astype("datetime64[us]"), "datetime", invalid
    return parsed.dt.normalize().astype("datetime64[us]"), "date", invalid


def type_frame(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    used: set[str] = set()
    typed, meta = {}, []
    for pos, col in enumerate(raw.columns):
        ident = safe_identifier(str(col), used)
        series, dtype, invalid = infer_column(raw[col], str(col))
        typed[ident] = series.reset_index(drop=True)
        meta.append({"position": pos, "name": ident, "original_name": str(col), "display_name": str(col).strip(),
                     "dtype": dtype, "invalid_count": invalid,
                     "numeric_like_ratio": float(_to_number(raw[col][~_null_mask(raw[col])].head(2000)).notna().mean())
                     if dtype == "string" and (~_null_mask(raw[col])).any() else None})
    return pd.DataFrame(typed), meta
