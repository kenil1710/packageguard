# Render probe — what validator egress actually sees

Throwaway contract `contracts/_render_probe.py`, deployed to Studionet at
**`0xAA236cC1Cd182879915E90DAc796D94d6bc32C90`**, run before a line of
PackageGuard was written. Everything below is a body a GenLayer validator
fetched, not a body fetched from a laptop. Every extraction rule in
`contracts/PackageGuard.py` is written against these observations and cites the
section number.

Probed 2026-08-31.

---

## 1. Is registry.npmjs.org reachable from validators?

Yes, unauthenticated, no key, no CORS shim, no browser needed. `probe_statuses`
on the four decisive URLs:

| URL | status | bytes |
|---|---|---|
| `registry.npmjs.org/express` | 200 | 804,975 |
| `api.npmjs.org/downloads/point/last-week/express` | 200 | 83 |
| `registry.npmjs.org/left-pad` | 200 | 22,573 |
| `registry.npmjs.org/event-stream` | 200 | 119,714 |

Byte counts are identical to the same fetches made off-chain minutes earlier, so
the runner is not truncating or transcoding. **No pivot needed.**

## 2. The body-size ceiling — the question that shaped the design

An npm packument is not a small document. It embeds *every version manifest ever
published*, so its size scales with release count:

| package | versions | packument |
|---|---|---|
| left-pad | 15 | 22 KB |
| event-stream | 84 | 120 KB |
| express | 288 | 805 KB |
| react | 2,924 | 6.9 MB |
| **typescript** | **3,811** | **15.6 MB** |

This mattered because the packument is the **only** source of `time.created` and
`time.modified`, and those two fields carry the whole maturity dimension and most
of maintenance. If validators could not hold one, the design would have had to be
assembled from small endpoints and lose package age entirely.

`probe_statuses` on react returned `status 200, len 6926968`. `probe_packument`
on typescript **fetched and `json.loads`-ed 15,618,607 bytes inside the GenVM**
and returned `n_versions: 3811, time_entries: 3816, created 2012-10-01`.
TypeScript is at or near the largest packument on the registry.

**Finding: there is no practical body-size ceiling for this data source.** The
packument is safe as PackageGuard's primary fetch, and the abbreviated-packument
fallback (section 6) was never needed. `PACKUMENT_CHARS` is set to 20,000,000
from this measurement rather than from a guess.

## 3. The packument carries every field the rubric needs

`probe_packument express` → derived facts, one transaction:

```json
{"status": 200, "len": 804975,
 "top_keys": ["_id","_rev","author","bugs","contributors","description",
              "dist-tags","homepage","keywords","license","maintainers","name",
              "readme","readmeFilename","repository","time","users","versions"],
 "created": "2010-12-29T19:38:25.450Z", "modified": "2026-08-15T20:58:49.104Z",
 "time_entries": 320, "n_versions": 288, "latest": "5.2.1",
 "license": "MIT", "n_deps": 28, "n_keywords": 10, "n_maintainers": 5,
 "has_description": true, "has_homepage": true, "has_repository": true,
 "deprecated": "None", "unpackedSize": 75429, "fileCount": 10,
 "scripts": ["lint","lint:fix","test","test-ci","test-cov","test-tap"],
 "dist_keys": ["fileCount","integrity","shasum","signatures","tarball",
               "unpackedSize"]}
```

Consequences, each one load-bearing:

- **`time` is a flat map of version → ISO timestamp**, plus `created` and
  `modified`. 320 entries for express's 288 versions. Release *frequency* is
  therefore countable — how many of those timestamps fall inside the last 365
  days — not merely inferable from a version count.
- **`dist-tags.latest` names the manifest to read**, and `versions[latest]` holds
  `dependencies`, `scripts`, `license`, `deprecated` and `dist`.
- **`scripts` is exact.** Install-time hooks (`install`, `preinstall`,
  `postinstall`) are the single biggest npm supply-chain risk, and they are a
  dictionary key test, not a judgement. No model is needed to find them.
