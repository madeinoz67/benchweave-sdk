"""Standalone capture writer: the three capture services on a filesystem backend.

Slice-1 scaffold (RED collection stub): the module lands before its first
behaviour commit so the capture-writer tests collect against a parent commit
that has no implementation yet. The implemented surface, landing in this
slice, is:

- ``capture_root`` — standalone capture-root resolution (explicit argument
  over ``BENCHWEAVE_CAPTURE_DIR`` over ``captures/`` under the working
  directory), refusing a root inside the installed package tree.
- ``_valid_capture_segment`` — the capture_id path-segment rules (ASCII
  allowlist, bounded length, no separators or traversal components, no
  Windows device-name prefixes), checked before any filesystem call.
- ``StandaloneCaptureWriter`` — the three capture methods of the eight-member
  ``CaptureServices`` protocol over one event directory per capture: staged
  chunk appends, an atomic (temp + rename) finalise whose manifest carries
  real per-artifact digest and length, and an abort scoped to staging plus
  the in-flight primary.
"""
