# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import typing
ERR = "[EXPECTED]"
DEFAULT_MIN_SCORE = 50
DEFAULT_MAX_AGE = 604800
DEFAULT_BANNED = "INSTALL_SCRIPTS,DEPRECATED,NO_LICENSE"
MAX_DEPENDENCIES = 200
MAX_LOG = 100
MAX_BATCH = 20
NAME_CHARS = ("abcdefghijklmnopqrstuvwxyz"
              "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
              "0123456789-._")
MAX_NAME = 214
def _flat(s: str) -> str:
 return " ".join(str(s).split())
def _short(s: str, n: int = 120) -> str:
 s = str(s)
 return s[:n] if len(s) > n else s
def _clamp_bar(value: typing.Any) -> int:
 try:
  n = int(value)
 except (TypeError, ValueError):
  return DEFAULT_MIN_SCORE
 if n < 0:
  return 0
 if n > 100:
  return 100
 return n
def _norm_package(raw: str) -> str:
 name = _flat(raw)
 if name == "":
  raise gl.vm.UserError(ERR + " package name is empty")
 if len(name) > MAX_NAME:
  raise gl.vm.UserError(ERR + " package name is too long")
 body = name
 if name[0] == "@":
  slash = name.find("/")
  if slash < 2 or slash == len(name) - 1:
   raise gl.vm.UserError(ERR + " scoped name must be @scope/name")
  scope = name[1:slash]
  body = name[slash + 1:]
  if body.find("/") >= 0:
   raise gl.vm.UserError(ERR + " scoped name has more than one /")
  for ch in scope:
   if ch not in NAME_CHARS:
    raise gl.vm.UserError(ERR + " illegal character in scope")
  if scope[0] == "." or scope[0] == "_":
   raise gl.vm.UserError(ERR + " scope may not start with . or _")
 elif name.find("/") >= 0:
  raise gl.vm.UserError(ERR + " unscoped name may not contain /")
 if body == "":
  raise gl.vm.UserError(ERR + " package name is empty")
 for ch in body:
  if ch not in NAME_CHARS:
   raise gl.vm.UserError(ERR + " illegal character in package name")
 if body[0] == "." or body[0] == "_":
  raise gl.vm.UserError(ERR + " package name may not start with . or _")
 return name
def _split_flags(text: str) -> list:
 out = []
 for part in str(text).split(","):
  token = _flat(part).upper()
  if token != "" and token not in out:
   out.append(token)
 return out
def _verdict(overall: int, bar: int, flags: list) -> str:
 if len(flags) > 0:
  return "BLOCK"
 return "ALLOW" if int(overall) >= int(bar) else "BLOCK"
@gl.contract_interface
class IPackageGuard:
 class View:
  def get_risk(self, package_name: str) -> typing.Any: ...
  def is_safe(self, package_name: str, min_score: int) -> bool: ...
  def require_safe(self, package_name: str,
  min_score: int) -> typing.Any: ...
  def get_stats(self) -> typing.Any: ...
  def get_config(self) -> typing.Any: ...
 class Write:
  pass
@allow_storage
@dataclass
class Dependency:
 package: str
 version: str
 added_by: Address
 overall: u32
 risk_level: str
 badge: str
 flags: str
 score_id: u32
 content_hash: str
 added_at: u64
