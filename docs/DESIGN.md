# PackageGuard — design

An oracle is only worth anything if two independent nodes cannot disagree about
what it says. Everything below follows from that one requirement.

Measured source shapes: [`PROBE.md`](PROBE.md). Contract:
[`../contracts/PackageGuard.py`](../contracts/PackageGuard.py).

---

## 1. The problem with scoring on-chain

The naive design has each validator fetch npm, score the package 0–100, and let
the network agree on the number. It does not work, and the way it fails is
instructive: two honest validators reading *identical bytes* produce 72 and 73,
those quantize to 70 and 75, and the transaction dies. Nobody was wrong. The
design was.

Loosening to "agree within ±5" is worse, not better. It means the contract has
no single answer — the stored score becomes whichever validator happened to
lead, and the tolerance is a hole an adversarial leader aims at.

## 2. What validators actually bind

Validators agree on a **feature vector**: sixteen coarse ordinals, plus the
package's `latest` version and description. Every score is then pure integer
arithmetic over that vector, run identically by the leader, by each validator,
by the post-consensus block, and by `verify_risk` years later.

```
dl       0-7  weekly downloads, log10           stars    0-4  npm stars
fresh    0-6  days since last PUBLISH           cadence  0-5  publishes in 365d
versions 0-5  total versions ever               depr     0-1  latest deprecated
lic      0-2  missing / unrecognised / known    deps     0-5  direct deps (fewer better)
hooks    0-1  no install-time script            repo     0-1  repository present
age      0-5  days since first publish          stab     0-3  prerelease / 0.x / 1.x+ / multi-major
maint    0-4  maintainer accounts               meta     0-3  description, keywords, homepage
desc     0-2  description quality (the model)   src_dl   0-1  downloads document resolved
```

**Bucket width is the consensus margin.** The ladders are decade-scale on
purpose: express's weekly download count changes between two validators' fetches
and lands on the same rung both times. There is no tolerance in `_agrees` — two
accepted outputs for one request are the same bytes — because the tolerance
lives in the bucketing, where it is visible and auditable.

`now` is captured once, before the consensus block, and passed into the task, so
two nodes seconds apart cannot straddle a day boundary and disagree about a
package neither of them read differently.

## 3. Post-consensus recompute

The leader's numbers never reach storage. After consensus, every stored field is
recomputed from the agreed vector:

```
evidence      = canonical JSON of the vector          <- the consensus object
five scores   = _score(vector)                        <- recomputed
risk_level    = _risk_level(overall, vector)          <- recomputed
risk_flags    = _risk_flags(vector)                   <- recomputed
bands         = _bands(vector)                        <- recomputed
sources_ok    = _sources(vector)                      <- recomputed, not copied
content_hash  = fnv1a(package_name + canonical vector)
```

`verify_risk(score_id)` replays the whole thing from `evidence` alone and reports
`verified: true/false` with both records side by side. That is what makes a score
*auditable* rather than merely *signed*: the rubric is a module constant, so
anybody can check the arithmetic without trusting the validator set that ran it.

## 4. Weights, and why maintenance is as heavy as popularity

```
popularity  25%   maintenance 25%   security 20%   maturity 15%   community 15%
```

The probe settled this. **left-pad is deprecated, has not shipped code in eight
years, and still pulls 1.9 million installs a week** (PROBE.md section 4). Any
rubric that leans on downloads calls it healthy. Downloads measure how much
damage a package *could* do, not how safe it is — so popularity is capped at a
quarter, and maintenance, which is what actually separates left-pad from express,
carries the same weight.

Within each dimension the arithmetic is a weighted integer average of ordinals
taken as a share of their own ceiling, snapped to a multiple of 5. No floats
anywhere — a float in a rubric is a consensus bug waiting to happen, and
`TestStatic.test_no_floats_in_the_scoring_path` fails the build over one.

Two rules sit above the arithmetic:

- **Deprecation quarters maintenance.** `deprecated` on the latest manifest is
  the publisher stating in the registry that the package should not be used. It
  is the largest lever in the rubric and it is pulled by the package's own
  author, not by a model.
- **A deprecated package can never be SAFE**, whatever the total says. left-pad
  is the case in point: zero dependencies, no install hooks, permissively
  licensed, twelve years old — every security and maturity term maxed. It scores
  60 and comes back MODERATE, and the override is there so that a *better* case
  could not slip through as SAFE while its author says do not use it.

## 5. Where the model is used, and where it is not

Almost nowhere. Every count, timestamp, licence string, dependency and script
hook is parsed by pure Python from JSON. Install-time hooks — the delivery
mechanism for essentially every npm compromise — are a dictionary key test, not
a judgement.

The model gets the one job a parser cannot do: whether a description tells a
developer what the package *does*. `"Fast, unopinionated, minimalist web
framework"` and `"my package"` are both non-empty strings of plausible length,
and the `meta` ordinal has already given each of them the same point.

