"""Role-based access: denies restricted data, lists restricted columns and rewrites SQL by region."""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from core.config import policies, semantic
from core.models import AnalysisIntent


@dataclass
class PolicyDecision:
    status: str                       # ALLOWED / SCOPED / DENIED
    reasons: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    allowed_scope: list[str] = field(default_factory=list)
    alternative: str | None = None
    scoped_filters: dict[str, list[str]] | None = None


def role_config(role: str) -> dict:
    roles = policies()["roles"]
    if role not in roles:
        raise KeyError(f"Unknown role '{role}'")
    return roles[role]


def role_labels() -> dict[str, str]:
    return {k: v["label"] for k, v in policies()["roles"].items()}


def restricted_columns(role: str) -> set[str]:
    return set(role_config(role).get("restricted_columns") or [])


def check_intent(intent: AnalysisIntent, role: str, filters: dict[str, list[str]]) -> PolicyDecision:
    cfg = role_config(role)
    attrs = semantic()["attributes"]
    blocked = [a for a in intent.requested_attributes
               if a in attrs and attrs[a]["column"] in restricted_columns(role)]
    scope = cfg.get("row_scope")
    allowed_scope = ["Aggregated payment performance (success rate, conversion, GMV, volume)",
                     "Breakdowns by bank, payment method, merchant category, region, merchant ID, decline reason"]
    if scope:
        allowed_scope.append(f"Only rows where {scope['column']} = {scope['value']}")
    if blocked:
        labels = ", ".join(attrs[a]["label"] for a in blocked)
        return PolicyDecision(
            status="DENIED",
            reasons=[f"Role '{cfg['label']}' is not permitted to access: {labels}."],
            allowed_scope=allowed_scope,
            alternative="I can show merchant-level payment performance by merchant ID instead, "
                        "e.g. 'Show payment success rate by merchant for last week'.")
    decision = PolicyDecision(status="ALLOWED", allowed_scope=allowed_scope, scoped_filters=dict(filters))
    if scope:
        col, val = scope["column"], scope["value"]
        req = filters.get(col)
        if req and req != [val]:
            decision.notices.append(f"Your access is limited to {col} = {val}; the requested {col} filter "
                                    f"{req} was replaced with [{val}].")
        elif col in intent.dimensions:
            decision.notices.append(f"Your access is limited to {col} = {val}; other {col}s are not visible.")
        else:
            decision.notices.append(f"Results are limited to {col} = {val} (your data scope).")
        decision.scoped_filters[col] = [val]
        decision.status = "SCOPED"
    return decision


def apply_row_scope(tree: exp.Expression | None, role: str, original_sql: str) -> str:
    scope = role_config(role).get("row_scope")
    if not scope or tree is None:
        return original_sql
    rules = policies()["scope_rules"]
    tree = tree.copy()
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in list(tree.find_all(exp.Table)):
        name = t.name.lower()
        if name in rules and name not in ctes:
            alias = t.alias or t.name
            sub = sqlglot.parse_one(rules[name].format(value=scope["value"].replace("'", "''")), read="duckdb")
            t.replace(sub.subquery(alias))
    return tree.sql(dialect="duckdb", pretty=True)
