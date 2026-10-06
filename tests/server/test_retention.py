"""I3c: the retention engine — loader, evaluator, recorder, sweep, prune
(issue #285, AR-9 and AR-14).

The evaluator is deterministic and hand-computable, so the golden set here is
a SPEC: every row's age, bytes, surface and project is engineered so the
three rules' selections overlap (attribution exercised), the boundary cell
(a max_bytes rule whose applicable rows sum exactly to the cap) selects
nothing, both pinned captures survive everywhere, and an unparseable
``started_at`` keeps its capture (deletion needs positive evidence). The
rules document's every malformed shape refuses with the
``standalone_retention_rules_invalid:`` prefix (STD-4).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from benchweave_sdk_server.cli import cli as server_cli
from benchweave_sdk_server.library import CaptureLibrary
from benchweave_sdk_server.retention import (
    QuotaLatch,
    QuotaUsage,
    load_config,
    plan,
    record,
    sweep_plan,
)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

RULES_DOCUMENT = {
    "interval_s": 86400,
    "orphan_grace_s": 900,
    "reserve_bytes": 2_000_000_000,
    "rules": [
        {"id": "a-mcp-aging", "source": "mcp", "max_age_d": 30},
        {"id": "b-tunnel-keep-5", "project": "wind-tunnel", "max_count": 5},
        {"id": "c-global-cap", "max_bytes": 1500},
        {"id": "d-boundary", "project": "shelf-a", "max_bytes": 750},
    ],
}

#: The fixture corpus: (id, surface, project, age in days, bytes, pinned).
#: ``None`` age writes an unparseable ``started_at`` (the kept-by-default
#: row); ``None`` project omits the key (the wildcard side).
CORPUS: tuple[tuple[str, str | None, str | None, float | None, int, bool], ...] = (
    ("cap-alpha", "mcp", "wind-tunnel", 45, 100, False),
    ("cap-bravo", "mcp", None, 10, 200, False),
    ("cap-charlie", "mcp", None, 35, 150, False),
    ("cap-delta", "rest", "wind-tunnel", 5, 300, False),
    ("cap-echo", "rest", "wind-tunnel", 3, 250, False),
    ("cap-foxtrot", "ui", "wind-tunnel", 20, 180, False),
    ("cap-golf", "rest", "wind-tunnel", 60, 220, False),
    ("cap-hotel", "mcp", None, 2, 120, True),
    ("cap-india", "rest", "wind-tunnel", 50, 90, True),
    ("cap-juliet", "rest", "shelf-a", 7, 400, False),
    ("cap-kilo", "ui", "shelf-a", 6, 350, False),
    ("cap-lima", "rest", "wind-tunnel", 80, 80, False),
    ("cap-mangle", "rest", None, None, 50, False),
)

#: The hand-computed golden set (capture_id, rule_id, bytes), first
#: selecting rule in id-sorted evaluation order:
#: - a-mcp-aging (mcp, >30 d) selects alpha and charlie; hotel is pinned.
#: - b-tunnel-keep-5 (wind-tunnel, newest 5 of 6) selects lima.
#: - c-global-cap (1500 B) keeps echo+delta+kilo+juliet+bravo (== the cap
#:   at bravo) and selects foxtrot, charlie, alpha, golf, lima — alpha and
#:   charlie were already taken by a, lima by b.
#: - d-boundary (shelf-a, 750 B) sums juliet+kilo to exactly the cap and
#:   selects nothing (the boundary cell).
GOLDEN: tuple[tuple[str, str, int], ...] = (
    ("cap-alpha", "a-mcp-aging", 100),
    ("cap-charlie", "a-mcp-aging", 150),
    ("cap-foxtrot", "c-global-cap", 180),
    ("cap-golf", "c-global-cap", 220),
    ("cap-lima", "b-tunnel-keep-5", 80),
)

#: Everything the prune must leave standing (directories and index rows).
KEPT: frozenset[str] = frozenset(
    {
        "cap-bravo",
        "cap-delta",
        "cap-echo",
        "cap-hotel",
        "cap-india",
        "cap-juliet",
        "cap-kilo",
        "cap-mangle",
    }
)

_REMOVED: frozenset[str] = frozenset(row[0] for row in GOLDEN)


def _digest(capture_id: str) -> str:
    """A unique, honest-looking digest per capture id (the manifest's own
    recorded value — AR-9(c) checks the retention log against exactly it)."""
    return f"{abs(hash(capture_id)) % 16**64:064x}"


def _write_corpus(root: Path) -> dict[str, str]:
    """Publish every corpus row as a real event directory (manifest plus
    metadata — the files the library's rebuild reads); returns the digests."""
    digests: dict[str, str] = {}
    for capture_id, surface, project, age, byte_length, pinned in CORPUS:
        started_at = (
            (NOW - timedelta(days=age)).isoformat()
            if age is not None
            else "not-a-date"
        )
        digest = _digest(capture_id)
        digests[capture_id] = digest
        event = root / capture_id
        event.mkdir(parents=True)
        (event / "manifest.json").write_text(
            json.dumps(
                {
                    "capture_id": capture_id,
                    "started_at": started_at,
                    "format": "raw_binary",
                    "byte_length": byte_length,
                    "sha256": digest,
                }
            ),
            encoding="utf-8",
        )
        metadata: dict[str, Any] = {"surface": surface, "pinned": pinned}
        if project is not None:
            metadata["project"] = project
        (event / "metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
    return digests


def _rules_file(tmp_path: Path) -> Path:
    path = tmp_path / "retention-rules.json"
    path.write_text(json.dumps(RULES_DOCUMENT), encoding="utf-8")
    return path


def _rows(root: Path) -> list[dict[str, Any]]:
    library = CaptureLibrary(root)
    try:
        return library.list_captures()
    finally:
        library.close()


# --- the loader (STD-4: every malformed shape carries the prefix) ------------


def test_load_config_parses_the_full_document(tmp_path: Path) -> None:
    config = load_config(_rules_file(tmp_path))
    assert config.interval_s == 86400
    assert config.orphan_grace_s == 900
    assert config.reserve_bytes == 2_000_000_000
    assert [rule.id for rule in config.rules] == [
        "a-mcp-aging",
        "b-tunnel-keep-5",
        "c-global-cap",
        "d-boundary",
    ]


def test_load_config_defaults_when_keys_are_absent(tmp_path: Path) -> None:
    """Every top-level key optional; an empty rules list is a valid document
    (keep-everything — the Q13/F-3 posture the engine ships)."""
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"reserve_bytes": 100}), encoding="utf-8")
    config = load_config(path)
    assert config.rules == ()
    assert config.interval_s is None
    assert config.reserve_bytes == 100
    assert config.orphan_grace_s == 900.0


