# Pre-submission audit

**84 checks, 0 failures.** Every one of them is executed by
[`tools/audit.sh`](../tools/audit.sh) — nothing here is asserted from memory, and
the script is in the repo so the numbers can be reproduced rather than believed:

```bash
bash tools/audit.sh                                            # offline checks
bash tools/audit.sh <oracle> <consumer>                        # + the live deployment
bash tools/audit.sh <oracle> <consumer> exercised              # + the demo-state checks
```

The third argument is opt-in on purpose. The last two checks assert state that
only exists once somebody has *driven* a deployment — refusals recorded, and
`freeze()` called — and a correct fresh deployment has neither. Asserting them
unconditionally would fail an honest contract, which is the same class of
mistake as a test that cannot fail. What holds on **any** deployment is that its
source is byte-identical to the artifact, and that is now checked for the
consumer as well as the oracle.

It exits with the number of failures, so it works as a CI gate.

Run: 2026-09-06, after the review fixes. **84/84 Studionet, 82/82 Bradbury** —

    bash tools/audit.sh 0x1F3f51d9927490543519d6C61b9B544bf5caA7FB 0x96Db4DBE72892b788E311e33cEA8807d921ca960 exercised   # Studionet
    bash tools/audit.sh 0x4f35Fd3D93bDb8446C3ccf715B684222D93BB8fE 0xcDEAD088A846309a7F3c39477101b90772940D25            # Bradbury

Bradbury runs 82 because the two demo-state checks are not requested: that
deployment is verified read-only — source identity, wiring, and the full
decision path through `gate_build` — and was deliberately not written to or
frozen, since `freeze()` is one-way.

Group 3b is new and exists because of the review. Both findings are now checked
mechanically rather than eyeballed, over the source **and** the deployed
artifact, and one of the checks runs the new tests against the *pre-fix*
contract and fails if they pass — a regression test nobody has watched fail is
not a regression test.

> There was no committed checklist from the earlier projects to copy — the
> "item 24" that caught a `Co-Authored-By` trailer during TokenScope lived in a
> conversation, not a file. This list is reconstructed from the failure modes
> those projects actually hit, and is committed this time so the next project
> inherits it.

---

## What the script checks

| group | checks | covers |
|---|---|---|
| 1. lint | 5 | GenVM linter on both sources, the probe, **and both minified artifacts** |
| 2. runner pin | 7 | pin is line 1 of every file, and the artifact's pin is byte-identical to its source's — a comment above line 1 makes a contract undeployable and the only error reported is `invalid_contract` |
| 3. offline suite | 4 | 389 tests pass with **0 failures and 0 skips**; the suite is ≥380; the stub raises on any network or model access; fixtures are regenerable |
| 3b. review findings | 9 | every `@gl.public.write` in the consumer carries the frozen guard (source **and** artifact); `remove_dependency` specifically; a refusal is returned rather than raised; **no storage write in either contract has a reachable `raise` after it**; and the new tests are confirmed to fail against the pre-fix contract |
| 4. artifacts current | 5 | rebuilding from source reproduces both artifacts **byte for byte**; both sha256s appear in `deployments.json`; the json parses |
| 5. repo hygiene | 10 | **no AI attribution in any commit**; no secret-looking tracked files; `.gitignore` covers `CLAUDE.md`, `.claude/`, `.accounts.json`; no `__pycache__`; all four docs present |
| 6. README honesty | 3 | the byte counts, the sha256 and the test count in the README are **re-measured against the files**, not trusted |
| 7. method surface | 28 | every method the README documents exists in the contract |
| 8. live deployment | 11 | **both** deployed sources byte-identical to their artifacts; fee 0; `verify_risk` returns true; `require_safe` reverts; `is_safe` is false when unscanned; consumer reads the oracle cross-contract; `preview_dependency` degrades; `gate_build` fails a mixed list; `oracle_error` separates a refusal from an unreachable oracle |
| 9. demo state (opt-in) | 2 | on a deployment that has been driven: **`blocked_attempts` is non-zero on chain** — rev1 would report 0, the increment having been rolled back — and the contract is **frozen with its manifest intact** after a refused removal, which rev1 would have let through |

The checks worth naming individually, because each one is a mistake a previous
project made:

