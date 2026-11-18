"""Restricted metric formula language.

Grammar (case-insensitive function names):
    expr      := term (('+' | '-') term)*
    term      := unary (('*' | '/') unary)*
    unary     := '-' unary | primary
    primary   := NUMBER | '(' expr ')' | aggregate          (aggregate mode)
               | NUMBER | '(' expr ')' | COLUMN             (row mode: calculated fields)
    aggregate := SUM|AVG|MIN|MAX '(' rowexpr ')' | COUNT '(' '*' ')' | COUNT_DISTINCT '(' COLUMN ')'
               | SUM_IF|AVG_IF '(' rowexpr ',' condition ')' | COUNT_IF '(' condition ')'
    condition := comparison (AND|OR comparison)* ; comparison := COLUMN op literal | '(' condition ')'

The parser produces an AST that is validated against dataset metadata and compiled to SQL with every
literal bound as a parameter. Division is always compiled as x / NULLIF(y, 0). Nothing is ever evaluated
with eval/exec."""
import re
from dataclasses import dataclass

from app.core.errors import AppError
from app.services.execution.engine import quote_ident

AGGS = {"SUM", "AVG", "MIN", "MAX", "COUNT", "COUNT_DISTINCT", "SUM_IF", "AVG_IF", "COUNT_IF"}
NUMERIC = ("integer", "float")
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|('(?:[^'\\]|\\.)*')|([A-Za-z_][A-Za-z0-9_]*)|(<>|!=|>=|<=|[-+*/(),=<>*]))")


def _err(msg: str) -> AppError:
    return AppError(422, "invalid_formula", msg)


def tokenize(text: str) -> list[tuple[str, str]]:
    if len(text) > 1000:
        raise _err("Formula is too long")
    pos, out = 0, []
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise _err(f"Unexpected character at position {pos + 1}: '{text[pos]}'")
        num, s, ident, op = m.groups()
        if num:
            out.append(("num", num))
        elif s:
            out.append(("str", s[1:-1].replace("\\'", "'")))
        elif ident:
            out.append(("ident", ident))
        else:
            out.append(("op", op))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, tokens, mode: str):
        self.t, self.i, self.mode = tokens, 0, mode

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else ("eof", "")

    def take(self, kind=None, value=None):
        tok = self.peek()
        if (kind and tok[0] != kind) or (value and tok[1].upper() != value):
            raise _err(f"Expected {value or kind} but found '{tok[1] or 'end of formula'}'")
        self.i += 1
        return tok

    def parse(self):
        node = self.expr(self.mode)
        if self.peek()[0] != "eof":
            raise _err(f"Unexpected '{self.peek()[1]}'")
        return node

    def expr(self, mode):
        node = self.term(mode)
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            node = {"t": "bin", "op": op, "l": node, "r": self.term(mode)}
        return node

    def term(self, mode):
        node = self.unary(mode)
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            node = {"t": "bin", "op": op, "l": node, "r": self.unary(mode)}
        return node

    def unary(self, mode):
        if self.peek() == ("op", "-"):
            self.take()
            return {"t": "neg", "e": self.unary(mode)}
        return self.primary(mode)

    def primary(self, mode):
        kind, val = self.peek()
        if kind == "num":
            self.take()
            return {"t": "num", "v": float(val)}
        if (kind, val) == ("op", "("):
            self.take()
            node = self.expr(mode)
            self.take("op", ")")
            return node
        if kind == "ident":
            up = val.upper()
            if up in AGGS:
                if mode != "aggregate":
                    raise _err(f"{up} cannot be used inside a row-level expression")
                return self.aggregate()
            if mode == "aggregate":
                raise _err(f"Column '{val}' must be wrapped in an aggregation such as SUM({val})")
            self.take()
            return {"t": "col", "name": val.lower()}
        raise _err(f"Unexpected '{val or 'end of formula'}'")

    def aggregate(self):
        fn = self.take("ident")[1].upper()
        self.take("op", "(")
        node = {"t": "agg", "fn": fn, "arg": None, "cond": None}
        if fn == "COUNT":
            self.take("op", "*")
        elif fn == "COUNT_DISTINCT":
            node["arg"] = {"t": "col", "name": self.take("ident")[1].lower()}
        elif fn == "COUNT_IF":
            node["cond"] = self.condition()
        else:
            node["arg"] = self.expr("row")
            if fn.endswith("_IF"):
                self.take("op", ",")
                node["cond"] = self.condition()
        self.take("op", ")")
        return node

    def condition(self):
        node = self.comparison()
        while self.peek()[0] == "ident" and self.peek()[1].upper() in ("AND", "OR"):
            op = self.take()[1].upper()
            node = {"t": "bool", "op": op, "l": node, "r": self.comparison()}
        return node

    def comparison(self):
        if self.peek() == ("op", "("):
            self.take()
            node = self.condition()
            self.take("op", ")")
            return node
        col = self.take("ident")[1].lower()
        op = self.take("op")[1]
        if op not in ("=", "!=", "<>", ">", ">=", "<", "<="):
            raise _err(f"Unsupported comparison '{op}'")
        neg = False
        if self.peek() == ("op", "-"):
            self.take()
            neg = True
        kind, val = self.take()
        if kind not in ("num", "str"):
            raise _err("Comparisons must use a number or a 'quoted text' value")
        value = (-float(val) if neg else float(val)) if kind == "num" else val
        return {"t": "cmp", "col": col, "op": "<>" if op == "!=" else op, "v": value}


