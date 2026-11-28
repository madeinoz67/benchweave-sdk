# ADR 0606 — Bind SDK dataset admission to the active host invoke

Status: Accepted

## Context
BenchWeave #606 covers standalone SDK dataset admission. The gateway repair landed in #609. In SDK main, seam.py:_op_invoke and _op_preset_apply serialize adapter execution per seam. session.py:execute calls its observer before adapter execution. seam.py:_invoke_core captures the mint for inline admission, while dataset_admission.py:_DatasetServicesView.dataset_publish still reads the caller context's dataset ID.

## Decision
Keep the mutex. Bind explicit publication to the host scope for the active invoke, using the operation ID, dataset ID, action ID and invoke input captured before adapter entry. Preserve record_dispatch as the source of per-operation correlation. The active scope establishes authority and lifetime. A historical record alone is insufficient. Keep the public publish signature. Treat context IDs as correlation checks. If either mismatches, or there is no matching active invoke for this controller, refuse before admitting or indexing the manifest. Close the active scope on success, error and cancellation. A task that inherited the scope must lose publishing authority when the invoke closes.

## Options and consequences
Use the existing per-seam mutex with dispatch-local binding. This changes admission without changing device scheduling. A shared last-dispatch slot would mix unrelated scopes. Widening public concurrency would change the device scheduling contract and has no requirement here. No new dependency or data migration is proposed.

## Verification and tasks
1. In seam.py and dataset_admission.py, bind the existing host dispatch record to the active invoke. Test same-seam serialization through public invoke and preset paths. Separately overlap two focused admission scopes behind test barriers and prove each sees only its own mint. Establish the pre-fix failure on the isolation assertion.
2. In dataset_admission.py, exercise the explicit publisher through the normal SDK invoke path. The unchanged context and matching host-minted ID succeed. A rewritten dataset ID, another operation's ID, an undispatched operation and a closed scope all refuse. Compare admission state before and after refusals. Keep inline publication and lookup callers compatible.
3. Update docs/internal/invariants.md to claim SDK admission identity binding for active host invokes only. Check the wording against the tests. The guarantee does not imply process isolation or a change to the gateway selection policy in #608.

## Rollback
Stop shipping the affected SDK candidate if either admission path regresses. Preserve the existing mutex, public publisher signature, manifest schema and gateway behaviour. No persisted data migration needs reversing.

## Approval
AC-2 split approved on Orca item 29. Design and public SDK ADR PR approved by Stephen Eaton on Orca item 29.
