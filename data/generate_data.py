"""Generates the synthetic payments database and an independent ground-truth file."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

SEED = 42
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "paymentlens.duckdb"
GT_PATH = DATA_DIR / "ground_truth.json"

START = date(2026, 10, 19)
N_DAYS = 28
AS_OF = datetime(2026, 11, 16, 6, 0, 0)
DAILY_ORDERS = 3200

WEEKS = {
    "W1": (date(2026, 10, 19), date(2026, 10, 25)),
    "W2": (date(2026, 10, 26), date(2026, 11, 1)),
    "W3": (date(2026, 11, 2), date(2026, 11, 8)),
    "W4": (date(2026, 11, 9), date(2026, 11, 15)),
}

BANKS = [
    ("B01", "Metro Bank", "PRIVATE"),
    ("B02", "Horizon Bank", "PRIVATE"),
    ("B03", "Nova Bank", "PUBLIC"),
    ("B04", "Zenith Bank", "COOPERATIVE"),
]
BANK_ID = {name: bid for bid, name, _ in BANKS}
BASE_BANK_RATE = {"Metro Bank": 0.94, "Horizon Bank": 0.92, "Nova Bank": 0.91, "Zenith Bank": 0.81}
BASE_BANK_SHARE = {"Metro Bank": 0.32, "Horizon Bank": 0.30, "Nova Bank": 0.26, "Zenith Bank": 0.12}
METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
METHOD_SHARE = [0.45, 0.30, 0.15, 0.10]
METHOD_ADJ = {"UPI": 0.01, "CARD": -0.01, "NETBANKING": -0.03, "WALLET": 0.0}
CATEGORIES = ["Ecommerce", "Food", "Travel", "Gaming", "Education", "Utilities"]
CATEGORY_ADJ = {"Travel": -0.01, "Gaming": -0.02}
REGIONS = ["North", "South", "West"]
REGION_P = [0.40, 0.35, 0.25]

NORMAL_DECLINES = ["INSUFFICIENT_FUNDS", "AUTHENTICATION_FAILED", "SUSPECTED_FRAUD", "TIMEOUT", "ISSUER_UNAVAILABLE"]
NORMAL_DECLINE_P = [0.35, 0.25, 0.15, 0.15, 0.10]

OUTAGE_DAYS = {date(2026, 11, 11), date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 14)}
OUTAGE_RATE = 0.70
P_CANCEL, P_PENDING, P_RETRY = 0.02, 0.008, 0.35

ANOMALIES = {"duplicate_rows": 500, "missing_bank_ids": 250, "future_timestamps": 20, "invalid_statuses": 10}


def week_of(d: date) -> str | None:
    for w, (a, b) in WEEKS.items():
        if a <= d <= b:
            return w
    return None


def bank_shares(d: date) -> dict[str, float]:
    w = week_of(d)
    z = {"W2": 0.28, "W4": 0.26}.get(w, BASE_BANK_SHARE["Zenith Bank"])
    others = {k: v for k, v in BASE_BANK_SHARE.items() if k != "Zenith Bank"}
    s = sum(others.values())
    shares = {k: v / s * (1 - z) for k, v in others.items()}
    shares["Zenith Bank"] = z
    return shares


def segment_rate(bank: str, method: str, category: str, d: date) -> tuple[float, float]:
    """Returns (actual rate, normal rate) for one attempt; they differ only during the planted outage."""
    r = BASE_BANK_RATE[bank] + METHOD_ADJ[method] + CATEGORY_ADJ.get(category, 0.0)
    if week_of(d) == "W2":
        r += 0.008
    r = min(r, 0.99)
    if bank == "Nova Bank" and method == "UPI" and d in OUTAGE_DAYS:
        return OUTAGE_RATE, r
    return r, r


def build_merchants(rng: np.random.Generator) -> pd.DataFrame:
    n = 100
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "merchant_id": f"M{i:03d}",
            "merchant_name": f"Merchant {i:03d}",
            "category": CATEGORIES[(i - 1) % len(CATEGORIES)],
            "region": rng.choice(REGIONS, p=REGION_P),
            "risk_tier": rng.choice(["LOW", "MEDIUM", "HIGH"], p=[0.6, 0.3, 0.1]),
            "signup_date": date(2024, 1, 1) + timedelta(days=int(rng.integers(0, 600))),
            # fake sensitive columns, used to demo access control
            "settlement_account": "SYNTH" + "".join(str(x) for x in rng.integers(0, 10, 10)),
            "contact_email": f"ops@merchant{i:03d}.example",
        })
    return pd.DataFrame(rows)


def simulate_day(rng, d: date, merchants: pd.DataFrame, weights: np.ndarray, start_idx: int,
                 n_orders: int, hours: float = 24.0, partial: bool = False) -> list[dict]:
    shares = bank_shares(d)
    bank_names = list(shares)
    bank_p = np.array([shares[b] for b in bank_names])
    m_idx = rng.choice(len(merchants), size=n_orders, p=weights)
    banks = rng.choice(bank_names, size=n_orders, p=bank_p)
    methods = rng.choice(METHODS, size=n_orders, p=METHOD_SHARE)
    secs = np.sort(rng.uniform(0, hours * 3600, size=n_orders))
    day_start = datetime(d.year, d.month, d.day)
    rows: list[dict] = []
    txn = start_idx
    for k in range(n_orders):
        m = merchants.iloc[m_idx[k]]
        order_id = f"O{start_idx + k:07d}"
        ts = day_start + timedelta(seconds=float(secs[k]))
        method = methods[k]
        for attempt in (1, 2):
            r_eff, r_norm = segment_rate(banks[k], method, m["category"], d)
            u = rng.random()
            decline = None
            if u < P_CANCEL:
                status = "USER_CANCELLED"
            elif u < P_CANCEL + P_PENDING:
                status = "PENDING"
            else:
                v = rng.random()
                if v < r_eff:
                    status = "SUCCESS"
                    if partial and rng.random() < 0.30:
                        status = "PENDING"  # not yet confirmed at load time
                elif v < r_norm:
                    status, decline = "FAILED", "ISSUER_UNAVAILABLE"  # failed because of the planted outage
                else:
                    status = "FAILED"
                    decline = str(rng.choice(NORMAL_DECLINES, p=NORMAL_DECLINE_P))
            txn += 1
            rows.append({
                "txn_id": f"T{txn:08d}",
                "order_id": order_id,
                "attempt_no": attempt,
                "merchant_id": m["merchant_id"],
                "bank_id": BANK_ID[banks[k]],
                "payment_method": method,
                "created_at": ts,
                "ingested_at": ts + timedelta(seconds=int(rng.integers(5, 120))),
                "amount": round(float(rng.lognormal(7.0, 0.9)), 2),
                "currency": "INR",
                "status": status,
                "decline_reason": decline,
                "region": m["region"],
            })
            if status == "FAILED" and attempt == 1 and rng.random() < P_RETRY:
                ts = ts + timedelta(seconds=int(rng.integers(30, 600)))
                if rng.random() > 0.7:
                    method = str(rng.choice(["UPI", "CARD"]))
                continue
            break
    return rows


def build_transactions(rng, merchants: pd.DataFrame) -> pd.DataFrame:
    weights = rng.lognormal(0, 1.0, len(merchants))
    weights = weights / weights.sum()
    rows: list[dict] = []
    idx = 0
    for i in range(N_DAYS):
        d = START + timedelta(days=i)
        n = int(rng.poisson(DAILY_ORDERS * (0.9 if d.weekday() >= 5 else 1.0)))
        day_rows = simulate_day(rng, d, merchants, weights, idx, n)
        rows.extend(day_rows)
        idx += len(day_rows) + n
    # partially loaded last day (00:00-06:00)
    d = AS_OF.date()
    n = int(DAILY_ORDERS * 0.12)
    rows.extend(simulate_day(rng, d, merchants, weights, idx, n, hours=6.0, partial=True))
    return pd.DataFrame(rows)


def inject_anomalies(rng, clean: pd.DataFrame) -> pd.DataFrame:
    raw = clean.copy()
    # 1) duplicates: the same FAILED rows loaded twice on Nov 12-13
    mask = (raw.status == "FAILED") & raw.created_at.dt.date.isin([date(2026, 11, 12), date(2026, 11, 13)])
    dup_idx = rng.choice(raw.index[mask], size=ANOMALIES["duplicate_rows"], replace=False)
    dups = raw.loc[dup_idx].copy()
    dups["ingested_at"] = dups["ingested_at"] + pd.Timedelta(hours=3)
    # 2) missing bank ids (kept in the clean data and shown as bank UNKNOWN)
    w34 = raw.index[raw.created_at.dt.date >= WEEKS["W3"][0]]
    miss_idx = rng.choice(w34, size=ANOMALIES["missing_bank_ids"], replace=False)
    raw.loc[miss_idx, "bank_id"] = None
    # 3) future timestamps (bad device clock) - extra rows
    fut = raw.sample(ANOMALIES["future_timestamps"], random_state=1).copy()
    fut["txn_id"] = [f"TF{i:07d}" for i in range(len(fut))]
    fut["created_at"] = pd.Timestamp("2027-03-01 10:00:00")
    fut["ingested_at"] = pd.Timestamp("2026-11-15 10:00:00")
    # 4) invalid statuses - extra rows
    inv = raw.sample(ANOMALIES["invalid_statuses"], random_state=2).copy()
    inv["txn_id"] = [f"TI{i:07d}" for i in range(len(inv))]
    inv["status"] = ["SUCESS", "Failed ", "success", "UNKNOWN", "SUCESS", "ERR", "Failed ", "SUCESS", "success", "ERR"]
    raw = pd.concat([raw, dups, fut, inv], ignore_index=True)
    return raw.sort_values(["created_at", "txn_id"]).reset_index(drop=True)


def build_settlements(rng, trusted: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    succ = trusted[(trusted.status == "SUCCESS") & (trusted.created_at < pd.Timestamp("2026-11-16"))].copy()
    lag = np.where(rng.random(len(succ)) < 0.05, 2, 1)
    succ["settlement_date"] = (succ.created_at.dt.normalize() + pd.to_timedelta(lag, unit="D")).dt.date
    # settlements for day D are paid at 02:00 on day D, so anything after the data date is still pending
    succ["settlement_status"] = np.where(succ["settlement_date"] <= AS_OF.date(), "SETTLED", "PENDING")
    # some week-4 payments get no settlement record at all
    w4 = succ.index[succ.created_at.dt.date >= WEEKS["W4"][0]]
    missing = rng.choice(w4, size=int(len(w4) * 0.004), replace=False)
    succ = succ.drop(index=missing)
    succ["gross_amount"] = succ["amount"]
    mism = rng.choice(succ.index, size=40, replace=False)
    succ.loc[mism, "gross_amount"] = (succ.loc[mism, "amount"] * 0.9).round(2)
    succ["fee_amount"] = (succ["gross_amount"] * 0.018).round(2)
    succ["net_amount"] = (succ["gross_amount"] - succ["fee_amount"]).round(2)
    succ = succ.reset_index(drop=True)
    succ["settlement_id"] = [f"S{i:08d}" for i in range(len(succ))]
    cols = ["settlement_id", "txn_id", "merchant_id", "settlement_date", "settlement_status",
            "gross_amount", "fee_amount", "net_amount"]
    info = {"missing_settlement_records": int(len(missing)), "amount_mismatches": 40}
    return succ[cols], info


def trusted_view(raw: pd.DataFrame) -> pd.DataFrame:
    """Same cleaning rules as the SQL 'transactions' view, done in pandas (only used for ground truth)."""
    t = raw[raw.status.isin(["SUCCESS", "FAILED", "PENDING", "USER_CANCELLED"])]
    t = t[t.created_at <= pd.Timestamp(AS_OF)]
    t = t.sort_values(["txn_id", "ingested_at"]).drop_duplicates("txn_id", keep="first")
    return t


def gt_rate(df: pd.DataFrame) -> dict:
    term = df[df.status.isin(["SUCCESS", "FAILED"])]
    s = int((term.status == "SUCCESS").sum())
    return {"successes": s, "attempts": int(len(term)), "rate": s / len(term)}


def in_week(df, w):
    a, b = WEEKS[w]
    return df[(df.created_at >= pd.Timestamp(a)) & (df.created_at < pd.Timestamp(b) + pd.Timedelta(days=1))]


def gt_decompose(prev: pd.DataFrame, cur: pd.DataFrame, keys: list[str]) -> dict:
    def seg(df):
        term = df[df.status.isin(["SUCCESS", "FAILED"])].copy()
        term["succ"] = (term.status == "SUCCESS").astype(int)
        g = term.groupby(keys).agg(n=("succ", "size"), s=("succ", "sum"))
        g["w"] = g.n / g.n.sum()
        g["r"] = g.s / g.n
        return g
    p, c = seg(prev), seg(cur)
    j = pd.merge(p, c, left_index=True, right_index=True, how="outer", suffixes=("0", "1"))
    j["w0"] = j.w0.fillna(0)
    j["w1"] = j.w1.fillna(0)
    j["r0"] = j.r0.fillna(j.r1)
    j["r1"] = j.r1.fillna(j.r0)
    R0 = (p.s.sum() / p.n.sum())
    R1 = (c.s.sum() / c.n.sum())
    rate = ((j.w0 + j.w1) / 2 * (j.r1 - j.r0))
    mix = ((j.r0 + j.r1) / 2 - (R0 + R1) / 2) * (j.w1 - j.w0)
    cf = float((j.w0 * j.r1).sum())
    top_rate = rate.idxmin()
    top_mix = mix.idxmin()
    top_contrib = (rate + mix).idxmin()
    fmt = lambda k: " | ".join(k) if isinstance(k, tuple) else str(k)
    return {
        "R0": R0, "R1": R1, "delta": R1 - R0,
        "rate_effect": float(rate.sum()), "mix_effect": float(mix.sum()),
        "counterfactual_rate": cf,
        "top_negative_rate_segment": fmt(top_rate), "top_negative_rate_effect": float(rate.min()),
        "top_negative_mix_segment": fmt(top_mix), "top_negative_mix_effect": float(mix.min()),
        "top_negative_contribution_segment": fmt(top_contrib),
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merchants = build_merchants(rng)
    banks = pd.DataFrame(BANKS, columns=["bank_id", "bank_name", "bank_type"])
    clean = build_transactions(rng, merchants)
    raw = inject_anomalies(rng, clean)
    trusted = trusted_view(raw)
    settlements, s_info = build_settlements(rng, trusted)

    if DB_PATH.exists():
        DB_PATH.unlink()
    con = duckdb.connect(str(DB_PATH))
    for name, df in [("merchants", merchants), ("banks", banks), ("transactions_raw", raw), ("settlements", settlements)]:
        con.register("df_tmp", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM df_tmp")
        con.unregister("df_tmp")
    con.execute("ALTER TABLE transactions_raw ALTER created_at TYPE TIMESTAMP")
    con.execute(f"""
        CREATE VIEW transactions AS
        SELECT * FROM transactions_raw
        WHERE status IN ('SUCCESS','FAILED','PENDING','USER_CANCELLED')
          AND created_at <= TIMESTAMP '{AS_OF:%Y-%m-%d %H:%M:%S}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY txn_id ORDER BY ingested_at) = 1
    """)
    con.execute("CREATE TABLE meta (key VARCHAR, value VARCHAR)")
    meta = {"data_as_of": AS_OF.strftime("%Y-%m-%d %H:%M:%S"), "seed": str(SEED),
            "data_version": datetime.now().strftime("%Y%m%d%H%M%S"), "generator": "data/generate_data.py"}
    con.executemany("INSERT INTO meta VALUES (?, ?)", list(meta.items()))
    con.close()

    # ---------------- correct answers, calculated with pandas separately from the app ----------------
    t = trusted.copy()
    t["bank"] = t.bank_id.map({b: n for b, n, _ in BANKS}).fillna("UNKNOWN")
    weekly = {w: gt_rate(in_week(t, w)) for w in WEEKS}
    w4_raw = gt_rate(in_week(raw[raw.status.isin(["SUCCESS", "FAILED"])], "W4"))
    nova_upi = lambda df: df[(df.bank == "Nova Bank") & (df.payment_method == "UPI")]
    nu3, nu4 = gt_rate(nova_upi(in_week(t, "W3"))), gt_rate(nova_upi(in_week(t, "W4")))
    f4 = nova_upi(in_week(t, "W4"))
    f4 = f4[f4.status == "FAILED"].decline_reason.value_counts()
    bank_share = lambda df: (df[df.status.isin(["SUCCESS", "FAILED"])].bank.value_counts(normalize=True)).to_dict()
    per_bank = lambda df: {b: gt_rate(g)["rate"] for b, g in df.groupby("bank")}
    orders = lambda df: df[df.status.isin(["SUCCESS", "FAILED"])].groupby("order_id").status.apply(lambda s: (s == "SUCCESS").any())
    partial = gt_rate(t[t.created_at >= pd.Timestamp("2026-11-16")])
    dup_extra = int(raw.duplicated("txn_id").sum())

    gt = {
        "description": "Ground truth computed by data/generate_data.py with pandas (independent of app code).",
        "data_as_of": meta["data_as_of"],
        "planted": {
            "zenith_share_by_week": {"W1": 0.12, "W2": 0.28, "W3": 0.12, "W4": 0.26},
            "w2_segment_uplift": 0.008,
            "nova_upi_outage_days": sorted(str(x) for x in OUTAGE_DAYS),
            "nova_upi_outage_rate": OUTAGE_RATE,
            "anomalies": ANOMALIES,
            "settlements": s_info,
        },
        "weeks": {w: [str(a), str(b)] for w, (a, b) in WEEKS.items()},
        "weekly_success_rate": weekly,
        "weekly_order_conversion": {w: float(orders(in_week(t, w)).mean()) for w in WEEKS},
        "w4_raw_success_rate": w4_raw,
        "w4_vs_w3_bank_x_method": gt_decompose(in_week(t, "W3"), in_week(t, "W4"), ["bank", "payment_method"]),
        "w4_vs_w3_bank": gt_decompose(in_week(t, "W3"), in_week(t, "W4"), ["bank"]),
        "w2_vs_w1_bank": gt_decompose(in_week(t, "W1"), in_week(t, "W2"), ["bank"]),
        "w1_bank_rates": per_bank(in_week(t[t.status.isin(["SUCCESS", "FAILED"])], "W1")),
        "w2_bank_rates": per_bank(in_week(t[t.status.isin(["SUCCESS", "FAILED"])], "W2")),
        "bank_share": {"W3": bank_share(in_week(t, "W3")), "W4": bank_share(in_week(t, "W4"))},
        "nova_upi": {"W3": nu3, "W4": nu4, "w4_top_decline_reason": str(f4.index[0]),
                     "w4_decline_reason_counts": {k: int(v) for k, v in f4.items()}},
        "data_quality": {
            "duplicate_extra_rows": dup_extra,
            "missing_bank_id_rows": int(trusted.bank_id.isna().sum()),
            "future_timestamp_rows": int((raw.created_at > pd.Timestamp(AS_OF)).sum()),
            "invalid_status_rows": int((~raw.status.isin(["SUCCESS", "FAILED", "PENDING", "USER_CANCELLED"])).sum()),
            "partial_day": {"date": "2026-11-16", **partial},
        },
        "row_counts": {"transactions_raw": int(len(raw)), "transactions_trusted": int(len(trusted)),
                       "merchants": int(len(merchants)), "banks": int(len(banks)), "settlements": int(len(settlements))},
    }
    GT_PATH.write_text(json.dumps(gt, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {DB_PATH} and {GT_PATH}")
    print(json.dumps({k: gt[k] for k in ["weekly_success_rate", "w4_vs_w3_bank_x_method", "w2_vs_w1_bank", "row_counts"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