def parse(formula: str, mode: str = "aggregate") -> dict:
    tokens = tokenize(formula)
    if not tokens:
        raise _err("Formula is empty")
    return _Parser(tokens, mode).parse()


@dataclass
class Compiled:
    sql: str
    params: list
    columns: list[str]
    kind: str  # additive|ratio|distinct|average|extreme|row


def validate_and_compile(ast: dict, columns: dict[str, dict]) -> Compiled:
    used: list[str] = []
    params: list = []
    kinds: set[str] = set()

    def col(name, need_numeric=True):
        c = columns.get(name)
        if not c:
            raise _err(f"Unknown column '{name}'")
        if c.get("excluded"):
            raise _err(f"Column '{name}' is excluded from analysis")
        if need_numeric and c["dtype"] not in NUMERIC:
            raise _err(f"Column '{name}' is {c['dtype']}, but a numeric column is required here")
        if name not in used:
            used.append(name)
        return quote_ident(name)

    def cond(n):
        if n["t"] == "bool":
            return f"({cond(n['l'])} {n['op']} {cond(n['r'])})"
        c = columns.get(n["col"])
        q = col(n["col"], need_numeric=False)
        if c["dtype"] in NUMERIC and not isinstance(n["v"], float):
            raise _err(f"Column '{n['col']}' is numeric; compare it with a number")
        if c["dtype"] == "string" and not isinstance(n["v"], str):
            raise _err(f"Column '{n['col']}' is text; compare it with a 'quoted value'")
        params.append(n["v"])
        if c["dtype"] in ("date", "datetime"):
            return f"{q} {n['op']} CAST(? AS DATE)"
        return f"{q} {n['op']} ?"

    def row(n):
        t = n["t"]
        if t == "num":
            params.append(n["v"])
            return "CAST(? AS DOUBLE)"
        if t == "col":
            return col(n["name"])
        if t == "neg":
            return f"(-{row(n['e'])})"
        if t == "bin":
            l, r = row(n["l"]), row(n["r"])
            return f"({l} / NULLIF({r}, 0))" if n["op"] == "/" else f"({l} {n['op']} {r})"
        raise _err("Invalid row expression")

    def agg(n):
        t = n["t"]
        if t == "num":
            params.append(n["v"])
            return "CAST(? AS DOUBLE)"
        if t == "neg":
            return f"(-{agg(n['e'])})"
        if t == "bin":
            l, r = agg(n["l"]), agg(n["r"])
            if n["op"] in ("/", "*"):
                kinds.add("ratio")
            return f"({l} / NULLIF({r}, 0))" if n["op"] == "/" else f"({l} {n['op']} {r})"
        if t == "agg":
            fn = n["fn"]
            if fn == "COUNT":
                kinds.add("additive")
                return "CAST(COUNT(*) AS DOUBLE)"
            if fn == "COUNT_DISTINCT":
                kinds.add("distinct")
                return f"CAST(COUNT(DISTINCT {col(n['arg']['name'], need_numeric=False)}) AS DOUBLE)"
            if fn == "COUNT_IF":
                kinds.add("additive")
                return f"CAST(COUNT(*) FILTER (WHERE {cond(n['cond'])}) AS DOUBLE)"
            inner = row(n["arg"])
            base = fn.replace("_IF", "")
            kinds.add({"SUM": "additive", "AVG": "average", "MIN": "extreme", "MAX": "extreme"}[base])
            filt = f" FILTER (WHERE {cond(n['cond'])})" if n["cond"] else ""
            return f"CAST({base}({inner}){filt} AS DOUBLE)"
        raise _err("Formula must be built from aggregations such as SUM(column)")

    if ast["t"] in ("col",) or (ast["t"] == "bin" and _is_row(ast)) or ast["t"] == "neg" and _is_row(ast["e"]):
        sql = row(ast)
        return Compiled(sql, params, used, "row")
    sql = agg(ast)
    kind = "ratio" if "ratio" in kinds else "distinct" if "distinct" in kinds else "average" if "average" in kinds \
        else "extreme" if "extreme" in kinds else "additive"
    return Compiled(sql, params, used, kind)


def _is_row(n: dict) -> bool:
    if n["t"] == "agg":
        return False
    if n["t"] == "bin":
        return _is_row(n["l"]) and _is_row(n["r"])
    if n["t"] == "neg":
        return _is_row(n["e"])
    return n["t"] in ("col", "num")


def compile_row_expression(expression: str, columns: dict[str, dict]) -> Compiled:
    ast = parse(expression, mode="row")
    return validate_and_compile(ast, columns)


def humanize(formula: str, columns: dict[str, dict]) -> str:
    """Formula with internal column names replaced by display names, for explanations."""
    def rep(m):
        name = m.group(0)
        c = columns.get(name.lower())
        return f"[{c['display_name']}]" if c else name
    return re.sub(r"(?<!')\b[a-z_][a-z0-9_]*\b(?!')", rep, formula)
