"""The generality gate: device-generic and action-generic ``src/``, by
machine (issue #589, PR-1 — the standing directive made structural, design
record §0.3 rev 7).

The property under guard: the FTDI transport serves ANY FTDI-class device —
the selector comes from the operator, the binding store or the pinned
contract, never from a device identity constant in the source — and the
action surface is the descriptor's data, never ``src/`` vocabulary. This
gate fails closed on the literals that would break that property:

* **Device identity as a CLASS**: any hex literal ``0x[0-9a-fA-F]{1,8}`` in
  code under ``src/`` (one to eight digits, so a near-miss product id like
  ``0xdc49`` and a sub-4-digit value like ``0xfa3`` both redden, where a
  4-digit or value-range rule passed them) — excepted only inside the
  transport module's symbol-located ``PROVIDER_EXECUTORS`` registration
  block (the one sanctioned place a family's identity may live) and by the
  committed allowlist below, each entry carrying its reason. There is
  deliberately NO decimal rule: a decimal device id is indistinguishable
  from a timeout, buffer size or baud rate by shape, and listing the
  decimals one device happens to have is device-specificness wearing a
  generality rule's clothes — decimal identities are a named residual in
  the design record, backstopped behaviourally by the archetype matrix.
* **This device's own literals as a regression layer**, separate from the
  class rule and honestly narrower: the measurement corpus's OEM product
  id ``0xdc48`` (hex or decimal, by int value), its descriptor-carried
  serial ``53305982`` and the project name ``logicport`` (any case) — as
  int constants by value or string constants by substring, and the family
  vendor id ``0x0403`` by value outside the sanctioned block.
* **The plugin's action names in ALL quoted positions**: ``configure_fpga``,
  ``set_trigger``, ``set_trigger_position``, ``read_samples``, ``resync``
  and ``stop`` as quoted strings anywhere — dict key, comparison value or
  argument (the measured fact: ``src/`` contains ZERO quoted ``stop``
  today, so the rev 6 dict-key carve-out suppressed nothing while leaving
  ``if action_id == "stop":`` and ``.get("stop")`` invisible). Bare words
  (``stop_event``, ``capture_stop``, ``.stop()``) are unquoted identifiers
  no rule touches.

The vendored standards tree is excluded by LOCK MEMBERSHIP, not by
assertion: the excluded set is exactly the paths ``standards-lock.json``
records (275 files as of this commit, exactly one of them a ``.py`` —
``plugin-ui/contracts.py``, which a naive ``*.py`` glob does scan), and
the gate asserts ``lock_excluded_files`` equals the lock's own file count,
so a corpus sync that vendors another file moves an asserted number
instead of reddening a gate this repository cannot fix.

The honest residual, stated: the class rule catches hex LITERALS in code,
not computations — ``int("0403", 16)`` or a config default smuggles a
constant past it, and a DECIMAL device identity is likewise ungated. The
second layer is behavioural (the selector suite exercises distinct device
shapes through one code path); what this gate buys is that the trivial way
to be device-specific is also the loud way. Docstrings and comments are
not examined — they are documentation, and the user guide's printed
example selectors are the same class the guide itself prints.
"""

from __future__ import annotations

import ast
import io
import json
import re
import shutil
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO / "src"
LOCK_PATH = REPO / "standards-lock.json"
STANDARDS_REL = Path("benchweave_sdk") / "standards"
TRANSPORT_REL = "benchweave_sdk_server/ftdi.py"

#: The device identities the regression layer must keep out of ``src/`` —
#: the corpus's OEM pair and serial are device-specific by definition; the
#: vendor id is the ONE value the family registration may carry (compared
#: by int VALUE, so decimal and hex spellings are both caught).
_VENDOR_ID = 0x0403
_OEM_PID = 0xDC48
_SERIAL = 53305982
_DENYLIST_INTS = (_VENDOR_ID, _OEM_PID, _SERIAL)

#: The plugin's action vocabulary, banned as quoted strings in ANY
#: position (compared by exact casefolded value — a string constant equal
#: to an action name, whether it sits in a dict key, a comparison or an
#: argument).
_ACTION_NAMES = (
    "configure_fpga",
    "set_trigger",
    "set_trigger_position",
    "read_samples",
    "resync",
    "stop",
)

