# PackageGuard

**An npm supply-chain risk oracle that lives on-chain.** Submit a package name;
GenLayer validators independently fetch it from the public npm registry, agree on
a feature vector, and store a five-dimension risk score any contract can read —
or gate a transaction on.

Built for GenLayer, category **Intelligent Contracts**. No frontend: the
contracts are the deliverable, and every claim below is a transaction on a public
network.

```
                  request_scan("event-stream")
                              |
      +-----------------------+------------------------+
      |                       |                        |
  validator 1             validator 2              validator N
  fetch registry          fetch registry           fetch registry
  fetch downloads         fetch downloads          fetch downloads
      |                       |                        |
      +--> 16 coarse ordinals, identical on every node <+
                              |
                   consensus on the VECTOR
                              |
              scores recomputed from the vector
                              |
        stored: evidence + 5 scores + flags + content hash
                              |
              require_safe() <-- any contract, any time
```

---

## Why a feature vector and not a score

The naive design has each validator score the package 0–100 and lets the network
agree on the number. It does not work, and the way it fails is the whole reason
this project is shaped the way it is: two honest validators reading *identical
bytes* produce 72 and 73, those quantize to 70 and 75, and the transaction dies.
Nobody was wrong — the design was.

So validators never agree on a score. They agree on a **feature vector** of
sixteen coarse ordinals, and every number after that is pure integer arithmetic
over it, run identically by the leader, by each validator, by the post-consensus
block, and by `verify_risk` years later. **Bucket width is the consensus
margin** — the tolerance lives in the bucketing, where it is visible and
auditable, instead of in a fuzzy comparison nobody can inspect.

`_agrees` has no tolerance at all: two accepted outputs for one request are the
same bytes.

---

## The rubric

| dimension | weight | what it reads |
|---|---|---|
| popularity | 25% | weekly downloads (log₁₀), npm stars |
| maintenance | 25% | days since last **publish**, releases in the last year, total versions, deprecation |
| security | 20% | licence present, direct dependency count, **install-time scripts**, repository present |
| maturity | 15% | days since first publish, prerelease / 0.x / 1.x+ / multi-major |
| community | 15% | maintainer count, description + keywords + homepage, description quality |

Overall is the weighted average, quantized to a multiple of 5.
**SAFE ≥ 70 · MODERATE 40–69 · HIGH_RISK < 40 · UNKNOWN** for anything unscanned.

### Why maintenance weighs as much as popularity

The probe settled it. **left-pad is deprecated, has not shipped code in eight
years, and still pulls 1.9 million installs a week.** Any rubric leaning on
downloads calls it healthy. Downloads measure how much damage a package *could*
do, not how safe it is.

Two rules sit above the arithmetic:

- **Deprecation quarters maintenance.** `deprecated` on the latest manifest is
  the publisher stating *in the registry* that the package should not be used.
  It is the largest lever in the rubric, and it is pulled by the package's own
  author — not by a model.
- **A deprecated package can never be SAFE**, whatever the total says.

---

## Where the model is used

Almost nowhere, by design. Every count, timestamp, licence string, dependency and
script hook is parsed by pure Python from JSON. Install-time hooks — the delivery
mechanism for essentially every npm compromise — are a dictionary key test, not a
judgement.

The model gets the one job a parser cannot do: whether a description tells a
developer what the package *does*. `"Fast, unopinionated, minimalist web
framework"` and `"my package"` are both non-empty strings of plausible length.

Two yes/no questions, each requiring a fragment copied **verbatim** out of the
description; a model that cannot copy the text it claims to have read has not
read it, and its claim is dropped. Descriptions under 12 characters skip the call
entirely.

**The bound: 3 points out of 100**, before quantization — 20 of community's 100
points × community's 15%. `TestRubric` verifies this across the whole vector
space rather than restating it in a comment. The model is never asked whether a
package is safe.

---

## What is deliberately *not* stored

`weekly_downloads` would be a lovely field to display, and it is absent on
purpose. npm's counter rolls over once a day; a consensus round lasts under two
minutes, so two validators would read the same number about 99.9% of the time and
**hang the round the rest**. A field that is right almost always is exactly the
kind that fails in front of an audience.

The record stores the band the bucket represents (`"10M-100M"`), which is derived
from the bound vector and cannot drift.

---

## Methods

### Write