- **`no AI attribution anywhere in commit messages`** — TokenScope shipped a
  `Co-Authored-By` trailer, which GitHub renders as a repo *contributor*. It had
  to be removed with `git filter-branch` and a force-push of an already-public
  repo. This check is `git log --format='%B' | grep -qiE 'co-authored-by|claude|
  generated with'`, inverted.
- **`build/*.min.py is a current build of its source`** — an artifact that has
  drifted from its source makes every other claim in the repo meaningless. The
  check rebuilds into `/tmp` and diffs.
- **`deployed source is byte-identical to build/PackageGuard.min.py`** — `genlayer
  code <address>` piped through `diff`. This is the only check that proves the
  address in the README is running the code in the repo.
- **`README artifact byte counts / sha256 / test count match`** — the README is
  the document most likely to drift, because it is written last and edited most.
- **`suite touches no network`** — the offline harness installs a `genlayer` stub
  whose `web.request` and `exec_prompt` raise. A test that silently reached the
  network would pass for the wrong reason.

One check found a real discrepancy on its first run: the README byte count was
written `43,633` and the check compared against `43633`. The number was right and
the *check* was wrong, so the check was fixed to strip separators — noted here
because "the audit found nothing" is a claim worth being able to distinguish from
"the audit was too weak to find anything".

---

## Limitations, stated rather than hidden

- **`request_scan` is rate limited to one per wallet per 300 seconds.** Scanning
  seven packages takes ~35 minutes of wall clock. `tools/e2e_studionet.sh` paces
  itself and **reports which packages were rejected** rather than continuing
  silently — the first run of it lost `left-pad` to a rate-limit collision with a
  manual scan, and said so. `request_scan` returning "write executed" does not
  mean "scored": it never raises once value is attached, so a refusal comes back
  as a `REJECTED` object with the fee credited.
- **The fee path cannot be exercised from the CLI.** `genlayer write` hardcodes
  `value: 0n`, so a payable method always sees `gl.message.value == 0`. The fee,
  refund and overpayment logic is covered offline, and the demo deployments run
  at fee 0 so `request_scan` is callable at all.
- **A reverting `view` shows only "execution failed" from the CLI.** The
  `UserError` message is not surfaced on a read. `require_safe` demonstrably
  reverts; the reason text is visible through
  `PackageConsumer.add_dependency`, which is a write — that is where the
  `carries banned flag(s) INSTALL_SCRIPTS…` message in the README comes from.
- **Mixed-case package names are separate feeds.** `JSONStream` and `jsonstream`
  are two different live packages (PROBE.md §8), so the name is never
  case-folded. A caller who types the wrong case gets a different package —
  exactly as `npm install` would.
- **The model can move a risk level at a threshold.** Its influence is 3 raw
  points of 100; quantizing to a step of 5 means a package sitting within one
  rung of a boundary can cross it. That is a property of quantizing at all, not
  of the model. The test asserts the movement is never more than one rung and
  never skips a level, and the live evidence is in the README: express scanned
  twice moved `desc` 1→2 and `overall` not at all.
- **The Bradbury CLI does not surface a revert's `UserError` text.** This used
  to matter on the `add_dependency` path and no longer does: after the review
  fixes a policy refusal is a RETURN value, not a revert, so both CLIs show the
  reason. It still applies to the paths that genuinely raise — a frozen
  contract, a malformed package name, an unreachable oracle — where the gate is
  evidenced by its effect instead: `has_dependency` is false, the manifest is
  unchanged, and `blocked_attempts` did not move.
- **Scores are point-in-time.** A package's vector moves as npm moves; the
  contract keeps 12 scans per package and `PackageConsumer` enforces a
  `max_age_seconds` policy (default 7 days) so a stale score cannot pass a gate.

---

## Full output