@pytest.mark.parametrize(
    "document",
    [
        "not an object",
        {"unknown_key": 1},
        {"interval_s": 0},
        {"interval_s": "86400"},
        {"orphan_grace_s": -1},
        {"reserve_bytes": "big"},
        {"rules": {"id": "x"}},
        {"rules": [{"id": "r"}]},  # no limit
        {"rules": [{"id": "r", "max_age_d": 30}, {"id": "r", "max_count": 1}]},
        {"rules": [{"id": "", "max_age_d": 30}]},
        {"rules": [{"id": "r", "source": "carrier-pigeon", "max_age_d": 30}]},
        {"rules": [{"id": "r", "project": 7, "max_age_d": 30}]},
        {"rules": [{"id": "r", "max_age_d": 0}]},
        {"rules": [{"id": "r", "max_age_d": -3}]},
        {"rules": [{"id": "r", "max_count": -1}]},
        {"rules": [{"id": "r", "max_count": 1.5}]},
        {"rules": [{"id": "r", "max_bytes": True}]},
        {"rules": [{"id": "r", "max_bytes": "1500"}]},
        {"rules": [{"id": "r", "max_age_d": 30, "unknown": 1}]},
    ],
)
def test_load_config_refuses_every_malformed_shape(
    tmp_path: Path, document: Any
) -> None:
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        load_config(path)
    assert str(caught.value).startswith("standalone_retention_rules_invalid:")


