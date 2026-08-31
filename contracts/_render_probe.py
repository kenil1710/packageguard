# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

# Throwaway diagnostic, not part of PackageGuard. It answers the questions that
# decide the whole project before a line of extraction is written:
#
#   1. Does validator egress reach registry.npmjs.org and api.npmjs.org at all?
#   2. What is the BODY SIZE CEILING? An npm packument is not a small document:
#      left-pad is 22 KB, event-stream 120 KB, express 805 KB, react 6.9 MB
#      (measured off-chain 2026-08-31). The packument is the only source of
#      `time.created` / `time.modified`, so whether a validator can hold one
#      decides whether maturity and maintenance can be scored from it or have
#      to be assembled from the small endpoints instead.
#   3. Do the small endpoints answer, and with what shape?
#        /{pkg}/latest                        ~3.5 KB  deps, license, scripts
#        downloads/point/last-week/{pkg}        83 B   weekly downloads
#        /-/v1/search?text={pkg}&size=1        ~1.1 KB last publish date
#        api.npmjs.org/versions/{pkg}/last-week ~4 KB  version count
#   4. Are custom request headers available? `Accept: application/vnd.npm
#      .install-v1+json` returns an abbreviated packument (express 339 KB
#      instead of 805 KB) but drops `time` entirely, so it only helps if the
#      full document turns out to be unfetchable.
#
# Every extraction rule in PackageGuard is written against the bodies this
# captures, never against assumptions about the registry's schema.
#
# Line 1 must stay the runner pin: a comment above it makes the contract
# undeployable and the only error reported is `invalid_contract`.

from genlayer import *

import json


def _status(res) -> int:
    s = getattr(res, "status_code", None)
    if s is None:
        s = getattr(res, "status", None)
    if s is None:
        return 0
    return int(s)


def _body(res) -> str:
    b = getattr(res, "body", None)
    if b is None:
        b = getattr(res, "text", None)
    if b is None:
        return ""
    if isinstance(b, bytes):
        return b.decode("utf-8", errors="ignore")
    return str(b)


def _fetch(url: str) -> tuple:
    """(status, body). Tries web.request first and falls back to web.get:
    AuditCourt used `gl.nondet.web.get`, SocialOracle used
    `gl.nondet.web.request`, and the probe should not die on which one this
    runner build exposes."""
    try:
        res = gl.nondet.web.request(url, method="GET")
    except AttributeError:
        res = gl.nondet.web.get(url)
    return _status(res), _body(res)


def _describe(d) -> dict:
    out = {}
    if not isinstance(d, dict):
        return {"_type": type(d).__name__}
    for k in sorted(d.keys()):
        v = d[k]
        if isinstance(v, dict):
            out[str(k)] = "dict{" + ",".join(
                sorted([str(x) for x in v.keys()])[:14]) + "}"
        elif isinstance(v, list):
            out[str(k)] = "list[" + str(len(v)) + "]"
        else:
            out[str(k)] = str(type(v).__name__) + "=" + str(v)[:90]
    return out


