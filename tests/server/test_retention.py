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
        {"rules": ["oops"]},
        {"rules": [42]},
        {"rules": [None]},
        {"rules": [True]},
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


# --- capture_delete + the recorder (SW-59, I3b ruling 9) ----------------------


def _publish_one(tmp_path: Path, *, count: int = 4) -> tuple[Any, str, str]:
    """Run one real capture to publication over the loopback fixture;
    returns (host, capture_id, the manifest's recorded digest)."""
    import asyncio

    from test_capture_lifecycle import _connected, _host, _start

    host = _host(tmp_path, mode="ok")

    async def scenario() -> tuple[str, str]:
        await _connected(host)
        started = await host.call("capture_start", _start(count=count))
        outcome = await host.await_capture()
        return str(started["capture_id"]), str(outcome["sha256"])

    capture_id, digest = asyncio.run(scenario())
    return host, capture_id, digest


def test_capture_delete_appends_its_recorder_row(tmp_path: Path) -> None:
    """Ruling 9's reuse: a manual delete never bypasses the log — after the
    directory and index row go, one retention.log row names the capture,
    the manifest's own recorded digest, rule manual-delete and the
    dispatch surface's trigger (delete-<surface>, defaulting rest)."""
    import asyncio

    host, capture_id, digest = _publish_one(tmp_path)

    async def scenario() -> None:
        await host.call(
            "capture_delete", {"capture_id": capture_id}, surface="ui"
        )

    asyncio.run(scenario())
    assert not (tmp_path / "captures" / capture_id).exists()
    rows = [
        json.loads(line)
        for line in (tmp_path / "captures" / "retention.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows == [
        {
            "capture_id": capture_id,
            "sha256": digest,
            "rule": "manual-delete",
            "at": rows[0]["at"],
            "trigger": "delete-ui",
        }
    ]


def test_capture_delete_trigger_defaults_to_rest(tmp_path: Path) -> None:
    """A dispatch with no surface (the internal/test path) records the
    closed set's default, rest — never a null trigger."""
    import asyncio

    host, capture_id, _digest = _publish_one(tmp_path)

    async def scenario() -> None:
        await host.call("capture_delete", {"capture_id": capture_id})

    asyncio.run(scenario())
    rows = [
        json.loads(line)
        for line in (tmp_path / "captures" / "retention.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows and rows[0]["trigger"] == "delete-rest"


# --- the in-host schedule (SW-57: run, event, quota, loop) --------------------


def _scheduled_host(tmp_path: Path) -> Any:
    """A capture-capable host over the golden corpus with the rules armed."""
    from test_capture_lifecycle import _host

    _write_corpus(tmp_path / "captures")
    config = load_config(_rules_file(tmp_path))
    return _host(tmp_path, mode="ok", retention=config)


def _kinds(host: Any, kind: str) -> list[dict[str, Any]]:
    import asyncio

    events = asyncio.run(host.call("events_get", {"after_id": 0}))["events"]
    return [event for event in events if event["kind"] == kind]


def test_scheduled_run_prunes_records_and_publishes_one_event(
    tmp_path: Path,
) -> None:
    """One scheduled evaluation: the golden set removed through the seam's
    own library, recorder rows trigger scheduled, and exactly ONE
    retention_pruned event (count, bytes, per-rule breakdown) on the bus."""
    host = _scheduled_host(tmp_path)
    payload = host.run_retention_once(now=NOW, clock=NOW.timestamp())
    assert payload == {
        "count": 5,
        "bytes": 730,
        "by_rule": {"a-mcp-aging": 2, "b-tunnel-keep-5": 1, "c-global-cap": 2},
    }
    pruned = _kinds(host, "retention_pruned")
    assert len(pruned) == 1
    assert pruned[0]["data"] == payload
    assert not any(
        (tmp_path / "captures" / row[0]).exists() for row in GOLDEN
    )
    log_rows = [
        json.loads(line)
        for line in (tmp_path / "captures" / "retention.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [(row["capture_id"], row["rule"]) for row in log_rows] == [
        (capture_id, rule_id) for capture_id, rule_id, _ in GOLDEN
    ]
    assert all(row["trigger"] == "scheduled" for row in log_rows)


def test_quota_events_fire_once_through_the_scheduler(tmp_path: Path) -> None:
    """The rising-edge latch through the live path: run one fires the two
    rules at or above 0.8 of their caps (the global cap sits exactly at its
    1500 B cap after pruning — the boundary posture; the shelf-a boundary
    rule at 750/750); the second, unchanged evaluation fires NOTHING (the
    latch holds; exactly-once per rising crossing)."""
    host = _scheduled_host(tmp_path)
    host.run_retention_once(now=NOW, clock=NOW.timestamp())
    first = _kinds(host, "retention_quota")
    assert {row["data"]["rule_id"] for row in first} == {
        "c-global-cap",
        "d-boundary",
    }
    global_row = next(
        row for row in first if row["data"]["rule_id"] == "c-global-cap"
    )
    assert global_row["data"] == {
        "rule_id": "c-global-cap",
        "used_bytes": 1500,
        "cap_bytes": 1500,
        "fraction": 1.0,
    }
    host.run_retention_once(now=NOW, clock=NOW.timestamp())
    assert _kinds(host, "retention_quota") == first  # nothing new fired


def test_scheduled_run_excludes_the_armed_capture(tmp_path: Path) -> None:
    """The seam-level AR-9(e) control: the armed capture is passed as
    in-flight — a capture mid-run is never a removal candidate."""
    host = _scheduled_host(tmp_path)
    host._capture = {"capture_id": "cap-golf"}
    payload = host.run_retention_once(now=NOW, clock=NOW.timestamp())
    removed = {
        capture_id
        for capture_id, _, _ in GOLDEN
        if not (tmp_path / "captures" / capture_id).exists()
    }
    assert "cap-golf" not in removed
    assert (tmp_path / "captures" / "cap-golf").is_dir()
    assert payload["count"] == 4
    host._capture = None


def test_the_scheduler_loop_evaluates_on_the_interval(tmp_path: Path) -> None:
    """The lifespan's task shape: sleep first, then evaluate every
    interval_s — a fast interval prunes and publishes without any caller
    but the loop itself, and cancellation stops it."""
    import asyncio

    from benchweave_sdk_server.retention import RetentionConfig, load_config

    _write_corpus(tmp_path / "captures")
    config = load_config(_rules_file(tmp_path))
    from test_capture_lifecycle import _host

    host = _host(
        tmp_path,
        mode="ok",
        retention=RetentionConfig(
            interval_s=0.05, rules=config.rules
        ),
    )

    async def scenario() -> bool:
        task = asyncio.create_task(host.retention_scheduler_loop())
        published = False
        for _ in range(100):  # up to ~5 s of polling
            await asyncio.sleep(0.05)
            if any(
                event["kind"] == "retention_pruned"
                for event in host.events.after(0)
            ):
                published = True
                break
        task.cancel()
        with contextlib_suppress():
            await task
        return published

    def contextlib_suppress():  # tiny local helper, no import shadowing
        import contextlib

        return contextlib.suppress(asyncio.CancelledError)

    assert asyncio.run(scenario())
    assert not any(
        (tmp_path / "captures" / row[0]).exists() for row in GOLDEN
    )


def test_the_lifespan_cancels_the_scheduler_and_releases_the_root(
    tmp_path: Path,
) -> None:
    """With rules armed and a fast interval, the app's lifespan starts the
    schedule and its exit cancels the task and releases the library lock —
    the close-down composes with the schedule live."""
    from fastapi.testclient import TestClient
    from test_capture_lifecycle import _host

    from benchweave_sdk_server.retention import RetentionConfig, load_config
    from benchweave_sdk_server.security import GuardPolicy, new_token
    from benchweave_sdk_server.web import build_app

    _write_corpus(tmp_path / "captures")
    config = load_config(_rules_file(tmp_path))
    host = _host(
        tmp_path,
        mode="ok",
        retention=RetentionConfig(interval_s=0.05, rules=config.rules),
    )
    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    app = build_app(host, policy=policy)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        assert client.get("/").status_code == 200
        import time as _time

        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline:
            if any(
                event["kind"] == "retention_pruned"
                for event in host.events.after(0)
            ):
                break
            _time.sleep(0.05)
    # Exit cancelled the scheduler and released the root lock.
    assert not (tmp_path / "captures" / "library.lock").exists()


# --- the next-effect projection (SW-49: the SAME evaluator, per capture) ------


def test_next_effects_label_every_corpus_row(tmp_path: Path) -> None:
    """The captures page's per-row projection over plan()'s own components:
    selected now -> prunable now by the first selecting rule; an applying
    age rule -> the computed date; an applying count/bytes rule -> eligible
    under the first such rule; pinned, in-flight, unparseable or unruled ->
    kept."""
    from benchweave_sdk_server.retention import next_effects

    root = tmp_path / "captures"
    _write_corpus(root)
    config = load_config(_rules_file(tmp_path))
    effects = next_effects(config.rules, _rows(root), now=NOW)
    assert effects["cap-alpha"]["label"] == "prunable now by a-mcp-aging"
    assert effects["cap-charlie"]["label"] == "prunable now by a-mcp-aging"
    assert effects["cap-lima"]["label"] == "prunable now by b-tunnel-keep-5"
    # bravo: mcp, 10 days old — the age rule applies and selects at day 40.
    assert effects["cap-bravo"]["label"] == (
        "a-mcp-aging at " + (NOW + timedelta(days=20)).date().isoformat()
    )
    # delta: wind-tunnel, inside the kept five — the count rule applies.
    assert effects["cap-delta"]["label"] == "eligible under b-tunnel-keep-5"
    # juliet: kept by the boundary rule; the first applying rule is the
    # global cap (id order c before d).
    assert effects["cap-juliet"]["label"] == "eligible under c-global-cap"
    assert effects["cap-hotel"]["label"] == "kept"  # pinned
    assert effects["cap-india"]["label"] == "kept"  # pinned
    assert effects["cap-mangle"]["label"] == "kept"  # unparseable started_at


def test_next_effects_keep_everything_without_rules(tmp_path: Path) -> None:
    from benchweave_sdk_server.retention import next_effects

    root = tmp_path / "captures"
    _write_corpus(root)
    effects = next_effects((), _rows(root), now=NOW)
    assert all(row["label"] == "kept" for row in effects.values())


def test_next_effects_keep_the_armed_capture(tmp_path: Path) -> None:
    from benchweave_sdk_server.retention import next_effects

    root = tmp_path / "captures"
    _write_corpus(root)
    config = load_config(_rules_file(tmp_path))
    effects = next_effects(
        config.rules, _rows(root), now=NOW, in_flight_ids={"cap-golf"}
    )
    assert effects["cap-golf"]["label"] == "kept"


# --- the captures page (SW-49) -------------------------------------------------

_DEVICE_ID = "fixture-bench-1"


def _write_corpus_device_aware(root: Path) -> None:
    """The corpus with a device id in every row's metadata (SW-49's device
    filter reads the file — the index has no device column)."""
    _write_corpus(root)
    for capture_id, _surface, _project, _age, _n, _pinned in CORPUS:
        metadata_path = root / capture_id / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["device"] = {"id": _DEVICE_ID}
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")


def _captures_app(tmp_path: Path, *, rules: bool = True):
    """A mock-transport host over the corpus with the app built on it."""
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk_server.seam import StandaloneSeam
    from benchweave_sdk_server.security import GuardPolicy, new_token
    from benchweave_sdk_server.session import load_plugin_project, mock_plugin_session
    from benchweave_sdk_server.web import build_app

    root = tmp_path / "captures"
    _write_corpus_device_aware(root)
    project_root = tmp_path / "proj"
    create_project(project_root, "pagecheck_plugin")
    loaded = load_plugin_project(project_root)
    retention = load_config(_rules_file(tmp_path)) if rules else None
    seam = StandaloneSeam(
        mock_plugin_session(loaded),
        transport_kind="mock",
        capture_root=root,
        retention=retention,
    )
    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
    )
    return seam, build_app(seam, policy=policy), policy


def test_captures_page_renders_rows_and_effects(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    _seam, app, _policy = _captures_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        response = client.get("/captures")
    assert response.status_code == 200
    body = response.text
    assert "cap-alpha" in body
    assert "prunable now by a-mcp-aging" in body
    assert "cap-hotel" in body  # pinned, still rendered
    assert "wind-tunnel" in body


def test_captures_page_filters(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    _seam, app, _policy = _captures_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        by_project = client.get("/captures", params={"project": "wind-tunnel"})
        by_source = client.get("/captures", params={"source": "mcp"})
        by_device = client.get("/captures", params={"device": _DEVICE_ID})
        by_device_miss = client.get("/captures", params={"device": "no-such"})
        by_query = client.get("/captures", params={"q": "cap-alpha"})
    body = by_project.text
    assert "cap-delta" in body and "cap-bravo" not in body
    body = by_source.text
    assert "cap-alpha" in body and "cap-delta" not in body
    assert "cap-delta" in by_device.text  # the device filter matches all
    assert "cap-alpha" not in by_device_miss.text
    assert "cap-alpha" in by_query.text and "cap-bravo" not in by_query.text


def test_delete_confirm_names_the_capture(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    _seam, app, _policy = _captures_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        response = client.get("/captures/cap-delta/delete")
        missing = client.get("/captures/cap-nothere/delete")
    assert response.status_code == 200
    body = response.text
    assert "cap-delta" in body
    assert "300" in body  # the size, named at confirmation (SW-59)
    assert "wind-tunnel" in body  # the project, named at confirmation
    assert missing.status_code == 404


def test_delete_post_dispatches_ui_and_records_delete_ui(tmp_path: Path) -> None:
    """AR-13's end-to-end pin: the HTML route's delete dispatches
    capture_delete with the UI surface — the recorder row's trigger is
    delete-ui (the dispatch layer's own identity, SW-34/ruling 9)."""
    from fastapi.testclient import TestClient

    _seam, app, policy = _captures_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        response = client.post(
            "/captures/cap-delta/delete",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/captures"
    assert not (tmp_path / "captures" / "cap-delta").exists()
    log_rows = [
        json.loads(line)
        for line in (tmp_path / "captures" / "retention.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["trigger"] for row in log_rows] == ["delete-ui"]
    assert log_rows[0]["rule"] == "manual-delete"
    assert log_rows[0]["capture_id"] == "cap-delta"


def test_pin_and_unpin_forms_round_trip(tmp_path: Path) -> None:
    import asyncio

    from fastapi.testclient import TestClient

    seam, app, policy = _captures_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        pinned = client.post(
            "/captures/cap-echo/pin",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        assert pinned.status_code == 303
        unpinned = client.post(
            "/captures/cap-echo/unpin",
            headers={"x-csrf-token": policy.csrf_token},
            follow_redirects=False,
        )
        assert unpinned.status_code == 303
    row = asyncio.run(seam.call("capture_get", {"capture_id": "cap-echo"}))
    assert row["metadata"]["pinned"] is False


# --- fold wave (refute lane 1): non-finite floats defeat the arithmetic ------


@pytest.mark.parametrize(
    "raw",
    [
        '{"interval_s": NaN}',
        '{"interval_s": 1e999}',
        '{"orphan_grace_s": NaN}',
        '{"orphan_grace_s": 1e999}',
        '{"rules": [{"id": "r", "max_age_d": NaN}]}',
        '{"rules": [{"id": "r", "max_age_d": 1e999}]}',
    ],
)
def test_load_config_refuses_non_finite_numbers(tmp_path: Path, raw: str) -> None:
    """F2 (row 1): a non-finite float is not a number the engine can
    compute with. NaN defeats the sweep grace (an uncomputable cutoff
    reads as 'everything is old'), inf/NaN detonate the age arithmetic
    bare, and a NaN interval kills the schedule task at its first sleep
    while an infinite one hangs it forever. Python's json accepts both as
    extensions, so they reach the loader today."""
    path = tmp_path / "rules.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        load_config(path)
    assert str(caught.value).startswith("standalone_retention_rules_invalid:")


def test_a_nan_grace_never_sweeps_the_fresh_orphan(tmp_path: Path) -> None:
    """The AR-14 kill condition, stated for the fold: an uncomputable
    grace proves nothing, so the sweep removes NOTHING (deletion needs
    positive evidence — the evaluator's own keep-by-default rule). A NaN
    cutoff currently reads every mtime as in-grace-eligible and sweeps
    the fresh orphan immediately."""
    root = _sweep_root(tmp_path)
    assert sweep_plan(root, now=time.time(), grace_s=float("nan")) == []
    assert (root / "orphan-fresh").is_dir()


def test_the_scheduler_survives_a_non_finite_interval(tmp_path: Path) -> None:
    """A NaN interval kills the schedule silently at its first sleep (the
    ValueError escapes the tick's suppress because it fires in sleep) and
    an infinite interval hangs it forever. A directly-constructed config
    must not be able to kill or hang the loop: the first tick survives."""
    import asyncio

    from test_capture_lifecycle import _host

    from benchweave_sdk_server.retention import RetentionConfig, load_config

    _write_corpus(tmp_path / "captures")
    config = load_config(_rules_file(tmp_path))
    host = _host(
        tmp_path,
        mode="ok",
        retention=RetentionConfig(
            interval_s=float("nan"), rules=config.rules
        ),
    )

    async def scenario() -> bool:
        task = asyncio.create_task(host.retention_scheduler_loop())
        await asyncio.sleep(0.2)  # past the loop's first sleep attempt
        alive = not task.done()
        task.cancel()
        with _suppress_cancel():
            await task
        return alive

    def _suppress_cancel():  # local helper, no import shadowing
        import contextlib

        return contextlib.suppress(asyncio.CancelledError)

    assert asyncio.run(scenario())


# --- fold wave (refute lane 1): a symlink must not dead the sweep -------------


def _sweep_root_with_link(tmp_path: Path) -> tuple[Path, Path]:
    """A sweep root with a real aged orphan AND a symlinked orphan (its
    target outside the root, aged) — the F3 lane's shape."""
    root = _sweep_root(tmp_path)
    target = tmp_path / "outside-target"
    target.mkdir()
    stale = time.time() - 3600
    import os

    os.utime(target, (stale, stale))
    link = root / "orphan-link"
    link.symlink_to(target)
    os.utime(link, (stale, stale))
    return root, link


def test_sweep_plan_skips_symlinked_entries(tmp_path: Path) -> None:
    """F3: the sweep never names a symlink — rmtree through a link raises
    OSError, and a raised sweep kills the whole run's report."""
    root, link = _sweep_root_with_link(tmp_path)
    assert sweep_plan(root, now=time.time(), grace_s=900.0) == ["orphan-old"]
    assert link.is_symlink()


def test_a_symlink_orphan_does_not_dead_the_sweep_run(tmp_path: Path) -> None:
    """The F3 lane's run shape: with a symlinked orphan in the root, the
    scheduled run COMPLETES — the real aged orphan goes with its log row,
    the symlink is left alone (never rmtree'd through), and the
    retention_pruned event fires. At 4d1afce the run raises OSError on
    the link, the event never fires, and the scheduler's tick suppress
    eats it forever — the crash-residue sweep silently dead."""

    from test_capture_lifecycle import _host

    root, link = _sweep_root_with_link(tmp_path)  # the corpus is already in
    config = load_config(_rules_file(tmp_path))
    host = _host(tmp_path, mode="ok", retention=config)

    payload = host.run_retention_once(now=NOW, clock=time.time())
    assert payload["count"] >= 1
    assert (payload["by_rule"].get("orphan-sweep") or 0) == 1
    assert not (root / "orphan-old").exists()
    assert link.is_symlink()
    assert link.exists()
    pruned = [
        event for event in host.events.after(0)
        if event["kind"] == "retention_pruned"
    ]
    assert len(pruned) == 1


def test_one_bad_sweep_entry_isolated_and_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Per-entry isolation: one entry whose removal fails (a raced link,
    a permission) cannot abort the run or the report — the entry is
    logged by name and the remaining entries still go."""
    import asyncio  # noqa: F401
    import logging as _logging

    from test_capture_lifecycle import _host

    root, link = _sweep_root_with_link(tmp_path)  # the corpus is already in
    config = load_config(_rules_file(tmp_path))
    host = _host(tmp_path, mode="ok", retention=config)

    import shutil as _shutil

    real_rmtree = _shutil.rmtree

    def failing_rmtree(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "orphan-old" in str(path):
            raise OSError("injected: removal refused")
        return real_rmtree(path, *args, **kwargs)

    import benchweave_sdk_server.seam as seam_module

    original = seam_module.shutil.rmtree
    seam_module.shutil.rmtree = failing_rmtree  # type: ignore[assignment]
    try:
        with caplog.at_level(_logging.WARNING):
            payload = host.run_retention_once(now=NOW, clock=time.time())
    finally:
        seam_module.shutil.rmtree = original  # type: ignore[assignment]
    assert payload["count"] >= 1
    assert any("orphan-old" in record.message for record in caplog.records)
    pruned = [
        event for event in host.events.after(0)
        if event["kind"] == "retention_pruned"
    ]
    assert len(pruned) == 1


# --- fold wave (refute lane 1): the log must survive a mid-run failure -------


class _BudgetedSink:
    """The probe's sink: a transactional writer whose calls must fit the
    remaining row budget whole (a large batch the sink cannot complete is
    refused with nothing landed — the disk-full model). Per-row appends
    land until the budget runs out."""

    def __init__(self, real: Any, budget: int) -> None:
        self._real = real
        self._budget = budget
        self.calls = 0

    def __call__(self, root: Path, removals: Any, *, trigger: str) -> None:
        self.calls += 1
        entries = list(removals)
        if len(entries) > self._budget:
            raise OSError("injected: the log write cannot complete this batch")
        self._real(root, entries, trigger=trigger)
        self._budget -= len(entries)
        if self._budget <= 0:
            raise OSError("injected: the log is full")


def test_a_mid_run_log_failure_keeps_prior_rows(tmp_path: Path) -> None:
    """F4 (row 4): the log is the artifact that survives index rebuilds,
    so it cannot be written once after ALL removals — a crash or a
    record failure in that window loses every row of the run
    unrecoverably. Each removal records its own row (window = one
    capture); a failure that lands mid-run keeps the prior removals'
    rows. At 4d1afce the run writes its whole plan in one call and the
    sink refuses it: zero rows for five deletions."""
    from test_capture_lifecycle import _host

    root = tmp_path / "captures"
    _write_corpus(root)
    config = load_config(_rules_file(tmp_path))
    host = _host(tmp_path, mode="ok", retention=config)
    sink = _BudgetedSink(record, budget=2)

    import benchweave_sdk_server.seam as seam_module

    original = seam_module.record
    seam_module.record = sink  # type: ignore[assignment]
    try:
        with pytest.raises(OSError):
            host.run_retention_once(now=NOW, clock=NOW.timestamp())
    finally:
        seam_module.record = original  # type: ignore[assignment]
    log_rows = (
        (root / "retention.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ) if (root / "retention.log").exists() else []
    rows = [json.loads(line) for line in log_rows]
    assert [row["capture_id"] for row in rows] == [
        capture_id for capture_id, _rule, _n in GOLDEN[:2]
    ]
    assert all(row["trigger"] == "scheduled" for row in rows)


def test_a_mid_run_log_failure_keeps_prior_rows_on_the_cli(
    tmp_path: Path,
) -> None:
    """The same window on the CLI prune path (the other batch site)."""
    root = tmp_path / "captures"
    _write_corpus(root)
    sink = _BudgetedSink(record, budget=2)

    import benchweave_sdk_server.retention as retention_module

    original = retention_module.record
    retention_module.record = sink  # type: ignore[assignment]
    try:
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
    finally:
        retention_module.record = original  # type: ignore[assignment]
    assert result.exit_code != 0  # the injected failure surfaces, not hides
    log_rows = (
        (root / "retention.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ) if (root / "retention.log").exists() else []
    rows = [json.loads(line) for line in log_rows]
    assert [row["capture_id"] for row in rows] == [
        capture_id for capture_id, _rule, _n in GOLDEN[:2]
    ]
    assert all(row["trigger"] == "cli" for row in rows)