Two yes/no questions, each requiring a fragment copied **verbatim** out of the
description, collapsed to a 0–2 ordinal by counting the ones that survive. A
model that cannot copy the text it claims to have read has not read it, and its
claim is dropped. A description under 12 characters skips the call entirely —
there is nothing to judge, and a model asked to judge nothing is a coin flip
inside a consensus round.

**The bound:** 20 of community's 100 points × community's 15% = **3 points of
100**, before quantization. Snapping to a multiple of 5 can present those 3
points as one 5-point rung, and near a threshold that rung can move a level —
that is a property of quantizing at all, not of the model, and 3 raw points is
the honest number. `TestRubric` checks all of this over the whole vector space
rather than restating it in a comment.

The description is publisher-controlled, so it is the one place an attacker can
address the model directly. It is sanitised of delimiters and angle brackets, and
the prompt marks it as data.

## 6. Two failure classes, kept apart

Inherited from TokenScope, where confusing them hung a round until the client
gave up:

- **4xx is a deterministic absence.** Every node sees it, so it can safely become
  an answer. `registry.npmjs.org/<nonexistent>` is a 21-byte 404 on every
  validator, and the request refuses cleanly with a refund.
- **5xx, a timeout, or an unparseable body is a broken server** — node-dependent
  by nature. It propagates and fails the whole request, so every node fails
  identically, `_handle_leader_error` matches on the class, and the network
  settles on one refusal rather than scoring a package on whichever documents
  happened to load for whichever node happened to lead.

The downloads document is allowed to be *deterministically* absent: a 404 sets
`src_dl = 0`, which is a consensus field, appears in `evidence`, and raises
`NO_DOWNLOAD_DATA`. A 5xx there still fails the request.

## 7. What is deliberately not stored

`weekly_downloads` would be a lovely field to display, and it is absent on
purpose. npm's counter rolls over once a day; a consensus round lasts under two
minutes, so two validators would read the same number about 99.9% of the time and
hang the round the rest. **A field that is right almost always is exactly the
kind that fails in front of an audience.** The record stores the band the bucket
represents (`"10M-100M"`), which is derived from the bound vector and cannot
drift.

`latest_version` and `description` *are* bound, because they change only on a
publish — and a publish moves the whole vector anyway, so binding them adds no
new failure mode.

## 8. Governance cannot move a score

No setter writes one. Weights, ladders, thresholds and licence tables are module
constants, not storage, and a test walks the AST to prove no method assigns to
them. The rate limiter and cooldown are constants for the same reason: an owner
who can retune them can clear the way for one address to flood the leaderboard.

The owner may set the fee within 0–0.1 GEN, pause new scanning (reads, refunds
and `require_safe` keep working), transfer ownership, and withdraw
`balance − refunds_owed`. Every call is logged.

Refunds are credited, never reverted: a payable call that raises keeps the
deposit with no record to refund it from, so no path in `request_scan` raises
once value is attached — it returns a `REJECTED` object and credits the full
amount, claimable with `claim_refund()`.

## 9. The leaderboard keeps both tails

`get_top_packages` and `get_riskiest` read off one bounded array. When it
overflows, the entries dropped are the ones in the **middle** — a package in the
middle of the distribution is the one neither list would ever show. An ordinary
top-K would drop the tail, which would make `get_riskiest` go quiet exactly as
more dangerous packages arrived.

## 10. Composability

`require_safe(package_name, min_score)` **reverts** rather than returning false.
That is the primitive: a calling contract has no boolean to ignore and no branch
to forget.

[`PackageConsumer`](../contracts/PackageConsumer.py) is built on it — a CI
dependency allowlist whose policy is a contract rather than a config file.
`add_dependency` calls `require_safe` first, so the manifest physically cannot
hold a package that failed policy. `preview_dependency` asks the same question
through the same code path without a transaction and *degrades*, returning
`{allowed: false, reason: …}` for a package nobody has scanned, so a UI can
explain rather than show a revert.

The consumer adds one rule of its own on top of the score: a banned flag blocks
regardless of the number, because "well maintained" and "safe to run in my build"
are different questions and only the second is the consumer's business. A package
can score 80 and still be refused for carrying a `postinstall`.

## 11. Testing

`test/test_logic.py` — stdlib only, no chain, no network, no model — runs the
whole pure half against **real packuments** pulled from the live registry by
`tools/make_fixtures.py`. A fixture an author invents is a fixture that agrees
with whatever the author already believed; three of this project's bugs were
found because the fixtures were real:

- `_as_text` read `{"type": "git", "url": …}` as `"git"`, three characters, which
  failed a length test and put **NO_REPOSITORY on every healthy package in the
  corpus**, costing each 15 points of security.
- `time.modified` is not the last publish (PROBE.md section 11).
- the packument's `readme` is empty for express (PROBE.md section 10).

It also runs a static undefined-name check over the *whole* file including class
bodies — a name error inside a `@gl.public.view` only fires when that view is
called on-chain, which is how TokenScope shipped a dangling `ok` in `verify_risk`
to a network — and re-runs the entire battery through the **minified artifact**,
because "the source is correct" is only half a claim; the other half is that the
deployed file is the same program.
