"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]

    # 1. Metric values that cannot be compared: NaN / inf, in the PR or in the baseline.
    for name, rep in (("PR", pr), ("baseline", base)):
        for k, v in (rep.get("metrics") or {}).items():
            if isinstance(v, float) and not math.isfinite(v):
                problems.append(f"{name} metric {k} is {v}: a crashed or empty grader, not a score")

    # 2. Row count must match the manifest; every (item, seed) appears exactly once.
    man = pr.get("manifest") or {}
    want_rows = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want_rows:
        problems.append(f"{len(rows)} rows but manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want_rows} (dropped or duplicated rows)")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    seen: set = set()
    dups = sorted({k for k in keys if k in seen or seen.add(k)}, key=str)
    if dups:
        problems.append(f"duplicated (item, seed) rows: {dups[:5]}")

    # 3. Same (item, seed) set and same manifest as the baseline: no cherry-picked items or seeds.
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if set(keys) != base_keys:
        miss, extra = sorted(base_keys - set(keys), key=str), sorted(set(keys) - base_keys, key=str)
        problems.append(f"(item, seed) set differs from baseline: missing {miss[:5]}, extra {extra[:5]}")
    bman = base.get("manifest") or {}
    for f in ("items", "seeds"):
        if f in bman and man.get(f) != bman.get(f):
            problems.append(f"manifest {f} {man.get(f)} differs from baseline {bman.get(f)}")
    if spec.get("seeds") and sorted(man.get("seeds") or []) != sorted(spec["seeds"]):
        problems.append(f"manifest seeds {man.get('seeds')} differ from spec seeds {spec['seeds']}")

    # 4. Crashed graders: reported failures, or a graded metric missing / None on a row.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), first: {pr['evaluator_failures'][0]}")
    none_rows = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded if r.get(m) is None]
    if none_rows:
        problems.append(f"{len(none_rows)} graded value(s) missing/None, first {none_rows[0]}: "
                        f"a crashed grader drops out of the mean")

    # 5. Reported metrics must equal what the rows say (hand-edited summary numbers).
    for m in graded:
        vals = [r[m] for r in rows if r.get(m) is not None]
        rep_v = (pr.get("metrics") or {}).get(m)
        if not vals or not isinstance(rep_v, (int, float)) or isinstance(rep_v, bool) or not math.isfinite(rep_v):
            continue
        got = sum(vals) if m in COUNT_METRICS else sum(vals) / len(vals)
        if abs(got - rep_v) > 1e-3:
            problems.append(f"metric {m} reported {rep_v} but rows give {round(got, 4)}")

    # 6. Slice tags per item must match the baseline (relabelling hides a slice regression).
    def tags(rs: list[dict]) -> dict:
        out: dict = {}
        for r in rs:
            out.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
        return out
    pt, bt = tags(rows), tags(base_rows)
    relabelled = sorted(i for i in set(pt) & set(bt) if pt[i] != bt[i])
    if relabelled:
        problems.append(f"slice tags differ from baseline for {relabelled[:5]}")

    # 7. Ratchet: on the same eval-set version the spec may only get stricter.
    if base_spec is not None and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        problems += [f"RATCHET {p}" for p in _ratchet(spec, base_spec)]
    return problems


COUNT_METRICS = {"secret_leak", "approval_bypass"}   # aggregated as a count, not a mean (lab9.eval)


def _looser(new: dict, old: dict, what: str) -> list[str]:
    """Compare two threshold dicts (a metric threshold or a slice entry)."""
    out = []
    for k in ("min", "max", "max_increase"):
        if k in old and k not in new:
            out.append(f"{what}: {k} removed")
        elif k in old and k in new:
            if (k == "min" and new[k] < old[k]) or (k != "min" and new[k] > old[k]):
                out.append(f"{what}: {k} loosened {old[k]} -> {new[k]}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"{what}: no_significant_drop dropped")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    out = []
    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        n = new_m.get(m["id"])
        if n is None:
            out.append(f"metric {m['id']} removed")
            continue
        if m.get("blocking") and not n.get("blocking"):
            out.append(f"metric {m['id']} no longer blocking")
        out += _looser(n.get("threshold") or {}, m.get("threshold") or {}, f"metric {m['id']}")
    new_s = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        name, metric = s.get("name"), s.get("metric")
        n = new_s.get((name, metric))
        if n is None:
            out.append(f"slice {name}/{metric} removed")
            continue
        if s.get("blocking") and not n.get("blocking"):
            out.append(f"slice {name}/{metric} no longer blocking")
        out += _looser(n, s, f"slice {name}/{metric}")
    if base_spec.get("seeds") and not set(base_spec["seeds"]) <= set(spec.get("seeds") or []):
        out.append(f"seeds reduced {base_spec['seeds']} -> {spec.get('seeds')}")
    bc = (base_spec.get("bootstrap") or {}).get("confidence")
    nc = (spec.get("bootstrap") or {}).get("confidence")
    if bc is not None and nc is not None and nc < bc:
        out.append(f"bootstrap confidence lowered {bc} -> {nc}")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict, note = "fail", "no rows in slice"       # a slice emptied by relabelling must not pass
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if "max" in s and val > s["max"]:
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = "ok" if verdict == "ok" else ("BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