```
== 1. contracts and artifacts lint ==
  PASS  genvm-lint contracts/PackageGuard.py
  PASS  genvm-lint contracts/PackageConsumer.py
  PASS  genvm-lint contracts/_render_probe.py
  PASS  genvm-lint build/PackageGuard.min.py
  PASS  genvm-lint build/PackageConsumer.min.py
== 2. runner pin ==
  PASS  runner pin is line 1 of contracts/PackageGuard.py
  PASS  runner pin is line 1 of contracts/PackageConsumer.py
  PASS  runner pin is line 1 of contracts/_render_probe.py
  PASS  runner pin is line 1 of build/PackageGuard.min.py
  PASS  runner pin is line 1 of build/PackageConsumer.min.py
  PASS  artifact pin matches source pin (oracle)
  PASS  artifact pin matches source pin (consumer)
== 3. offline suite ==
  PASS  python3 test/test_logic.py passes with 0 failures and 0 skips
  PASS  suite is >= 380 tests
  PASS  suite touches no network (stub raises on web/model access)
  PASS  fixtures are regenerable from the live registry
== 3b. the two review findings, checked in the source ==
  PASS  every @gl.public.write in contracts/PackageConsumer.py checks frozen
  PASS  every @gl.public.write in build/PackageConsumer.min.py checks frozen
  PASS  remove_dependency refuses when frozen (finding 1)
  PASS  add_dependency returns a refusal instead of reverting (finding 2)
  PASS  no storage write is followed by a reachable raise in contracts/PackageGuard.py
  PASS  no storage write is followed by a reachable raise in contracts/PackageConsumer.py
  PASS  no storage write is followed by a reachable raise in build/PackageGuard.min.py
  PASS  no storage write is followed by a reachable raise in build/PackageConsumer.min.py
  PASS  the new tests fail against the pre-fix contract (f0e2167)
== 4. artifacts are current ==
  PASS  build/PackageGuard.min.py is a current build of its source
  PASS  build/PackageConsumer.min.py is a current build of its source
  PASS  deployments.json sha256 matches build/PackageGuard.min.py
  PASS  deployments.json sha256 matches build/PackageConsumer.min.py
  PASS  deployments.json is valid json
== 5. repository hygiene ==
  PASS  no AI attribution anywhere in commit messages
  PASS  no secret-looking files tracked
  PASS  .gitignore excludes CLAUDE.md
  PASS  .gitignore excludes .claude/
  PASS  .gitignore excludes .accounts.json
  PASS  no __pycache__ tracked
  PASS  README exists and is substantial
  PASS  docs/PROBE.md exists
  PASS  docs/DESIGN.md exists
  PASS  docs/AUDIT.md exists
== 6. claims in the README match measured values ==
  PASS  README artifact byte counts match the files
  PASS  README sha256 matches the artifact
  PASS  README test count matches the suite
== 7. every documented method exists ==
  PASS  PackageGuard.request_scan
  PASS  PackageGuard.set_fee
  PASS  PackageGuard.get_risk
  PASS  PackageGuard.get_risk_by_id
  PASS  PackageGuard.get_risk_history
  PASS  PackageGuard.is_safe
  PASS  PackageGuard.require_safe
  PASS  PackageGuard.get_top_packages
  PASS  PackageGuard.get_riskiest
  PASS  PackageGuard.verify_risk
  PASS  PackageGuard.get_stats
  PASS  PackageGuard.get_config
  PASS  PackageGuard.claim_refund
  PASS  PackageGuard.set_paused
  PASS  PackageGuard.transfer_ownership
  PASS  PackageGuard.withdraw
  PASS  PackageConsumer.add_dependency
  PASS  PackageConsumer.remove_dependency
  PASS  PackageConsumer.check_risk
  PASS  PackageConsumer.preview_dependency
  PASS  PackageConsumer.gate_build
  PASS  PackageConsumer.get_manifest
  PASS  PackageConsumer.get_policy
  PASS  PackageConsumer.set_policy
  PASS  PackageConsumer.freeze
  PASS  PackageConsumer.transfer_ownership
  PASS  PackageConsumer.set_oracle
  PASS  PackageConsumer._require_unfrozen
== 8. live deployment ==
  PASS  deployed source is byte-identical to build/PackageGuard.min.py
  PASS  fee is 0 on the demo deployment
  PASS  get_stats reports scanned packages
  PASS  verify_risk(1) returns verified: true
  PASS  require_safe reverts below the bar
  PASS  is_safe on an unscanned package is false
  PASS  deployed consumer source is byte-identical to build/PackageConsumer.min.py
  PASS  consumer reads the oracle cross-contract
  PASS  preview_dependency degrades instead of reverting
  PASS  gate_build fails a mixed dependency list
  PASS  preview separates a refusal from an unreachable oracle
== 9. demo state: the review fixes, driven on chain ==
  PASS  refused adds were recorded and survived (blocked_attempts > 0)
  PASS  frozen, with the manifest intact after a refused removal

======================================================
  84 passed, 0 failed
======================================================
```