- **`users` is npm's star map** — 2,649 for express, 947 chalk, 101 event-stream,
  11 left-pad, 3 is-odd, and absent entirely for flatmap-stream. A popularity
  signal from the same document, costing no extra fetch.

## 4. The three demo packages are separable from the data alone

| | express | left-pad | event-stream |
|---|---|---|---|
| created | 2010-12-29 | 2014-03-14 | 2011-08-22 |
| modified | 2026-08-15 | 2024-04-16 | 2022-11-08 |
| days stale | 15 | 866 | **1,391** |
| versions | 288 | 15 | 84 |
| latest | 5.2.1 | 1.3.0 | 4.0.1 |
| direct deps | 28 | 0 | 7 |
| license | MIT | WTFPL | MIT |
| maintainers | 5 | 2 | **1** |
| **deprecated** | no | **`"use String.prototype.padStart()"`** | no |
| install scripts | none | none | none (`prepublish` only) |
| weekly downloads | 132,879,571 | 1,855,290 | 6,442,255 |

Two findings that fixed the rubric:

- **left-pad self-reports.** Its latest manifest carries a `deprecated` string.
  Abandonment does not have to be inferred from staleness — the registry states
  it. That is why `depr` is a first-class vector field with a hard multiplier
  rather than a soft penalty.
- **left-pad still gets 1.86M downloads a week.** Popularity alone cannot
  separate a dead package from a live one; 866 days of silence and a deprecation
  notice can. This is the whole argument for scoring five dimensions instead of
  ranking by downloads, and the reason maintenance carries the same 25% weight as
  popularity.
- **event-stream is not flagged by npm at all.** No deprecation, MIT licensed,
  6.4M weekly downloads. What the data *does* say is 1,391 days since the last
  publish and a **single maintainer** — which is exactly the shape of the 2018
  incident, where a lone maintainer handed the package to a stranger. The
  contract scores that shape; it does not claim to know about the incident.
  `flatmap-stream`, the package that actually carried the payload, probes as
  197 weekly downloads, 1 version, **no license**, 1,581 days stale, 0 stars.

## 5. Small endpoints — shapes and sizes

| URL | bytes | carries |
|---|---|---|
| `api.npmjs.org/downloads/point/last-week/{pkg}` | 83 | `{"downloads":132879571,"start":…,"end":…,"package":…}` |
| `registry.npmjs.org/{pkg}/latest` | 3,508 | latest manifest alone, no dates |
| `registry.npmjs.org/-/v1/search?text={pkg}&size=1` | 1,147 | last publish date, `dependents`, `flags.insecure`, **and npms.io `score.detail`** |
| `api.npmjs.org/versions/{pkg}/last-week` | 3,959 | per-version download split |
| `registry.npmjs.org/-/package/{pkg}/dist-tags` | 38 | tags only |

PackageGuard uses the packument and the **downloads point endpoint** and nothing
else. The search endpoint was deliberately rejected despite being the most
convenient: it returns `score.detail.{quality,popularity,maintenance}`, which is
npms.io's opinion. Consuming it would make PackageGuard a cache of somebody
else's score rather than an oracle that derives its own.

## 6. Request headers — available, and not needed

`probe_headers` confirmed `gl.nondet.web.request(url, method="GET",
headers={...})` is accepted by this runner. `Accept:
application/vnd.npm.install-v1+json` returns an abbreviated packument — express
drops 805 KB → 339 KB — but **strips `time` entirely**, so it cannot answer age
or staleness. Recorded as a dead end so nobody re-derives it; section 2 removed
the need.

## 7. Missing packages fail deterministically

```
registry.npmjs.org/this-package-does-not-exist-pg9   → 404 {"error":"Not found"}
downloads/point/last-week/this-package-does-not-exist-pg9
                                                     → 404 {"error":"package … not found"}
```

21 and 60 bytes. Every node sees the same 404, so "this package does not exist"
is a **deterministic** observation and can safely refuse the request with a
refund. Per the rule inherited from TokenScope, a 5xx or an unparseable body is
*not* that — it is node-dependent and must fail the whole request rather than
degrade into a low score.