| method | notes |
|---|---|
| `request_scan(package_name)` *payable* | The oracle. Returns a status object — **it never raises once value is attached**; every refusal credits the full amount back. Rate limited to one per wallet per 300 s, one per package per 900 s. |
| `set_fee(new_fee)` | Owner only, bounded 0 – 0.1 GEN. |

Operational writes a payable contract cannot do without: `claim_refund()` (pull,
not push — anyone), `set_paused(bool)`, `transfer_ownership(addr)`,
`withdraw(amount)` (owner only, capped at `balance − refunds_owed`).

### View — free, callable by any contract

| method | returns |
|---|---|
| `get_risk(package_name)` | full breakdown: five scores, level, badge, flags, bands, evidence, content hash |
| `get_risk_by_id(score_id)` | one historical scan; says so honestly if it has rotated out of the 12-scan window |
| `get_risk_history(package_name, count)` | past scans, newest first, with best/worst |
| `is_safe(package_name, min_score)` | bool — **an unscanned package is not safe** |
| `require_safe(package_name, min_score)` | **reverts** unless the package clears the bar |
| `get_top_packages(count)` | safest first |
| `get_riskiest(count)` | most dangerous first |
| `verify_risk(score_id)` | recomputes the record from `evidence` alone and reports whether it still matches |
| `get_stats()` | totals, averages, level histogram |
| `get_config()` | fee, weights, thresholds, **every ladder**, limits, model bound |

Plus `get_packages(offset, count)`, `get_flag_counts()`, `refund_of(addr)`,
`get_gov_log(count)`.

### Findings the rubric can raise

`DEPRECATED` · `INSTALL_SCRIPTS` · `NO_LICENSE` · `ABANDONED` · `STALE` ·
`SINGLE_MAINTAINER` · `HEAVY_DEPS` · `NO_REPOSITORY` · `PRERELEASE` ·
`UNSTABLE_API` · `LOW_ADOPTION` · `NEW_PACKAGE` · `NO_RECENT_RELEASE` ·
`POOR_METADATA` · `NO_DOWNLOAD_DATA`

Every one is a pure function of the agreed vector, so a reader can check each
flag against `evidence` without trusting anybody.

---

## Governance cannot move a score

No setter writes one. Weights, ladders, thresholds and licence tables are
**module constants, not storage**, and a test walks the AST to prove no method
assigns to them. The rate limiter and cooldown are constants for the same reason:
an owner who can retune them can clear the way for one address to flood the
leaderboard.

---

## Composability — `PackageConsumer`

> *"CI pipeline rejects packages scoring below 50."*

A dependency allowlist whose policy is a contract rather than a config file.
Every decision — `add_dependency`, `preview_dependency` and `gate_build` alike —
is made by one function reading `PackageGuard.get_risk`, so a preview and a build
cannot answer differently. `PackageGuard.require_safe` still has the last word
before anything is written: the manifest row is built from what `require_safe`
**returned**, so the oracle's own reverting gate decides what may enter the
manifest rather than merely commenting on it.

| method | notes |
|---|---|
| `add_dependency(pkg)` | writes the row, or returns `{ok: false, reason: "blocked by policy"}` and counts the refusal |
| `remove_dependency(pkg)` | anyone, while the contract is open — removing is always the safe direction |
| `check_risk(pkg)` | risk level as this consumer sees it; never raises |
| `preview_dependency(pkg)` | the same decision, same code path, **degrades** instead of reverting |
| `gate_build([pkg, …])` | the scenario in one call: PASS/FAIL for a whole dependency list |
| `get_manifest()` / `has_dependency(pkg)` / `get_policy()` / `get_oracle_stats()` |  |
| `set_policy(min_score, banned_flags, max_age)` / `set_oracle` / `transfer_ownership` | owner only |
| `freeze()` | owner only, one-way, and **total**: after it no public write succeeds |

**A refusal is not a revert.** A package that fails the policy does not raise —
it increments `blocked_attempts` and returns the refusal. That is the only way
the counter can mean anything: a revert unwinds the whole call, so a counter
bumped immediately before raising is rolled back with everything else and the
contract silently forgets every request it turned down. Nothing after the
increment can raise, and the static test in `test/test_logic.py` asserts that
about the block itself rather than about line order.

An **unreachable oracle is not a refusal** and is not counted — it raises.
"the source was down" and "the package failed policy" are different answers, and
filing the first under the second is how an availability failure becomes a
permanent, wrong record.