class RenderProbe(gl.Contract):
    url: str
    text: str
    text_len: u32
    statuses: str

    def __init__(self):
        self.url = ""
        self.text = ""
        self.text_len = u32(0)
        self.statuses = ""

    @gl.public.write
    def probe_statuses(self, urls: list) -> None:
        """HTTP status + body length for each plain GET, one transaction.

        Distinguishes 'blocked' from 'empty' from 'too large' - a 403 is an
        egress block, a 200 with a 40-byte body is an endpoint that exists but
        says nothing, and a status of -1 with an exception string is a body the
        runner would not carry. They call for different pivots."""
        targets = [str(u) for u in urls][:10]

        def leader_fn() -> dict:
            found = {}
            for u in targets:
                try:
                    st, body = _fetch(u)
                    found[u] = {"status": st, "len": len(body),
                                "head": body[:120]}
                except Exception as e:
                    found[u] = {"status": -1, "len": -1, "err": str(e)[:200]}
            return found

        def validator_fn(leader_result: gl.vm.Result) -> bool:
            # Shape only. A validator that re-fetched would disagree on every
            # live download count and the probe would never commit - which is
            # the whole reason PackageGuard itself agrees on buckets, not bytes.
            return isinstance(leader_result, gl.vm.Return)

        self.statuses = json.dumps(gl.vm.run_nondet(leader_fn, validator_fn))

    @gl.public.write
    def probe_get(self, url: str, start: int, count: int) -> None:
        """Raw GET, no browser, keeping a window of the body."""
        begin = int(start)
        span = int(count)
        if span <= 0 or span > 12000:
            span = 12000

        def leader_fn() -> dict:
            st, body = _fetch(url)
            return {"len": len(body), "status": st,
                    "window": body[begin:begin + span]}

        def validator_fn(leader_result: gl.vm.Result) -> bool:
            return isinstance(leader_result, gl.vm.Return)

        out = gl.vm.run_nondet(leader_fn, validator_fn)
        self.url = str(url) + " [status " + str(out["status"]) + "]"
        self.text_len = u32(int(out["len"]))
        self.text = str(out["window"])

    @gl.public.write
    def probe_keys(self, url: str) -> None:
        """The document's SHAPE rather than its bytes: top-level keys with the
        type and a short sample of each, and the same for the first element of
        whichever list the payload carries.

        This is what actually gets written against. An 805 KB packument shown
        200 characters at a time takes a dozen transactions to understand; its
        key list takes one."""

        def leader_fn() -> dict:
            st, body = _fetch(url)
            try:
                doc = json.loads(body)
            except ValueError:
                return {"status": st, "len": len(body),
                        "err": "unparseable", "head": body[:400]}
            info = {"status": st, "len": len(body)}
            if isinstance(doc, dict):
                info["top"] = _describe(doc)
                for lk in ("objects", "items", "downloads", "result"):
                    rows = doc.get(lk)
                    if isinstance(rows, list) and len(rows) > 0:
                        info["list_key"] = lk
                        info["list_len"] = len(rows)
                        info["item0"] = _describe(rows[0])
                        break
            elif isinstance(doc, list):
                info["top"] = "list[" + str(len(doc)) + "]"
                if len(doc) > 0:
                    info["item0"] = _describe(doc[0])
            return info

        def validator_fn(leader_result: gl.vm.Result) -> bool:
            return isinstance(leader_result, gl.vm.Return)

        self.statuses = json.dumps(gl.vm.run_nondet(leader_fn, validator_fn))

    @gl.public.write
    def probe_packument(self, pkg: str) -> None:
        """The load-bearing test: can a validator hold a WHOLE packument, parse
        it, and reach the fields the rubric needs?

        Reports only derived facts, never the document, so the answer is
        readable in one view call. If this succeeds for express (805 KB) the
        packument can be PackageGuard's primary source; if it succeeds for
        left-pad but not express, scoring has to be assembled from the small
        endpoints and `time.created` is unavailable, which reshapes the
        maturity dimension."""
        name = str(pkg)

        def leader_fn() -> dict:
            st, body = _fetch("https://registry.npmjs.org/" + name)
            out = {"status": st, "len": len(body)}
            try:
                doc = json.loads(body)
            except ValueError:
                out["err"] = "unparseable"
                out["head"] = body[:300]
                return out
            if not isinstance(doc, dict):
                out["err"] = "not an object"
                return out
            out["top_keys"] = sorted([str(k) for k in doc.keys()])
            tm = doc.get("time")
            if isinstance(tm, dict):
                out["time_entries"] = len(tm)
                out["created"] = str(tm.get("created"))
                out["modified"] = str(tm.get("modified"))
            vs = doc.get("versions")
            if isinstance(vs, dict):
                out["n_versions"] = len(vs)
            tags = doc.get("dist-tags")
            latest = ""
            if isinstance(tags, dict):
                out["dist_tags"] = sorted([str(k) for k in tags.keys()])[:8]
                latest = str(tags.get("latest", ""))
            out["latest"] = latest
            out["license"] = str(doc.get("license"))[:60]
            out["has_description"] = bool(doc.get("description"))
            kw = doc.get("keywords")
            out["n_keywords"] = len(kw) if isinstance(kw, list) else -1
            mt = doc.get("maintainers")
            out["n_maintainers"] = len(mt) if isinstance(mt, list) else -1
            out["has_homepage"] = bool(doc.get("homepage"))
            out["has_repository"] = bool(doc.get("repository"))
            if isinstance(vs, dict) and latest in vs:
                man = vs[latest]
                out["latest_keys"] = sorted([str(k) for k in man.keys()])
                dep = man.get("dependencies")
                out["n_deps"] = len(dep) if isinstance(dep, dict) else 0
                sc = man.get("scripts")
                out["scripts"] = sorted(
                    [str(k) for k in sc.keys()]) if isinstance(sc, dict) else []
                out["deprecated"] = str(man.get("deprecated"))[:120]
                dist = man.get("dist")
                if isinstance(dist, dict):
                    out["dist_keys"] = sorted([str(k) for k in dist.keys()])
                    out["unpackedSize"] = dist.get("unpackedSize")
                    out["fileCount"] = dist.get("fileCount")
            return out

        def validator_fn(leader_result: gl.vm.Result) -> bool:
            return isinstance(leader_result, gl.vm.Return)

        self.statuses = json.dumps(gl.vm.run_nondet(leader_fn, validator_fn))

    @gl.public.write
    def probe_headers(self, url: str, accept: str) -> None:
        """Are custom request headers available on this runner? The abbreviated
        packument (`Accept: application/vnd.npm.install-v1+json`) is 2.4x
        smaller, so this decides whether an oversize-packument fallback exists
        at all."""
        hdr = {"Accept": str(accept)}
        target = str(url)

        def leader_fn() -> dict:
            attempts = {}
            try:
                r = gl.nondet.web.request(target, method="GET", headers=hdr)
                attempts["headers_kwarg"] = {"status": _status(r),
                                             "len": len(_body(r))}
            except Exception as e:
                attempts["headers_kwarg"] = {"err": str(e)[:220]}
            try:
                st, body = _fetch(target)
                attempts["plain"] = {"status": st, "len": len(body)}
            except Exception as e:
                attempts["plain"] = {"err": str(e)[:220]}
            return attempts

        def validator_fn(leader_result: gl.vm.Result) -> bool:
            return isinstance(leader_result, gl.vm.Return)

        self.statuses = json.dumps(gl.vm.run_nondet(leader_fn, validator_fn))

    @gl.public.view
    def get_len(self) -> int:
        return int(self.text_len)

    @gl.public.view
    def get_window(self) -> str:
        return str(self.text)

    @gl.public.view
    def get_slice(self, start: int, count: int) -> str:
        s = str(self.text)
        a = int(start)
        n = int(count)
        if a < 0:
            a = 0
        if n <= 0 or n > 4000:
            n = 4000
        return s[a:a + n]

    @gl.public.view
    def get_statuses(self) -> str:
        return str(self.statuses)
