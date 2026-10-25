"""Make the invariants.db mirror match results/leaderboard.json before a checker run.

    .venvs/hub/bin/python -m harden.store.reconcile

patched and unpatched entries: exactly one complete invariant row per listed exploit
(rows missing from the mirror are extracted from the replay evidence, up to 3 tries),
stale rows deleted, evidence_path set to that exploit's replay. robust entries: rows
deleted. failed_to_run entries and environments not on the leaderboard: untouched.
"""

from __future__ import annotations

import json
import posixpath
import sys

from harden.store import mirror

EXPLOITED = ("patched", "unpatched")
TEXT_FIELDS = ("mechanism", "root_cause", "preconditions", "defense_pattern")


def _complete(row: dict) -> bool:
    return all(isinstance(row.get(f), str) and len(row[f].strip()) >= mirror.MIN_TEXT for f in TEXT_FIELDS)


def reconcile(extract_missing=None) -> list[str]:
    """Returns a list of actions taken. extract_missing(entry, exploit) -> Invariant | None
    is called for an exploit with no complete row."""
    board = json.loads((mirror.ROOT / "results" / "leaderboard.json").read_text())
    entries = board["entries"] if isinstance(board, dict) else board
    actions = []
    for entry in entries:
        env_id, status = entry["env_id"], entry["status"]
        rows = {r["exploit_id"]: r for r in mirror.invariant_rows(env_id)}
        if status == "robust":
            for exploit_id in rows:
                mirror.delete_invariant(env_id, exploit_id)
                actions.append(f"{env_id}: deleted row {exploit_id} (robust entry)")
            continue
        if status not in EXPLOITED:
            continue
        listed = {e["exploit_id"]: e for e in entry["exploits"]}
        for exploit_id in sorted(set(rows) - set(listed)):
            mirror.delete_invariant(env_id, exploit_id)
            actions.append(f"{env_id}: deleted stale row {exploit_id}")
        for exploit_id, exploit in listed.items():
            path = posixpath.join(entry["evidence_dir"], exploit["replay"])
            row = rows.get(exploit_id)
            if row is not None and _complete(row):
                if row.get("evidence_path") != path:
                    inv = mirror.Invariant(
                        env_id=env_id, exploit_id=exploit_id, title=row.get("title") or exploit_id,
                        mechanism=row["mechanism"], root_cause=row["root_cause"], preconditions=row["preconditions"],
                        defense_pattern=row["defense_pattern"], evidence_path=path,
                        embedding_model=row.get("embedding_model") or "", embedding=row.get("embedding"),
                    )
                    mirror.record_invariant(inv)
                    actions.append(f"{env_id}: set evidence_path of {exploit_id}")
                continue
            if extract_missing is None:
                actions.append(f"{env_id}: MISSING row {exploit_id} (no extractor given)")
                continue
            for _ in range(3):
                inv = extract_missing(entry, exploit)
                if inv is not None:
                    inv.evidence_path = path
                    mirror.record_invariant(inv)
                    actions.append(f"{env_id}: extracted missing row {exploit_id}")
                    break
            else:
                actions.append(f"{env_id}: FAILED to extract {exploit_id}")
    return actions


def main() -> int:
    from harden.audit.invariants import reconcile_extractor

    actions = reconcile(reconcile_extractor)
    for action in actions:
        print(action)
    print(f"reconcile: {len(actions)} change(s)")
    return 1 if any("MISSING" in a or "FAILED" in a for a in actions) else 0


if __name__ == "__main__":
    sys.exit(main())