**Freeze means frozen.** After `freeze()` no public write succeeds — not
`add_dependency`, not `remove_dependency`, not a policy, oracle or ownership
change, and not a second `freeze()`. A guard on some mutators and not others
would make a published manifest worth nothing to the person it is published for,
so the guard is one method called from one place and a test enumerates every
`@gl.public.write` out of the source to check none of them skips it.

The consumer adds one rule of its own **on top of** the score: a banned flag
blocks regardless of the number, because *"well maintained"* and *"safe to run in
my build"* are different questions and only the second is the consumer's
business. A package can score 80 and still be refused for carrying a
`postinstall`.

---

## Repository layout

```
contracts/
  PackageGuard.py        the oracle          (81,216 bytes readable)
  PackageConsumer.py     the CI gate
  _render_probe.py       throwaway diagnostic, deployed before anything else
build/
  PackageGuard.min.py    the deployed artifact  (43,633 bytes)
  PackageConsumer.min.py                        (14,503 bytes)
docs/
  PROBE.md               what validator egress actually sees — 11 findings
  DESIGN.md              why every decision is what it is
test/
  test_logic.py          389 offline tests, stdlib only
  fixtures.json          real packuments, rebuilt by tools/make_fixtures.py
tools/
  make_fixtures.py       refetch fixtures from the live registry
  minify_contract.py     source -> deployable artifact
  e2e_studionet.sh       paced multi-package scan, respects the rate limiter
  audit.sh               84 pre-submission checks, exits with the failure count
  deploy_bradbury.sh     the testnet deploy
deployments.json         addresses, tx hashes, sha256 per artifact
```

---

## Running it

```bash
# offline: no chain, no network, no model, no genlayer install
python3 test/test_logic.py

# rebuild the deployable artifacts
python3 tools/minify_contract.py contracts/PackageGuard.py -o build/PackageGuard.min.py
python3 tools/minify_contract.py contracts/PackageConsumer.py -o build/PackageConsumer.min.py

# refetch the test fixtures from the live registry
python3 tools/make_fixtures.py

# scan several packages, paced for the contract's own rate limiter
bash tools/e2e_studionet.sh <oracle-address> express left-pad event-stream
```

---

## Live on two networks

| contract | Bradbury testnet | Studionet |
|---|---|---|
| **PackageGuard** | `0x4f35Fd3D93bDb8446C3ccf715B684222D93BB8fE` | `0x1F3f51d9927490543519d6C61b9B544bf5caA7FB` |
| **PackageConsumer** | `0xcDEAD088A846309a7F3c39477101b90772940D25` | `0x96Db4DBE72892b788E311e33cEA8807d921ca960` |
| render probe (throwaway) | — | `0xAA236cC1Cd182879915E90DAc796D94d6bc32C90` |

Both consumers are the **reviewed build**. PackageGuard was not redeployed — it
is unchanged by the review fixes, and each consumer points at the oracle that
was already there. The rev1 consumers
(`0x76B22B4aDcfBe55Bc639d8FaE42C4B5Cb41780a4` on Bradbury,
`0x0d9e9be2627B014eC78bD206d91dF24eC4B8d90d` on Studionet) are kept in
`deployments.json` because earlier transcripts were taken against them.

**One artifact, both networks.** The deployed source on each is byte-identical to
its artifact, and to the other:

```
$ genlayer code 0x4f35Fd3D93bDb8446C3ccf715B684222D93BB8fE | diff - build/PackageGuard.min.py
$ genlayer code 0x1F3f51d9927490543519d6C61b9B544bf5caA7FB | diff - build/PackageGuard.min.py
$ shasum -a 256 build/PackageGuard.min.py
56fd5144a97d489445c0de0cddcf7431c1139d58d485c8e97e2908640ecb3a4e

$ genlayer code 0xcDEAD088A846309a7F3c39477101b90772940D25 | diff - build/PackageConsumer.min.py
$ genlayer code 0x96Db4DBE72892b788E311e33cEA8807d921ca960 | diff - build/PackageConsumer.min.py
$ shasum -a 256 build/PackageConsumer.min.py
aed9d3d308b57ce5b3da33eb4610240472315073da2c729317d14c8610c461d6
```

The Bradbury consumer is verified read-only: source identity, wiring
(`get_policy` reports the right oracle, `get_oracle_stats` reads it
cross-contract), and the full decision path through `gate_build`. The
write-path evidence below — `blocked_attempts` surviving three refusals, and
`freeze()` then `remove_dependency` — was taken on Studionet against the
byte-identical artifact, because `freeze()` is one-way.

### The same package, the same hash, two validator sets

