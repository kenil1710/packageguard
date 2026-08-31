#!/usr/bin/env python3
"""Rebuild test/fixtures.json from the live npm registry.

    python3 tools/make_fixtures.py

The offline suite runs against REAL packuments, not invented ones - a fixture an
author makes up is a fixture that agrees with whatever the author already
believed. Two reductions are applied, both lossless for what the contract reads:

  * every version manifest except `dist-tags.latest` becomes `{}`. The contract
    reads manifests only for the latest version; the others exist so that
    `len(versions)` and the distinct-major count stay exact.
  * `users` (npm stars) becomes an integer `_users`, which the test loader
    expands back into a dict of that size. The contract only takes `len()` of it,
    and express alone carries 2,649 usernames that mean nothing to the tests.

Everything else - `time` in full, the latest manifest in full, maintainers,
licence, description, keywords, homepage, repository - is byte-for-byte what the
registry served.
"""

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Chosen to span the rubric, not to flatter it: a healthy package, a deprecated
# one that is still popular, the 2018 compromise, the payload it shipped, an
# install-hook package, a package that is deprecated AND runs install scripts, a
# trivial package, and a well-kept small one.
PACKAGES = ("express", "left-pad", "event-stream", "flatmap-stream",
            "esbuild", "node-sass", "is-odd", "chalk")


def fetch(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r:
        return json.loads(r.read())


def trim(doc: dict) -> dict:
    latest = (doc.get("dist-tags") or {}).get("latest", "")
    versions = {}
    for name in doc.get("versions") or {}:
        versions[name] = doc["versions"][name] if name == latest else {}
    return {
        "name": doc.get("name"),
        "dist-tags": doc.get("dist-tags"),
        "time": doc.get("time"),
        "versions": versions,
        "maintainers": doc.get("maintainers"),
        "license": doc.get("license"),
        "description": doc.get("description"),
        "keywords": doc.get("keywords"),
        "homepage": doc.get("homepage"),
        "repository": doc.get("repository"),
        "_users": len(doc.get("users") or {}),
        "readme": (doc.get("readme") or "")[:400],
    }


def main() -> int:
    out = {}
    for pkg in PACKAGES:
        doc = fetch("https://registry.npmjs.org/" + pkg)
        out[pkg] = trim(doc)
        dl = fetch("https://api.npmjs.org/downloads/point/last-week/" + pkg)
        out[pkg]["_weekly_downloads"] = int(dl.get("downloads") or 0)
        print(pkg, len(out[pkg]["versions"]), "versions,",
              len(out[pkg]["time"]), "time entries,",
              out[pkg]["_users"], "stars,",
              out[pkg]["_weekly_downloads"], "weekly")
    target = ROOT / "test" / "fixtures.json"
    target.write_text(json.dumps(out, separators=(",", ":"), sort_keys=True),
                      encoding="utf8")
    print("wrote", target, target.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
