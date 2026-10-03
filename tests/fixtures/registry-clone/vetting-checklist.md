# Publisher vetting checklist — version 1

The versioned owner checklist for vetting publisher identities and their
namespace assignments (CR-15/CR-16/CR-39, issue #225 slice 3). A
`records/publishers.json` entry is not valid without a `vetting` block citing
rows of this checklist by id (`cited_rows`), naming who walked them
(`vetted_by`); the records-validity CI resolves every cited row against this
file — an unknown row refuses with `vetting_row_unknown:`.

Checklist id: `vetting-checklist` · version: `1` · rows: 6.

## Rows

| Row | Requirement | Source |
|-----|-------------|--------|
| V-01 | The publisher identity is one GitHub identity plus one publisher name (NFR-7); the namespace claimed equals the publisher id or is explicitly assigned to it, and the GitHub identity controls the namespace's repositories. | CR-15 |
| V-02 | The claimed namespace and plugin names clear the reserved lists (`lane-rules.json`: `benchweave`, `otdp`, `dev`, `stg`; reserved plugin names) — a reserved name or an extension of one refuses (`namespace_reserved:`). | CR-16 |
| V-03 | The claimed namespace is distinct from every existing vetted namespace under the committed similarity rule (skeleton-plus-edit-distance, confusable map, max edit distance 2 — the five committed `lane-rules.json` vectors are the rule's pin in this repo and in the SDK); a lookalike refuses at vetting (`namespace_lookalike:`) even though package-time only flags it for review. | CR-39 |
| V-04 | The publisher's repository protections (push protection, code scanning, advisories) are declared and recorded `declared-not-verified` (Q21) — the lane makes no enforcement claim over repositories it cannot read; the declarations name what the reviewer consulted, never what was proven. | Q21 |
| V-05 | The publisher's Ed25519 public key is recorded as a PEM with its validity window (`key_validity`); the registry never holds a private key, and signatures verify against exactly this recorded key. | CR-15 |
| V-06 | A transfer of a package to this publisher re-runs this checklist in full: the receiving publisher's vetting citation must be current at transfer time, both publishers' consents are recorded on the transfer record, and the coordinator actor is named. A transfer without a resolving receiver vetting reference refuses. | CR-17, Q9 |

## What this checklist does not establish

Structural validity never establishes trust. A `vetting` block that cites all
six rows proves the citation resolves, not that the vetting was sound — that
accountability stays with `vetted_by`. Declared-not-verified protections
(Q21) stay declared-not-verified no matter how often they are cited.