def test_load_config_refuses_mangled_json(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        load_config(path)
    assert str(caught.value).startswith("standalone_retention_rules_invalid:")


# --- the evaluator (AR-9a: the golden set, attribution included) -------------


def test_plan_matches_the_hand_computed_golden_set(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    _write_corpus(root)
    config = load_config(_rules_file(tmp_path))
    removals = plan(config.rules, _rows(root), now=NOW)
    assert [(m.capture_id, m.rule_id, m.bytes) for m in removals] == list(GOLDEN)


def test_plan_excludes_in_flight_captures(tmp_path: Path) -> None:
    """AR-9(e)'s RED control: an armed capture is never a removal candidate
    (the in-host schedule passes the live slot; a host holding the lock
    refuses the CLI prune outright, so the CLI path cannot see one). With
    golf armed, wind-tunnel drops to exactly five members — rule b keeps
    them all and selects nothing, so lima falls to rule c (the attribution
    recomputes over the eligible set, it does not subtract)."""
    root = tmp_path / "captures"
    _write_corpus(root)
    config = load_config(_rules_file(tmp_path))
    removals = plan(
        config.rules, _rows(root), now=NOW, in_flight_ids={"cap-golf"}
    )
    assert "cap-golf" not in {m.capture_id for m in removals}
    assert [(m.capture_id, m.rule_id, m.bytes) for m in removals] == [
        ("cap-alpha", "a-mcp-aging", 100),
        ("cap-charlie", "a-mcp-aging", 150),
        ("cap-foxtrot", "c-global-cap", 180),
        ("cap-lima", "c-global-cap", 80),
    ]


def test_a_poisoned_plan_including_the_in_flight_capture_is_not_the_plan(
    tmp_path: Path,
) -> None:
    """The control's other half: a plan that DID include the armed capture
    fails the golden comparison — the assertion the RED arm leans on."""
    root = tmp_path / "captures"
    _write_corpus(root)
    config = load_config(_rules_file(tmp_path))
    actual = plan(
        config.rules, _rows(root), now=NOW, in_flight_ids={"cap-golf"}
    )
    poisoned = list(GOLDEN)  # includes cap-golf
    assert [(m.capture_id, m.rule_id, m.bytes) for m in actual] != poisoned


def test_plan_with_no_rules_keeps_everything(tmp_path: Path) -> None:
    """The Q13/F-3 fork: no rules document, no removals — the engine is
    rule-driven and ships keep-everything."""
    root = tmp_path / "captures"
    _write_corpus(root)
    assert plan((), _rows(root), now=NOW) == []


def test_plan_is_deterministic_across_row_order(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    _write_corpus(root)
    config = load_config(_rules_file(tmp_path))
    rows = _rows(root)
    shuffled = list(reversed(rows))
    assert plan(config.rules, rows, now=NOW) == plan(
        config.rules, shuffled, now=NOW
    )


# --- the prune CLI (AR-9a/b/c/d end to end) -----------------------------------


def test_prune_dry_run_json_matches_the_golden_set(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    _write_corpus(root)
    result = CliRunner().invoke(
        server_cli,
        [
            "prune",
            "--capture-root",
            str(root),
            "--retention-rules",
            str(_rules_file(tmp_path)),
            "--dry-run",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["removals"] == [
        {"capture_id": capture_id, "rule": rule_id, "bytes": byte_length}
        for capture_id, rule_id, byte_length in GOLDEN
    ]
    assert payload["summary"] == {"count": 5, "bytes": 730}
    # A dry run touches nothing on disk.
    assert all((root / row[0]).is_dir() for row in GOLDEN)
    assert not (root / "retention.log").exists()


def test_prune_removes_exactly_the_plan_and_logs_every_removal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "captures"
    digests = _write_corpus(root)
    result = CliRunner().invoke(
        server_cli,
        [
            "prune",
            "--capture-root",
            str(root),
            "--retention-rules",
            str(_rules_file(tmp_path)),
        ],
    )
    assert result.exit_code == 0, result.output
    # (b) exactly the golden set: directories gone, index rows gone.
    assert not any((root / capture_id).exists() for capture_id in _REMOVED)
    assert all((root / capture_id).is_dir() for capture_id in KEPT)
    assert {row["capture_id"] for row in _rows(root)} == KEPT
    # (c) one retention.log row per removal, digest equal to the removed
    # manifest's own recorded value, rule and trigger intact.
    log_rows = [
        json.loads(line)
        for line in (root / "retention.log").read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [(row["capture_id"], row["rule"]) for row in log_rows] == [
        (capture_id, rule_id) for capture_id, rule_id, _ in GOLDEN
    ]
    assert all(row["trigger"] == "cli" for row in log_rows)
    assert all(row["sha256"] == digests[row["capture_id"]] for row in log_rows)
    # (d) pinned captures appear nowhere: hotel and india stand.
    assert (root / "cap-hotel").is_dir()
    assert (root / "cap-india").is_dir()


def test_prune_without_a_rules_document_only_sweeps(tmp_path: Path) -> None:
    """No document = keep-everything: the plan is empty and only the sweep
    can remove anything (an orphan-free root keeps every capture)."""
    root = tmp_path / "captures"
    _write_corpus(root)
    result = CliRunner().invoke(
        server_cli, ["prune", "--capture-root", str(root)]
    )
    assert result.exit_code == 0, result.output
    assert {row["capture_id"] for row in _rows(root)} == KEPT | _REMOVED


def test_prune_refuses_an_invalid_rules_document_with_exit_2(
    tmp_path: Path,
) -> None:
    root = tmp_path / "captures"
    _write_corpus(root)
    bad = tmp_path / "bad-rules.json"
    bad.write_text(json.dumps({"rules": [{"id": "r"}]}), encoding="utf-8")
    result = CliRunner().invoke(
        server_cli,
        ["prune", "--capture-root", str(root), "--retention-rules", str(bad)],
    )
    assert result.exit_code == 2
    assert "standalone_retention_rules_invalid:" in result.output
    # The refusal removed nothing.
    assert {row["capture_id"] for row in _rows(root)} == KEPT | _REMOVED


def test_prune_refuses_a_root_a_live_host_locks(tmp_path: Path) -> None:
    """The library's one-writer lock IS the prune-vs-host exclusion: while a
    library holds the root, the CLI prune surfaces the existing refusal and
    exits 2 (stop the host or use the in-host schedule)."""
    root = tmp_path / "captures"
    _write_corpus(root)
    holder = CaptureLibrary(root)
    try:
        result = CliRunner().invoke(
            server_cli, ["prune", "--capture-root", str(root)]
        )
        assert result.exit_code == 2
        assert "standalone_library_locked" in result.output
    finally:
        holder.close()


# --- the sweep (AR-14) ---------------------------------------------------------


def _sweep_root(tmp_path: Path) -> Path:
    root = tmp_path / "captures"
    _write_corpus(root)  # the published capture(s)
    old = root / "orphan-old"
    old.mkdir()
    (old / "staging").mkdir()
    stale = time.time() - 3600
    import os

    os.utime(old, (stale, stale))
    (root / "orphan-fresh").mkdir()
    return root


def test_sweep_plan_removes_exactly_the_aged_orphan(tmp_path: Path) -> None:
    root = _sweep_root(tmp_path)
    assert sweep_plan(root, now=time.time(), grace_s=900.0) == ["orphan-old"]


def test_sweep_never_touches_published_or_fresh_directories(
    tmp_path: Path,
) -> None:
    """AR-14's KILL arms, stated directly: a manifest-bearing directory is
    never sweepable (the published capture stands) and a fresh orphan is
    inside the grace window (a zombie still writing keeps its mtime fresh —
    the FOLD-8 residual's protection)."""
    root = _sweep_root(tmp_path)
    swept = sweep_plan(root, now=time.time(), grace_s=900.0)
    assert swept == ["orphan-old"]
    assert (root / "orphan-fresh").is_dir()
    assert (root / "cap-echo").is_dir()


def test_sweep_excludes_the_in_flight_directory(tmp_path: Path) -> None:
    """The armed capture's directory (no manifest yet) is not an orphan."""
    root = _sweep_root(tmp_path)
    in_flight = root / "orphan-armed"
    in_flight.mkdir()
    stale = time.time() - 3600
    import os

    os.utime(in_flight, (stale, stale))
    assert sweep_plan(
        root, now=time.time(), grace_s=900.0, in_flight_ids={"orphan-armed"}
    ) == ["orphan-old"]


def test_recorded_sweep_rows_carry_an_honest_null_digest(
    tmp_path: Path,
) -> None:
    root = _sweep_root(tmp_path)
    record(
        root,
        [{"capture_id": "orphan-old", "sha256": None, "rule": "orphan-sweep"}],
        trigger="sweep",
    )
    rows = [
        json.loads(line)
        for line in (root / "retention.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows == [
        {
            "capture_id": "orphan-old",
            "sha256": None,
            "rule": "orphan-sweep",
            "at": rows[0]["at"],
            "trigger": "sweep",
        }
    ]


def test_prune_also_runs_the_sweep(tmp_path: Path) -> None:
    """The prune's own sweep leg: the aged orphan goes (with its log row),
    the fresh orphan and every published capture stay."""
    root = _sweep_root(tmp_path)
    result = CliRunner().invoke(
        server_cli,
        [
            "prune",
            "--capture-root",
            str(root),
            "--retention-rules",
            str(_rules_file(tmp_path)),
        ],
    )
    assert result.exit_code == 0, result.output
    assert not (root / "orphan-old").exists()
    assert (root / "orphan-fresh").is_dir()
    log_rows = [
        json.loads(line)
        for line in (root / "retention.log").read_text(encoding="utf-8")
        .splitlines()
    ]
    sweep_rows = [row for row in log_rows if row["rule"] == "orphan-sweep"]
    assert sweep_rows == [
        {
            "capture_id": "orphan-old",
            "sha256": None,
            "rule": "orphan-sweep",
            "at": sweep_rows[0]["at"],
            "trigger": "sweep",
        }
    ]


# --- the quota latch (AR-9e: exactly-once on the rising edge) -----------------


def test_quota_latch_fires_once_per_rising_crossing() -> None:
    latch = QuotaLatch()
    at_cap = [QuotaUsage("c-global-cap", 1200, 1500)]  # exactly 0.8
    assert latch.crossings(at_cap) == at_cap  # 0.8 itself is a crossing
    assert latch.crossings(at_cap) == []  # already above: no second fire
    above = [QuotaUsage("c-global-cap", 1400, 1500)]
    assert latch.crossings(above) == []
    below = [QuotaUsage("c-global-cap", 1000, 1500)]  # drops under: re-arm
    assert latch.crossings(below) == []
    re_crossed = [QuotaUsage("c-global-cap", 1300, 1500)]
    assert latch.crossings(re_crossed) == re_crossed  # fires again


def test_quota_latch_is_per_rule() -> None:
    latch = QuotaLatch()
    usages = [QuotaUsage("rule-a", 900, 1000), QuotaUsage("rule-b", 100, 1000)]
    assert latch.crossings(usages) == [QuotaUsage("rule-a", 900, 1000)]


def test_quota_latch_zero_cap_is_above_only_with_bytes() -> None:
    """max_bytes 0 is a legal rule (select everything); its quota fraction
    is defined so only actual bytes above the cap read as a crossing."""
    latch = QuotaLatch()
    assert latch.crossings([QuotaUsage("zero-cap", 0, 0)]) == []
    assert latch.crossings([QuotaUsage("zero-cap", 1, 0)]) == [
        QuotaUsage("zero-cap", 1, 0)
    ]