#: Substrings banned in string constants anywhere in ``src/`` (compared
#: casefolded) — this device's own identity spellings only.
_BANNED_SUBSTRINGS = (
    "0xdc48",
    "0403:dc48",
    "53305982",
    "logicport",
)

#: One hex literal in code: the class rule's detector (source spelling,
#: not int value — the value range (0xFF, 0xFFFF] was rev 6's rule and
#: passed both a 5-digit id and anything planted outside the transport
#: module).
_HEX_LITERAL = re.compile(r"\A0x[0-9a-fA-F]{1,8}\Z")

#: Explicit exemptions of the class rule, each with its reason. The length
#: is PINNED by the production arm, and the arm asserts every entry is
#: CONSUMED — an entry may only be added by editing this table and its
#: pinned count together, and an entry that matches nothing is dead
#: configuration the gate reports. The residual this shape accepts, named:
#: a device identity whose value happens to equal an allowlisted constant
#: in the same file passes this rule (the denylist and the behavioural
#: layer are the backstops).
_CLASS_ALLOWLIST: dict[tuple[str, int], str] = {
    ("benchweave_sdk_server/ftdi.py", 0xFF): (
        "the grammar-probe payload's set_bitmode mask — an FTDI wire "
        "constant, not a device identity"
    ),
    ("benchweave_sdk_server/ftdi.py", 0x40): (
        "the grammar-probe payload's set_bitmode mode — an FTDI wire "
        "opcode, not a device identity"
    ),
    ("benchweave_sdk/publishing.py", 0x01): "DER tag in the RFC 3161 timestamp-response parser",
    ("benchweave_sdk/publishing.py", 0x02): "DER tag in the RFC 3161 timestamp-response parser",
    ("benchweave_sdk/publishing.py", 0x04): "DER tag in the RFC 3161 timestamp-response parser",
    ("benchweave_sdk/publishing.py", 0x05): "DER tag in the RFC 3161 timestamp-response parser",
    ("benchweave_sdk/publishing.py", 0x06): "DER object-identifier tag in the timestamp parser",
    ("benchweave_sdk/publishing.py", 0x17): "DER UTCTime tag in the timestamp parser",
    ("benchweave_sdk/publishing.py", 0x18): "DER GeneralizedTime tag in the timestamp parser",
    ("benchweave_sdk/publishing.py", 0x30): "DER SEQUENCE tag in the timestamp parser",
    ("benchweave_sdk/publishing.py", 0x31): "DER SET tag in the timestamp parser",
    ("benchweave_sdk/publishing.py", 0x7F): "DER short-form length limit in the timestamp parser",
    ("benchweave_sdk/publishing.py", 0x80): "DER long-form length prefix in the timestamp parser",
    ("benchweave_sdk/publishing.py", 0xA0): "DER context tag in the timestamp parser",
    ("benchweave_sdk/presentation.py", 0x400): "Windows FILE_ATTRIBUTE reparse-point flag",
    ("benchweave_sdk/presentation.py", 0x20000000): "Windows reparse-name surrogate attribute",
    ("benchweave_sdk_server/library.py", 0x1000): "Win32 PROCESS_QUERY_LIMITED_INFORMATION flag",
    ("benchweave_sdk_server/lifecycle.py", 0x8): "Win32 DETACHED_PROCESS flag",
    ("benchweave_sdk_server/lifecycle.py", 0x200): "Win32 CREATE_NEW_PROCESS_GROUP flag",
    ("benchweave_sdk_server/lifecycle.py", 0x1000): "Win32 PROCESS_QUERY_LIMITED_INFORMATION flag",
}
#: The pinned count of class-rule literals the production scan exempts
#: through the allowlist (30 consumptions over the 20 table keys — several
#: DER tags recur at multiple sites in the parser). The pin makes a dead
#: allowlist entry and growth under an existing key both red: the number
#: only moves in a commit that names why.
_EXPECTED_ALLOWLISTED_LITERALS = 30

#: The pinned count of class-rule literals exempt by the PROVIDER_EXECUTORS
#: block rule (the ftdi family's vendor id registration — growth inside
#: the sanctioned block is a red test, not a quieter exemption).
_EXPECTED_BLOCK_EXEMPTIONS = 1