A real-but-obscure package returns 200 with a real number
(`flatmap-stream` → 197), so a 404 on downloads never happens for a package whose
packument resolved. It is handled anyway, as bucket 0 with `src_dl=0` recorded in
the vector.

## 8. Scoped packages need no encoding

```
registry.npmjs.org/@babel/core    → 200, 788,273 bytes
registry.npmjs.org/@babel%2Fcore  → 200, 788,273 bytes   (identical)
api.npmjs.org/downloads/point/last-week/@babel/core → 200, 87 bytes
```

Both URL forms return byte-identical bodies, so the contract can pass a scoped
name through unencoded after validating it against npm's name grammar.

**Case is significant and must not be normalised.** `registry.npmjs.org/JSONStream`
returns 93,357 bytes and `registry.npmjs.org/jsonstream` returns 7,291 — they are
two *different packages*, both live. npm has rejected new mixed-case names since
2017, but the legacy ones still resolve. Lower-casing the key to make it
canonical would therefore have silently scored the wrong package. PackageGuard
stores and fetches the name exactly as given, and `JSONStream` and `jsonstream`
are two independent feeds.

## 9. Clock handling

`lodash` and `typescript` were both republished on the probe date, giving
`modified` timestamps *ahead of* a midnight-anchored reference instant and a
negative day count. Days-since is therefore clamped at 0 in the contract, and
`now` is captured once before the consensus block and passed into the task — two
validators seconds apart must not straddle a day boundary and disagree about a
package neither of them read differently.

---

*Sections 10 and 11 were found while writing the extraction code against these
documents, not during the on-chain probe run. They are read from the packuments
in `test/fixtures.json`, which `tools/make_fixtures.py` pulls from the same
registry the probe reached, and each one changed the contract.*

## 10. `readme` is not a documentation signal

The obvious fourth metadata term — does the package ship a README — cannot be
read from the packument:

| package | top-level `readme` |
|---|---|
| **express** | **0 bytes** |
| **event-stream** | **0 bytes** |
| esbuild | 175 bytes |
| flatmap-stream | 328 bytes |
| left-pad | 871 bytes |
| is-odd | 3,494 bytes |
| chalk | 13,885 bytes |
| node-sass | 25,897 bytes |

express is about as well documented as an npm package gets, and its packument
carries an empty string. npm does not populate the field consistently — it holds
whatever the last publish happened to embed. Scoring it would have taken a
metadata point off two of the healthiest packages in the corpus for a field the
registry simply declined to send.

So `meta` counts **description, keywords and homepage** — the three the rubric
names — and `readme` is not consulted. `TestExtraction.test_readme_is_not_
consulted` pins the finding so nobody adds it back.

## 11. `time.modified` is not the last publish

This one changed a score by two full rungs. `modified` moves on **any** metadata
edit — a deprecation, a maintainer change, a dist-tag retag — not only on a
publish:

| package | `time.modified` | newest version stamp | gap |
|---|---|---|---|
| express | 15 days | 111 days (4.22.2) | 96 days |
| node-sass | 767 days | 1,199 days | 432 days |
| **left-pad** | **867 days** | **3,066 days** | **6 years** |
| **event-stream** | **1,392 days** | **2,893 days** | **4 years** |

left-pad's `modified` is the day somebody **deprecated** it. Reading that as
"maintained 2 years ago" rather than "last shipped code 8 years ago" would have
moved it two rungs up the staleness ladder — for an edit that is itself an
admission of abandonment. event-stream's is the same story: its last real
publish was 4.0.1 in September 2018, and the 2022 date is metadata housekeeping.

The rubric asks for *days since last publish*, so the contract counts publishes:
the newest per-version stamp wins, and `created`/`modified` are only a fallback
for a packument that omits them. A side effect is that a forged summary cannot
make a dead package look fresh —
`TestExtraction.test_a_forged_summary_cannot_make_a_dead_package_look_fresh`
sets `modified` to today and the staleness rung does not move.
