"""Explicit dataset relationships: validated keys, cardinality, match rates, preview, and an explicit
materialisation step that creates a new joined dataset. Joins are never inferred silently."""
import pandas as pd
from sqlalchemy.orm import Session as DbSession

from app.core.errors import AppError
from app.models import DataRelationship, Dataset
from app.services.dataset import service
from app.services.dataset.ingestion import safe_identifier


def _load(db, workspace_id, dataset_id, column):
    ds = service.get_dataset(db, workspace_id, dataset_id)
    v = service.get_version(db, ds)
    cmap = service.column_map(v, include_excluded=True)
    if column not in cmap:
        raise AppError(422, "unknown_column", f"'{column}' is not a column of {ds.name}")
    return ds, v, service.load_frame(v), cmap


def json_rows(df: pd.DataFrame) -> list[list]:
    """DataFrame → JSON-safe rows (NaN/NaT → None, timestamps → ISO strings, numpy scalars → Python)."""
    def cell(v):
        if v is None or (not isinstance(v, (str, bytes)) and pd.isna(v)):
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v.item() if hasattr(v, "item") else v
    return [[cell(v) for v in row] for row in df.itertuples(index=False, name=None)]


def _key(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.lower()


def validate(db: DbSession, workspace_id: str, left_id: str, right_id: str, lcol: str, rcol: str, join_type: str) -> dict:
    if left_id == right_id:
        raise AppError(422, "invalid_relationship", "Choose two different datasets")
    lds, lv, ldf, lmap = _load(db, workspace_id, left_id, lcol)
    rds, rv, rdf, rmap = _load(db, workspace_id, right_id, rcol)
    lk, rk = _key(ldf[lcol]), _key(rdf[rcol])
    l_unique, r_unique = lk.dropna().is_unique, rk.dropna().is_unique
    card = {(True, True): "one_to_one", (False, True): "many_to_one", (True, False): "one_to_many", (False, False): "many_to_many"}[(l_unique, r_unique)]
    rset, lset = set(rk.dropna()), set(lk.dropna())
    l_match = lk.isin(rset)
    r_match = rk.isin(lset)
    warnings = []
    if card in ("one_to_many", "many_to_many"):
        warnings.append("Keys on the right side repeat, so joining will duplicate left-side rows. Totals of left-side measures would be inflated.")
    if lmap[lcol]["dtype"] != rmap[rcol]["dtype"]:
        warnings.append(f"Key types differ ({lmap[lcol]['dtype']} vs {rmap[rcol]['dtype']}); values are compared as text.")
    if l_match.mean() < 0.5:
        warnings.append(f"Only {l_match.mean() * 100:.0f}% of left rows have a match. Check that the selected columns hold the same keys.")
    joined = _join(ldf, rdf, lcol, rcol, join_type, lds, rds, lmap, rmap, limit=10)
    return {"left": {"dataset": lds.name, "column": lmap[lcol]["display_name"], "rows": len(ldf), "keys_unique": l_unique},
            "right": {"dataset": rds.name, "column": rmap[rcol]["display_name"], "rows": len(rdf), "keys_unique": r_unique},
            "cardinality": card, "join_type": join_type,
            "matched_left_rows": int(l_match.sum()), "unmatched_left_rows": int((~l_match).sum()),
            "unmatched_right_rows": int((~r_match).sum()),
            "unmatched_left_sample": [str(x) for x in ldf.loc[~l_match, lcol].dropna().astype(str).unique()[:10]],
            "unmatched_right_sample": [str(x) for x in rdf.loc[~r_match, rcol].dropna().astype(str).unique()[:10]],
            "match_rate": round(float(l_match.mean()) * 100, 1), "warnings": warnings,
            "preview": {"columns": list(joined[0].columns), "rows": json_rows(joined[0])},
            "result_rows": joined[1]}


def _join(ldf, rdf, lcol, rcol, how, lds, rds, lmap, rmap, limit=None):
    l = ldf.copy()
    r = rdf.copy()
    l["__k"], r["__k"] = _key(l[lcol]), _key(r[rcol])
    used = set(l.columns)
    rename = {}
    for c in r.columns:
        if c == "__k":
            continue
        if c in used:
            rename[c] = safe_identifier(f"{rds.name[:20]}_{c}", used)
        else:
            used.add(c)
    r = r.rename(columns=rename).drop(columns=[rename.get(rcol, rcol)])
    out = l.merge(r, on="__k", how=how).drop(columns="__k")
    total = len(out)
    return (out.head(limit) if limit else out), total


def materialize(db: DbSession, workspace_id: str, user_id: str, rel: DataRelationship, name: str, allow_mult: bool) -> Dataset:
    if rel.cardinality in ("one_to_many", "many_to_many") and not allow_mult:
        raise AppError(422, "row_multiplication", "This relationship duplicates rows. Confirm row multiplication to continue.")
    lds, lv, ldf, lmap = _load(db, workspace_id, rel.left_dataset_id, rel.left_column)
    rds, rv, rdf, rmap = _load(db, workspace_id, rel.right_dataset_id, rel.right_column)
    out, _ = _join(ldf, rdf, rel.left_column, rel.right_column, rel.join_type, lds, rds, lmap, rmap)
    meta = []
    for pos, c in enumerate(out.columns):
        src = lmap.get(c) or rmap.get(c) or next((rmap[k] for k in rmap if c.endswith(k)), None)
        dtype = src["dtype"] if src else "string"
        meta.append({"position": pos, "name": c, "original_name": src["original_name"] if src else c,
                     "display_name": (src["display_name"] if src else c) + (f" ({rds.name})" if c not in lmap and src and c != src["name"] else ""),
                     "dtype": dtype, "invalid_count": 0})
    ds = Dataset(workspace_id=workspace_id, name=name, original_filename=f"{lds.name} ⋈ {rds.name}", source_type="join",
                 status="processing", created_by=user_id,
                 description=f"{rel.join_type.title()} join of {lds.name}.{lmap[rel.left_column]['display_name']} = "
                             f"{rds.name}.{rmap[rel.right_column]['display_name']} ({rel.cardinality.replace('_', '-')})",
                 import_report={"source": "join", "relationship_id": rel.id, "left_version": lv.id, "right_version": rv.id})
    db.add(ds)
    db.flush()
    service.create_version(db, ds, out.reset_index(drop=True), meta, user_id, note="Materialised from relationship")
    rel.materialized_dataset_id = ds.id
    return ds


def rel_out(db: DbSession, r: DataRelationship) -> dict:
    l, rr = db.get(Dataset, r.left_dataset_id), db.get(Dataset, r.right_dataset_id)
    return {"id": r.id, "left_dataset": {"id": r.left_dataset_id, "name": l.name if l else "?"},
            "right_dataset": {"id": r.right_dataset_id, "name": rr.name if rr else "?"},
            "left_column": r.left_column, "right_column": r.right_column, "join_type": r.join_type,
            "cardinality": r.cardinality, "validation": r.validation, "materialized_dataset_id": r.materialized_dataset_id,
            "created_at": r.created_at.isoformat()}