`express`, scanned independently on each network:

```
Bradbury    content_hash 162:16effac907d8a715   overall 85   SAFE
Studionet   content_hash 162:16effac907d8a715   overall 85   SAFE

evidence (identical on both):
  {"age":5,"cadence":3,"depr":0,"deps":1,"desc":2,"dl":7,"fresh":4,"hooks":1,
   "lic":2,"maint":3,"meta":3,"repo":1,"src_dl":1,"stab":3,"stars":4,
   "versions":5}
```

All sixteen ordinals matched — the model-derived `desc` included — so the digest
over *(package name + vector)* is the same string on both chains. One program,
two independent validator sets, agreeing exactly.

**The honest caveat**, because it is the more interesting result: an earlier
Studionet round produced `desc=1` for this same package and therefore a different
hash — while `overall` stayed **85**, because the model's 3-point bound plus the
step-5 quantization absorbed the difference. Determinism is enforced *within* a
round with no tolerance at all; *across* rounds the fifteen parsed ordinals are
stable and the single model ordinal is bounded. That is the whole design in one
observation.

### Seven real packages, scored on-chain (Studionet)

| package | overall | level | badge | findings |
|---|---|---|---|---|
| `express` | **85** | SAFE | TRUSTED | `HEAVY_DEPS` |
| `chalk` | **85** | SAFE | TRUSTED | `SINGLE_MAINTAINER` |
| `esbuild` | **80** | SAFE | SAFE | `INSTALL_SCRIPTS`, `SINGLE_MAINTAINER`, `UNSTABLE_API` |
| `left-pad` | **65** | MODERATE | REVIEW | `DEPRECATED`, `ABANDONED`, `NO_RECENT_RELEASE` |
| `event-stream` | **65** | MODERATE | REVIEW | `ABANDONED`, `SINGLE_MAINTAINER`, `NO_RECENT_RELEASE` |
| `node-sass` | **55** | MODERATE | REVIEW | `DEPRECATED`, `INSTALL_SCRIPTS`, `ABANDONED`, `NO_RECENT_RELEASE` |
| `flatmap-stream` | **30** | HIGH_RISK | AVOID | `NO_LICENSE`, `ABANDONED`, `SINGLE_MAINTAINER`, `PRERELEASE`, `LOW_ADOPTION`, `NO_RECENT_RELEASE` |

`flatmap-stream` is the package that actually carried the payload in the 2018
event-stream compromise. Nothing in the registry marks it as malicious — it is
not deprecated and npm does not flag it. **The rubric reaches HIGH_RISK from the
shape alone:** no licence, one maintainer, one version, a `-security` prerelease
tag, 197 installs a week, and nothing published in over four years.

`event-stream` itself is instructive in the other direction. It is MIT licensed,
carries no deprecation, and still pulls 6.4M installs a week — npm says nothing
is wrong. What the data *does* say is **one maintainer** and **no publish in over
four years**, which is exactly the shape the 2018 incident had: a lone maintainer
handed the package to a stranger. The contract scores that shape; it does not
claim to know about the incident.

### The one full record

```
$ genlayer call 0x1F3f51d9927490543519d6C61b9B544bf5caA7FB get_risk --args left-pad

  package:        'left-pad'          latest_version: '1.3.0'
  overall_score:  65                  risk_level:     'MODERATE'
  badge:          'REVIEW'            confidence:     'HIGH'
  risk_flags:     [ 'DEPRECATED', 'ABANDONED', 'NO_RECENT_RELEASE' ]
  scores:  { popularity: 65, maintenance: 5, security: 100,
             maturity: 100, community: 75 }
  bands:   { downloads: '1M-10M', last_publish: '>4y',
             age: '>8y', direct_deps: '0' }
  evidence: '{"age":5,"cadence":0,"depr":1,"deps":5,"desc":2,"dl":5,"fresh":0,
              "hooks":1,"lic":2,"maint":2,"meta":3,"repo":1,"src_dl":1,
              "stab":3,"stars":2,"versions":3}'
  content_hash: '163:7da5db08d7d5f685'
  sources_ok:   'registry,downloads'
```

Read that record: **maintenance 5, security 100.** left-pad is deprecated and
abandoned, and it is also zero-dependency, install-hook-free, permissively
licensed and twelve years old. It is *obsolete*, not *dangerous*, and the rubric
says both instead of smearing one bad dimension across the others. The `SAFE`
override is what keeps it out of the top band anyway.