#: The pinned denominators of the production scan (design record §0.3:
#: "asserts each against its committed value" — any source edit that moves
#: one of these moves the gate with it, deliberately). The lock's file
#: count is NOT pinned here: it is asserted against the lock's own
#: recorded entries at runtime, so a corpus sync moves the number without
#: reddening a gate this repository cannot fix (275 as of this commit).
_EXPECTED_FILES_SCANNED = 50
_EXPECTED_LITERALS_EXAMINED = 17487


@dataclass(frozen=True)
class Finding:
    rel: str
    lineno: int
    rule: str
    detail: str


@dataclass
class Scan:
    files_scanned: int = 0
    literals_examined: int = 0
    block_exemptions: int = 0
    allowlisted_entries: int = 0
    lock_excluded_files: int = 0
    findings: list[Finding] = field(default_factory=list)

    def report(self) -> str:
        return (
            f"generality gate: files_scanned={self.files_scanned} "
            f"literals_examined={self.literals_examined} "
            f"block_exemptions={self.block_exemptions} "
            f"allowlisted_entries={self.allowlisted_entries} "
            f"lock_excluded_files={self.lock_excluded_files} "
            f"findings={len(self.findings)}"
        )


def _lock_relative_paths() -> list[Path]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return [
        Path(entry["path"])
        for row in lock["standards"]
        for entry in row.get("files", [])
    ]


def _docstring_ids(tree: ast.Module) -> set[int]:
    """The ``id()`` of every docstring constant node in the tree."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _executor_block_span(tree: ast.Module) -> tuple[int, int] | None:
    """The PROVIDER_EXECUTORS registration span, located by SYMBOL (never
    by line number) — the sanctioned home of a family's identity."""
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "PROVIDER_EXECUTORS":
                assert node.end_lineno is not None
                return (node.lineno, node.end_lineno)
    return None


def _scan(root: Path) -> Scan:
    scan = Scan()
    lock_paths = _lock_relative_paths()
    lock_root = root / STANDARDS_REL
    excluded = [lock_root / rel for rel in lock_paths]
    scan.lock_excluded_files = sum(1 for path in excluded if path.is_file())
    excluded_set = set(excluded)
    for path in sorted(root.rglob("*.py")):
        if path in excluded_set:
            continue  # lock membership, not assertion (STD-5: vendored
            # bytes are main-side's to fix, never edited here)
        rel = str(path.relative_to(root))
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        docstrings = _docstring_ids(tree)
        block: tuple[int, int] | None = None
        if rel == TRANSPORT_REL:
            block = _executor_block_span(tree)
        scan.files_scanned += 1
        # The class rule: hex-literal SPELLINGS in code (tokenize sees the
        # exact source token; strings and comments are different token
        # kinds and are not examined here).
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.NUMBER and _HEX_LITERAL.match(tok.string):
                value = int(tok.string, 16)
                lineno = tok.start[0]
                in_block = (
                    block is not None
                    and block[0] <= lineno <= block[1]
                    and rel == TRANSPORT_REL
                )
                if in_block:
                    scan.block_exemptions += 1
                    continue
                if (rel, value) in _CLASS_ALLOWLIST:
                    scan.allowlisted_entries += 1
                    continue
                scan.findings.append(
                    Finding(
                        rel,
                        lineno,
                        "device-identity-class",
                        f"hex literal {tok.string} in code (the class rule "
                        "admits no device identity outside the registration "
                        "block and the committed allowlist)",
                    )
                )
        # The string/int constant pass: the denylist by value, the banned
        # substrings, and the action names by exact quoted value in ANY
        # position.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or id(node) in docstrings:
                continue
            scan.literals_examined += 1
            value = node.value
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                if value in _DENYLIST_INTS and not (
                    value == _VENDOR_ID
                    and rel == TRANSPORT_REL
                    and block is not None
                    and block[0] <= node.lineno <= block[1]
                ):
                    scan.findings.append(
                        Finding(
                            rel,
                            node.lineno,
                            "device-identity",
                            f"int literal {value} (0x{value:04x} in hex form) "
                            "— this device's own identity, denylisted by value",
                        )
                    )
            elif isinstance(value, str):
                folded = value.casefold()
                for needle in _BANNED_SUBSTRINGS:
                    if needle in folded:
                        scan.findings.append(
                            Finding(rel, node.lineno, "device-or-action-name", repr(needle))
                        )
                if folded in _ACTION_NAMES:
                    scan.findings.append(
                        Finding(
                            rel,
                            node.lineno,
                            "action-name",
                            f"{value!r} is a plugin action name quoted in src/ "
                            "(all quoted positions — key, comparison, argument)",
                        )
                    )
    return scan