class PackageConsumer(gl.Contract):
 owner: Address
 oracle: Address
 min_score: u32
 max_age_seconds: u64
 banned_flags: str
 frozen: bool
 deps: DynArray[Dependency]
 present: TreeMap[str, bool]
 blocked_count: u32
 log: DynArray[str]
 def __init__(self, oracle_address: str):
  self.owner = gl.message.sender_address
  self.oracle = Address(str(oracle_address))
  self.min_score = u32(DEFAULT_MIN_SCORE)
  self.max_age_seconds = u64(DEFAULT_MAX_AGE)
  self.banned_flags = DEFAULT_BANNED
  self.frozen = False
  self.blocked_count = u32(0)
 def _now(self) -> int:
  return int(datetime.now(timezone.utc).timestamp())
 def _only_owner(self) -> None:
  if gl.message.sender_address != self.owner:
   raise gl.vm.UserError(ERR + " owner only")
 def _require_unfrozen(self) -> None:
  if self.frozen:
   raise gl.vm.UserError(ERR + " contract is frozen")
 def _oracle(self) -> typing.Any:
  return IPackageGuard(self.oracle)
 def _note(self, action: str, detail: str) -> None:
  if len(self.log) >= MAX_LOG:
   return
  self.log.append(str(self._now()) + " " + action + " " + _short(detail))
 def _banned_hits(self, flags: typing.Any) -> list:
  banned = _split_flags(str(self.banned_flags))
  got = []
  if isinstance(flags, list):
   for item in flags:
    token = _flat(str(item)).upper()
    if token in banned and token not in got:
     got.append(token)
  return got
 def _row(self, item: Dependency) -> dict:
  return {
  "package": str(item.package),
  "version": str(item.version),
  "overall_score": int(item.overall),
  "risk_level": str(item.risk_level),
  "badge": str(item.badge),
  "flags": [x for x in str(item.flags).split(",") if x],
  "score_id": int(item.score_id),
  "content_hash": str(item.content_hash),
  "added_by": str(item.added_by.as_hex),
  "added_at": int(item.added_at),
  }
 def _find(self, name: str) -> int:
  for i in range(len(self.deps)):
   if str(self.deps[i].package) == name:
    return i
  return -1
 def _assess(self, name: str, now: int) -> dict:
  bar = int(self.min_score)
  try:
   rec = self._oracle().view().get_risk(name)
  except Exception as e:
   return {"package": name, "allowed": False, "verdict": "BLOCK",
   "oracle_error": True,
   "reason": "oracle unreachable: " + _short(str(e), 90),
   "risk_level": "UNKNOWN", "badge": "UNSCANNED",
   "min_score": bar}
  if not isinstance(rec, dict):
   return {"package": name, "allowed": False, "verdict": "BLOCK",
   "oracle_error": True,
   "reason": "oracle returned an unexpected shape",
   "risk_level": "UNKNOWN", "badge": "UNSCANNED",
   "min_score": bar}
  if not rec.get("found"):
   return {"package": name, "allowed": False, "verdict": "BLOCK",
   "oracle_error": False,
   "reason": "never scanned; call PackageGuard.request_scan",
   "risk_level": "UNKNOWN", "badge": "UNSCANNED",
   "min_score": bar}
  overall = int(rec.get("overall_score") or 0)
  flags = rec.get("risk_flags")
  hits = self._banned_hits(flags)
  age = now - int(rec.get("scanned_at") or 0)
  stale = age > int(self.max_age_seconds)
  verdict = _verdict(overall, bar, hits)
  if stale:
   verdict = "BLOCK"
  reason = "clears the bar"
  if len(hits) > 0:
   reason = "carries banned flag(s): " + ",".join(hits)
  elif overall < bar:
   reason = ("scores " + str(overall) + ", policy requires "
   + str(bar))
  if stale:
   reason = ("score is " + str(age) + "s old, policy allows "
   + str(int(self.max_age_seconds)) + "s")
  return {
  "package": name,
  "allowed": verdict == "ALLOW",
  "verdict": verdict,
  "oracle_error": False,
  "reason": reason,
  "overall_score": overall,
  "risk_level": str(rec.get("risk_level") or "UNKNOWN"),
  "badge": str(rec.get("badge") or ""),
  "version": str(rec.get("latest_version") or ""),
  "flags": flags if isinstance(flags, list) else [],
  "banned_hits": hits,
  "score_id": int(rec.get("score_id") or 0),
  "content_hash": str(rec.get("content_hash") or ""),
  "score_age_seconds": age,
  "min_score": bar,
  }
 @gl.public.write
 def add_dependency(self, package_name: str) -> typing.Any:
  self._require_unfrozen()
  name = _norm_package(package_name)
  if len(self.deps) >= MAX_DEPENDENCIES and self._find(name) < 0:
   raise gl.vm.UserError(ERR + " manifest is full")
  now = self._now()
  got = self._assess(name, now)
  if got.get("oracle_error"):
   raise gl.vm.UserError(
   ERR + " " + _short(str(got.get("reason")), 160))
  if not got.get("allowed"):
   self.blocked_count = u32(int(self.blocked_count) + 1)
   self._note("blocked", name + " " + str(got.get("reason")))
   return {
   "ok": False,
   "status": "BLOCKED",
   "package": name,
   "verdict": "BLOCK",
   "reason": "blocked by policy",
   "detail": str(got.get("reason")),
   "overall_score": int(got.get("overall_score") or 0),
   "min_score": int(self.min_score),
   "blocked_attempts": int(self.blocked_count),
   "manifest_size": len(self.deps),
   }
  rec = self._oracle().view().require_safe(name, int(self.min_score))
  if not isinstance(rec, dict):
   raise gl.vm.UserError(ERR + " oracle returned an unexpected shape")
  flags = rec.get("risk_flags")
  flat = ",".join([_flat(str(x)).upper()
  for x in (flags if isinstance(flags, list) else [])])
  idx = self._find(name)
  item = self.deps[idx] if idx >= 0 else self.deps.append_new_get()
  item.package = name
  item.version = _short(str(rec.get("latest_version") or ""), 64)
  item.added_by = gl.message.sender_address
  item.overall = u32(int(rec.get("overall_score") or 0))
  item.risk_level = _short(str(rec.get("risk_level") or ""), 16)
  item.badge = _short(str(rec.get("badge") or ""), 16)
  item.flags = _short(flat, 240)
  item.score_id = u32(int(rec.get("score_id") or 0))
  item.content_hash = _short(str(rec.get("content_hash") or ""), 40)
  item.added_at = u64(now)
  self.present[name] = True
  self._note("add", name + " " + str(int(item.overall)))
  return {"ok": True, "status": "OK", "added": self._row(item),
  "manifest_size": len(self.deps)}
 @gl.public.write
 def remove_dependency(self, package_name: str) -> typing.Any:
  self._require_unfrozen()
  name = _norm_package(package_name)
  idx = self._find(name)
  if idx < 0:
   raise gl.vm.UserError(ERR + " not in the manifest")
  last = len(self.deps) - 1
  if idx != last:
   src = self.deps[last]
   dst = self.deps[idx]
   dst.package = str(src.package)
   dst.version = str(src.version)
   dst.added_by = src.added_by
   dst.overall = u32(int(src.overall))
   dst.risk_level = str(src.risk_level)
   dst.badge = str(src.badge)
   dst.flags = str(src.flags)
   dst.score_id = u32(int(src.score_id))
   dst.content_hash = str(src.content_hash)
   dst.added_at = u64(int(src.added_at))
  self.deps.pop()
  del self.present[name]
  self._note("remove", name)
  return {"ok": True, "status": "OK", "removed": name,
  "manifest_size": len(self.deps)}
 @gl.public.view
 def check_risk(self, package_name: str) -> typing.Any:
  try:
   name = _norm_package(package_name)
  except gl.vm.UserError as e:
   msg = getattr(e, "message", "")
   return {"package": _short(str(package_name), 214),
   "risk_level": "UNKNOWN", "allowed": False,
   "reason": _short(str(msg) if msg else str(e), 160)}
  got = self._assess(name, self._now())
  return {
  "package": name,
  "risk_level": got["risk_level"],
  "badge": got.get("badge", ""),
  "overall_score": got.get("overall_score", 0),
  "allowed": got["allowed"],
  "reason": got["reason"],
  "flags": got.get("flags", []),
  }
 @gl.public.view
 def preview_dependency(self, package_name: str) -> typing.Any:
  try:
   name = _norm_package(package_name)
  except gl.vm.UserError as e:
   msg = getattr(e, "message", "")
   return {"package": _short(str(package_name), 214),
   "allowed": False, "verdict": "BLOCK",
   "reason": _short(str(msg) if msg else str(e), 160)}
  return self._assess(name, self._now())
 @gl.public.view
 def gate_build(self, package_names: list) -> typing.Any:
  now = self._now()
  rows = []
  failed = []
  for raw in list(package_names)[:MAX_BATCH]:
   try:
    name = _norm_package(str(raw))
   except gl.vm.UserError as e:
    msg = getattr(e, "message", "")
    rows.append({"package": _short(str(raw), 214),
    "allowed": False, "verdict": "BLOCK",
    "reason": _short(str(msg) if msg else str(e), 160),
    "risk_level": "UNKNOWN"})
    failed.append(_short(str(raw), 60))
    continue
   got = self._assess(name, now)
   rows.append(got)
   if not got["allowed"]:
    failed.append(name)
  return {
  "build": "FAIL" if len(failed) > 0 else "PASS",
  "checked": len(rows),
  "blocked": failed,
  "policy": {"min_score": int(self.min_score),
  "banned_flags": _split_flags(str(self.banned_flags)),
  "max_age_seconds": int(self.max_age_seconds)},
  "results": rows,
  }
 @gl.public.view
 def get_manifest(self) -> typing.Any:
  rows = []
  for i in range(len(self.deps)):
   rows.append(self._row(self.deps[i]))
  rows.sort(key=lambda r: (-r["overall_score"], r["package"]))
  return {"count": len(rows), "capacity": MAX_DEPENDENCIES,
  "frozen": bool(self.frozen), "dependencies": rows}
 @gl.public.view
 def has_dependency(self, package_name: str) -> bool:
  try:
   return bool(self.present.get(_norm_package(package_name)) or False)
  except gl.vm.UserError:
   return False
 @gl.public.view
 def get_policy(self) -> typing.Any:
  return {
  "oracle": str(self.oracle.as_hex),
  "owner": str(self.owner.as_hex),
  "min_score": int(self.min_score),
  "banned_flags": _split_flags(str(self.banned_flags)),
  "max_age_seconds": int(self.max_age_seconds),
  "frozen": bool(self.frozen),
  "manifest_size": len(self.deps),
  "capacity": MAX_DEPENDENCIES,
  "blocked_attempts": int(self.blocked_count),
  "scenario": "CI pipeline rejects packages scoring below "
  + str(int(self.min_score)),
  }
 @gl.public.view
 def get_oracle_stats(self) -> typing.Any:
  try:
   return self._oracle().view().get_stats()
  except Exception as e:
   return {"error": "oracle unreachable: " + _short(str(e), 120)}
 @gl.public.view
 def get_log(self, count: int) -> typing.Any:
  n = int(count)
  total = len(self.log)
  if n <= 0 or n > total:
   n = total
  out = []
  for i in range(total - n, total):
   out.append(str(self.log[i]))
  return {"total": total, "entries": out}
 @gl.public.write
 def set_policy(self, min_score: int, banned_flags: str,
 max_age_seconds: int) -> typing.Any:
  self._only_owner()
  self._require_unfrozen()
  bar = _clamp_bar(min_score)
  age = int(max_age_seconds)
  if age < 60:
   raise gl.vm.UserError(ERR + " max_age_seconds must be at least 60")
  self.min_score = u32(bar)
  self.banned_flags = ",".join(_split_flags(banned_flags))
  self.max_age_seconds = u64(age)
  self._note("policy", str(bar) + " " + str(self.banned_flags))
  return self.get_policy()
 @gl.public.write
 def set_oracle(self, new_oracle: str) -> typing.Any:
  self._only_owner()
  self._require_unfrozen()
  self.oracle = Address(str(new_oracle))
  self._note("set_oracle", str(self.oracle.as_hex))
  return {"ok": True, "status": "OK", "oracle": str(self.oracle.as_hex)}
 @gl.public.write
 def freeze(self) -> typing.Any:
  self._only_owner()
  self._require_unfrozen()
  self.frozen = True
  self._note("freeze", "every public write is now refused")
  return {"ok": True, "status": "OK", "frozen": True}
 @gl.public.write
 def transfer_ownership(self, new_owner: str) -> typing.Any:
  self._only_owner()
  self._require_unfrozen()
  addr = Address(str(new_owner))
  if addr == Address("0x" + "0" * 40):
   raise gl.vm.UserError(ERR + " owner cannot be the zero address")
  self.owner = addr
  self._note("transfer_ownership", str(addr.as_hex))
  return {"ok": True, "status": "OK", "owner": str(addr.as_hex)}