Note `last_publish: '>4y'`. npm's `time.modified` for left-pad says **867 days** —
that is the day somebody deprecated it. Its last actual publish was **3,066 days**
ago (PROBE.md §11).

### The audit path

```
$ genlayer call 0x1F3f51d9927490543519d6C61b9B544bf5caA7FB verify_risk --args 1

  verified: true
  stored:     { overall: 85, risk_level: 'SAFE', content_hash: '162:16effac907d8a715' }
  recomputed: { overall: 85, risk_level: 'SAFE', content_hash: '162:16effac907d8a715' }
```

The record was recomputed from `evidence` alone and matched — scores, level,
badge, confidence, every flag, and the hash.

### Determinism, and the exact size of the model's influence

express was scanned twice, on two independent deployments, by different validator
rounds minutes apart:

| | round 1 | round 2 |
|---|---|---|
| the 15 **parsed** ordinals | `age 5 · cadence 3 · depr 0 · deps 1 · dl 7 · fresh 4 · hooks 1 · lic 2 · maint 3 · meta 3 · repo 1 · src_dl 1 · stab 3 · stars 4 · versions 5` | **identical** |
| `desc` (the **only** model-derived ordinal) | 1 | 2 |
| community | 80 | 90 |
| **overall** | **85 SAFE** | **85 SAFE** |

Exactly one ordinal moved between rounds, and it is the one the model produces.
Its 3-point bound plus the step-5 quantization absorbed the difference entirely,
so the published score did not move. Within each round every validator agreed —
`_agrees` has no tolerance, so the round could not have committed otherwise.

*(The two deployments differ by one commit — a tightening of licence-prefix
matching that cannot affect an MIT package, so `lic` is 2 under both.)*

### Composability, exercised

Against the reviewed consumer at `0x96Db4DBE72892b788E311e33cEA8807d921ca960`:

```
$ genlayer write 0x96Db4DBE72892b788E311e33cEA8807d921ca960 add_dependency --args express
  -> {"ok":true,"status":"OK","manifest_size":1}

$ genlayer write ... add_dependency --args flatmap-stream
  -> {"ok":false,"status":"BLOCKED","reason":"blocked by policy",
      "detail":"scores 30, policy requires 50",
      "overall_score":30,"blocked_attempts":1}

$ genlayer write ... add_dependency --args esbuild
  -> {"ok":false,"status":"BLOCKED","reason":"blocked by policy",
      "detail":"carries banned flag(s): INSTALL_SCRIPTS",
      "overall_score":80,"blocked_attempts":2}

$ genlayer write ... add_dependency --args lodash
  -> {"ok":false,"status":"BLOCKED","reason":"blocked by policy",
      "detail":"never scanned; call PackageGuard.request_scan",
      "blocked_attempts":3}

$ genlayer call ... get_policy
  -> blocked_attempts: 3          # three refusals, three increments kept
     manifest_size:    1

$ genlayer write ... freeze
  -> {"ok":true,"status":"OK","frozen":true}

$ genlayer write ... remove_dependency --args express
  -> ERROR: contract is frozen

$ genlayer write ... add_dependency --args chalk
  -> ERROR: contract is frozen

$ genlayer call ... get_manifest
  -> count: 1, package: express, frozen: true      # untouched
```

**esbuild is the interesting one.** It scores 80 and is `SAFE` — a healthy,
actively maintained package — and the CI gate refuses it anyway, because it runs
a `postinstall`. The oracle's job is to say how well kept a package is; deciding
whether that is acceptable is the consumer's, and the two are separate contracts
for exactly that reason.

The whole scenario in one call:

```
$ genlayer call ... gate_build --args '["express","chalk","esbuild","left-pad","flatmap-stream","lodash"]'

  build:   'FAIL'
  checked: 6
  blocked: [ 'esbuild', 'left-pad', 'flatmap-stream', 'lodash' ]
  policy:  { min_score: 50,
             banned_flags: [ 'INSTALL_SCRIPTS', 'DEPRECATED', 'NO_LICENSE' ],
             max_age_seconds: 604800 }
```

…with a per-package `reason` for every row: `clears the bar`,
`carries banned flag(s): INSTALL_SCRIPTS`, `scores 30, policy requires 50`,
`never scanned; call PackageGuard.request_scan`.

### Corpus totals