def _scratch_copy(tmp_path: Path) -> Path:
    scratch = tmp_path / "src"
    shutil.copytree(SRC_ROOT, scratch)
    return scratch


def _plant(scratch: Path, rel: str, trailer: str) -> None:
    planted = scratch / rel
    planted.write_text(
        planted.read_text(encoding="utf-8") + trailer, encoding="utf-8"
    )


class TestTheGateHoldsOnRealSource:
    def test_zero_findings_and_the_pinned_denominators(self, capsys) -> None:
        scan = _scan(SRC_ROOT)
        print(scan.report())
        for finding in scan.findings:
            print(f"  {finding.rel}:{finding.lineno} {finding.rule}: {finding.detail}")
        assert scan.findings == []
        assert scan.files_scanned == _EXPECTED_FILES_SCANNED
        assert scan.literals_examined == _EXPECTED_LITERALS_EXAMINED
        assert scan.block_exemptions == _EXPECTED_BLOCK_EXEMPTIONS
        assert scan.allowlisted_entries == _EXPECTED_ALLOWLISTED_LITERALS

    def test_the_lock_exclusion_is_lock_derived_and_counted(self) -> None:
        """The vendored tree is excluded by LOCK MEMBERSHIP: the excluded
        count equals the lock's own file count (a sync that vendors another
        file moves the number with the lock instead of reddening here),
        and the excluded set really is on disk under the standards root —
        a lock entry with no file (or one escaped the root) is drift this
        catches."""
        scan = _scan(SRC_ROOT)
        lock_count = len(_lock_relative_paths())
        assert scan.lock_excluded_files == lock_count
        assert lock_count > 0
        # Exactly one lock-recorded file is a .py (the record's measured
        # fact — a second one arriving by sync moves this pin, which is
        # the disclosed cost of the assertion).
        py_in_lock = [p for p in _lock_relative_paths() if p.suffix == ".py"]
        assert [str(p) for p in py_in_lock] == ["plugin-ui/contracts.py"]

    def test_the_transport_block_locates_by_symbol(self) -> None:
        """The exemption exists only because PROVIDER_EXECUTORS is found in
        the real transport module by symbol — the sanctioned registration
        the family's vendor id lives in."""
        tree = ast.parse(
            (SRC_ROOT / TRANSPORT_REL).read_text(encoding="utf-8"),
            filename=TRANSPORT_REL,
        )
        assert _executor_block_span(tree) is not None