```
$ genlayer call 0x1F3f51d9927490543519d6C61b9B544bf5caA7FB get_stats

  packages_tracked: 7     total_scanned: 7      rejected: 0
  risk_levels:      { SAFE: 3, MODERATE: 3, HIGH_RISK: 1 }
  average_scores:   { overall: 66, popularity: 70, maintenance: 37,
                      security: 80, maturity: 89, community: 65 }
```

**Average maintenance across the corpus is 37, against security 80 and maturity
89.** That is the finding the whole rubric exists to surface: npm's problem is
not that packages are badly built, it is that they stop being looked after.

---

## What the probe found

`contracts/_render_probe.py` was deployed to Studionet **before a line of
extraction was written**. Eleven findings are in [`docs/PROBE.md`](docs/PROBE.md);
four of them changed the design:

1. **There is no practical body-size ceiling.** A validator fetched and
   `json.loads`-ed typescript's **15,618,607-byte** packument. This was the
   decisive question: the packument is the only document carrying `time.created`,
   so if validators could not hold one, package age would not be scorable at all
   and the maturity dimension would have had to be dropped.
2. **`time.modified` is not the last publish.** It moves on any metadata edit.
   left-pad: 867 days vs **3,066**. event-stream: 1,392 vs **2,893**.
3. **The packument's `readme` is empty for express and event-stream** while chalk
   carries 13,885 bytes. npm does not populate it consistently, so it is not a
   documentation signal and is not scored.
4. **`JSONStream` and `jsonstream` are two different live packages** (93 KB and
   7 KB). Case-folding the name to make a storage key canonical would have
   silently scored the wrong package.

## Deliberately rejected: `/-/v1/search`

The search endpoint returns everything this contract needs in 1.1 KB — including
`score.detail.{quality, popularity, maintenance}`. It is not used, because that
is **npms.io's opinion**. Consuming it would make PackageGuard a cache of
somebody else's score rather than an oracle that derives its own.

## Testing

```
$ python3 test/test_logic.py
Ran 389 tests in 0.7s
OK
```

stdlib only — no chain, no network, no model, no genlayer install. Run against
**real packuments** pulled from the live registry by `tools/make_fixtures.py`.
That mattered: a fixture an author writes by hand is a fixture that agrees with
whatever the author already believed, and three bugs fell out that hand-written
fixtures would have hidden. None of them threw; **all three produced a plausible
wrong number**, which is the class of bug an oracle exists to prevent:

- `_as_text` read `{"type": "git", "url": …}` as `"git"` — three characters,
  failing a length test — which put **`NO_REPOSITORY` on every healthy package in
  the corpus** and cost each of them 15 points of security.
- `time.modified` used as the last publish (finding 2 above).
- `readme` scored as documentation (finding 3 above).

The suite also runs a **static undefined-name check over the whole file including
class bodies** — a name error inside a `@gl.public.view` only fires when that
view is called on-chain — and re-runs the entire battery through the **minified
artifact**, because "the source is correct" is only half a claim; the other half
is that the deployed file is the same program.

## Pre-submission audit

```
$ bash tools/audit.sh 0x1F3f51d9927490543519d6C61b9B544bf5caA7FB 0x96Db4DBE72892b788E311e33cEA8807d921ca960 exercised
  84 passed, 0 failed
```

Every check runs; none is asserted. It covers lint on sources **and artifacts**,
the runner pin, the offline suite, whether the committed artifacts are a current
build of their sources, repo hygiene (including **no AI attribution in any commit
message**), whether the README's own byte counts and hashes match the files, the
full method surface, and the live deployment — that `genlayer code <address>`
diffs clean against `build/PackageGuard.min.py`, that `verify_risk` returns true,
that `require_safe` reverts, and that the consumer reads the oracle
cross-contract. It exits with the failure count, so it works as a CI gate.

Group 3b exists because of the review. Both findings are checked mechanically
over the source **and** the deployed artifact: every `@gl.public.write` carries
the frozen guard, a refusal is returned rather than raised, and **no storage
write in either contract has a reachable `raise` after it**. One check runs the
new tests against the *pre-fix* contract and fails if they pass — a regression
test nobody has watched fail is not a regression test.

Full output and the limitations stated rather than hidden:
[`docs/AUDIT.md`](docs/AUDIT.md).

## Deploying

```bash
bash tools/deploy_bradbury.sh
```

Deploys both artifacts, sets the demo fee to 0, and prints a smoke-test script.
The fee is 0 because the `genlayer` CLI hardcodes `value: 0n` on writes, so a
non-zero fee would make the payable `request_scan` uncallable from the command
line; the fee, refund and overpayment logic is covered offline instead.