class TestTheGateBites:
    """Planted violations on a scratch copy — each rule's detector, proven
    on every run so a broken regex cannot pass silently. The rev 7 holes
    are the load-bearing rows: a comparison-position ``stop``, a near-miss
    product id and a sub-4-digit id planted OUTSIDE the transport module,
    all of which the rev 6 rules passed."""

    def test_a_vendor_id_outside_the_block_fails(self, tmp_path: Path) -> None:
        scratch = _scratch_copy(tmp_path)
        _plant(scratch, TRANSPORT_REL, "\n_LEAK = 0x0403\n")
        scan = _scan(scratch)
        assert any(
            f.rule == "device-identity-class" and f.lineno for f in scan.findings
        )

    def test_the_oem_pid_fails_in_hex_and_decimal_anywhere(self, tmp_path: Path) -> None:
        scratch = _scratch_copy(tmp_path)
        _plant(
            scratch,
            "benchweave_sdk_server/session.py",
            "\n_LEAK_HEX = 0xDC48\n_LEAK_DEC = 56392\n",
        )
        scan = _scan(scratch)
        leaked = [f.detail for f in scan.findings if f.rule == "device-identity"]
        assert any("0xdc48" in d for d in leaked)
        assert any("56392" in d for d in leaked)

    def test_the_serial_and_the_project_name_fail_as_strings(self, tmp_path: Path) -> None:
        scratch = _scratch_copy(tmp_path)
        _plant(
            scratch,
            "benchweave_sdk_server/serial.py",
            '\n_LEAK = "device 53305982 of the LogicPort bench"\n',
        )
        scan = _scan(scratch)
        details = [f.detail for f in scan.findings if f.rule == "device-or-action-name"]
        assert any("53305982" in d for d in details)
        assert any("logicport" in d for d in details)

    def test_an_action_name_string_fails(self, tmp_path: Path) -> None:
        scratch = _scratch_copy(tmp_path)
        _plant(scratch, "benchweave_sdk_server/seam.py", '\n_LEAK = "configure_fpga"\n')
        scan = _scan(scratch)
        assert any(
            f.rule == "action-name" and "configure_fpga" in f.detail
            for f in scan.findings
        )

    def test_a_quoted_stop_fails_in_every_position_while_bare_words_do_not(
        self, tmp_path: Path
    ) -> None:
        """Rev 7's widening: the dict-key-only rule left ``if action_id ==
        "stop":`` and ``.get("stop")`` invisible while suppressing nothing
        (measured: zero quoted ``stop`` in ``src/``). All three quoted
        positions redden; the bare identifiers beside them do not."""
        scratch = _scratch_copy(tmp_path)
        _plant(
            scratch,
            "benchweave_sdk_server/seam.py",
            '\nstop_event = capture_stop = 0\n'
            '_LEAK_KEY = {"stop": 1}\n'
            '_LEAK_CMP = action_id == "stop"\n'
            '_LEAK_ARG = row.get("stop")\n',
        )
        scan = _scan(scratch)
        stop_rows = [
            f for f in scan.findings if f.rule == "action-name" and "stop" in f.detail
        ]
        assert len(stop_rows) == 3, [f.detail for f in scan.findings]

    def test_a_near_miss_pid_fails_outside_the_transport_module(self, tmp_path: Path) -> None:
        """``0xdc49`` — one hex digit off the corpus device's pid, four
        digits — passed rev 6's transport-only value-range rule; the class
        rule reddens on the spelling wherever it lives."""
        scratch = _scratch_copy(tmp_path)
        _plant(scratch, "benchweave_sdk_server/session.py", "\n_LEAK = 0xdc49\n")
        scan = _scan(scratch)
        assert any(f.rule == "device-identity-class" for f in scan.findings)

    def test_a_sub_four_digit_id_fails_outside_the_transport_module(self, tmp_path: Path) -> None:
        """``0xfa3`` — a sub-4-digit value — also passed rev 6's rules
        outside the transport module; the class rule's {1,8} digits
        redden on it."""
        scratch = _scratch_copy(tmp_path)
        _plant(scratch, "benchweave_sdk_server/seam.py", "\n_LEAK = 0xfa3\n")
        scan = _scan(scratch)
        assert any(f.rule == "device-identity-class" for f in scan.findings)

    def test_a_five_digit_id_fails_even_in_the_transport_module(self, tmp_path: Path) -> None:
        """A 5-digit hex id sits above 0xFFFF, outside rev 6's value-range
        cut even inside the transport module; the class rule has no value
        cut."""
        scratch = _scratch_copy(tmp_path)
        _plant(scratch, TRANSPORT_REL, "\n_LEAK = 0x1abcd\n")
        scan = _scan(scratch)
        assert any(f.rule == "device-identity-class" for f in scan.findings)

    def test_the_lock_exclusion_really_excludes_the_vendored_tree(
        self, tmp_path: Path
    ) -> None:
        """The one lock-recorded ``.py`` is excluded by lock membership:
        a hex literal planted in it does not redden THIS gate (vendored
        bytes are the main repository's to fix — never edited, never
        linted into shape here)."""
        scratch = _scratch_copy(tmp_path)
        vendored = str(STANDARDS_REL / "plugin-ui" / "contracts.py")
        _plant(scratch, vendored, "\n_LEAK = 0x9999\n")
        scan = _scan(scratch)
        assert not any(
            f.rule == "device-identity-class" and f.rel == vendored
            for f in scan.findings
        )
        assert scan.lock_excluded_files == len(_lock_relative_paths())

    def test_a_clean_copy_passes_with_the_same_denominators(self, tmp_path: Path) -> None:
        scratch = _scratch_copy(tmp_path)
        scan = _scan(scratch)
        assert scan.findings == []
        assert scan.block_exemptions == _EXPECTED_BLOCK_EXEMPTIONS
        assert scan.allowlisted_entries == _EXPECTED_ALLOWLISTED_LITERALS
        real = _scan(SRC_ROOT)
        assert scan.files_scanned == real.files_scanned
        assert scan.literals_examined == real.literals_examined
