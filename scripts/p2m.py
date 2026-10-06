#!/usr/bin/env python3
"""prove2me-autoprover helper: Prove2me API client, claim selection, local gates.

The agent drives everything through this script so that
  * the API key never has to appear in the agent's context or in logs,
  * the "only submit what compiles, sorry-free, standard axioms" rule is
    enforced in code rather than left to the prompt,
  * dry-run mode and the per-run submission cap cannot be bypassed by the agent.

Standard library only. Run `python3 scripts/p2m.py -h` for the commands.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API = "https://prove2.me/api/v1"
REPO = Path(__file__).resolve().parent.parent
# The user's private data repo: autoprover.config.json + logs/. In a routine run
# it is the cloned repo (the current directory); the tool itself lives elsewhere.
DATA = Path(os.environ.get("AUTOPROVER_DATA")
            or (Path.cwd() if (Path.cwd() / "autoprover.config.json").exists() else REPO))
CONFIG_PATH = Path(os.environ.get("AUTOPROVER_CONFIG", DATA / "autoprover.config.json"))
WS = Path(os.environ.get("PROVE2ME_WORKSPACE", Path.home() / "prove2me_workspace"))
CREDS = Path(os.environ.get("PROVE2ME_CREDENTIALS_FILE", WS / "credentials.json"))
STATE = Path(os.environ.get("AUTOPROVER_STATE", Path.home() / ".autoprover-state"))  # per-run scratch
LOGS = DATA / "logs"  # run logs, committed to the data repo
SOURCE_URL = os.environ.get("AUTOPROVER_SOURCE_URL", "https://github.com/sattath/prove2me-autoprover")
MIRRORS = STATE / "mirrored_modules.json"  # module -> platform id/name/status

# Axioms Lean/Mathlib proofs normally rely on. Anything else (sorryAx,
# Lean.ofReduceBool from native_decide, a user `axiom`) blocks submission.
STANDARD_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
IMPORT_LINE = re.compile(r"^\s*(?:(?:public|private|meta)\s+)*import\s+([^\n]+)", re.M)  # also `public import`
MAX_MIRRORED_MODULES = 80

DEFAULT_CONFIG = {
    "weekly_reset": {"day": "thursday", "time": "10:00", "timezone": "UTC"},
    "lead_hours": [10, 5],
    "dry_run": True,
    "max_claims_per_run": 3,
    "max_submissions_per_run": 3,
    "minutes_per_claim": 40,
    "allow_disproofs": True,
    "allow_sketches": True,
    "build_timeout_minutes": 20,
    "selection": {
        "sources": ["saved", "missions", "search"],
        "mission_ids": [],
        "tags": [],
        "query": "",
        "sort": "votes",
        "max_statement_chars": 1500,
        "skip_flagged": True,
        "skip_attempted_by_me": True,
        "pool_size": 15,
    },
}


# ---------------------------------------------------------------- utilities

def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text())
        sel = user.pop("selection", {})
        cfg.update(user)
        cfg["selection"].update(sel)
    # Environment overrides, used by the GitHub Actions workflow inputs.
    if os.environ.get("AUTOPROVER_DRY_RUN"):
        cfg["dry_run"] = os.environ["AUTOPROVER_DRY_RUN"].lower() in ("1", "true", "yes")
    for key in ("max_claims_per_run", "max_submissions_per_run"):
        var = "AUTOPROVER_" + key.upper()
        env = os.environ.get(var, "").strip()
        if env:
            try:
                cfg[key] = int(env)
            except ValueError:
                die(f"environment variable {var} must be a whole number, got {env!r}")
            if cfg[key] < 0:
                die(f"environment variable {var} must not be negative, got {env!r}")
    return cfg


def platform_imports(src: str) -> list[str]:
    return [m for line in IMPORT_LINE.findall(src) for m in line.split()
            if m.startswith(("Theorems.", "Definitions."))]


def slug(name: str) -> str:
    return name.replace(".", "_")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id() -> str:
    """One id per run, shared by all commands in that run."""
    STATE.mkdir(parents=True, exist_ok=True)
    f = STATE / "run_id"
    if not f.exists():
        f.write_text(dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S"))
    return f.read_text().strip()


def ledger_append(event: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    event = {"time": now(), **event}
    with open(STATE / "ledger.jsonl", "a") as fh:
        fh.write(json.dumps(event) + "\n")


def ledger() -> list[dict]:
    f = STATE / "ledger.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


def previously_attempted() -> set[str]:
    """Theorem ids attempted in earlier runs, read from the committed logs."""
    ids: set[str] = set()
    for f in LOGS.glob("*.jsonl"):
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("status") == "DRY_RUN_PASSED_LOCAL_CHECKS":
                continue  # solved but never sent; a live run should still try it
            if e.get("event") in ("result", "submitted") and e.get("theorem_id"):
                ids.add(e["theorem_id"])
    return ids


# ---------------------------------------------------------------- API client

class Api:
    def __init__(self) -> None:
        self.token_file = STATE / "access_token.json"
        self._token: str | None = None

    def _http(self, method: str, path: str, *, json_body=None, form=None, auth=True):
        headers = {"Accept": "application/json"}
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif form is not None:
            boundary = uuid.uuid4().hex
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            data = _multipart(form, boundary)
        if auth:
            headers["Authorization"] = "Bearer " + self.token()
        req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = resp.read()
                return json.loads(body) if body else {}
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")[:500]
                if e.code == 401 and auth and attempt == 0:
                    self._refresh()
                    headers["Authorization"] = "Bearer " + self.token()
                    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
                    continue
                if e.code in (429, 502, 503, 504) and attempt < 3:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {text}") from None
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as e:
                if attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"{method} {path} -> network error: {e}") from None

    def get(self, path: str, **params):
        params = {k: v for k, v in params.items() if v not in (None, "")}
        return self._http("GET", path + ("?" + urllib.parse.urlencode(params) if params else ""))

    def token(self) -> str:
        if self._token:
            return self._token
        if self.token_file.exists():
            t = json.loads(self.token_file.read_text())
            if t.get("expires_at", 0) > time.time() + 300:
                self._token = t["access_token"]
                return self._token
        return self._refresh()

    def _refresh(self) -> str:
        if not CREDS.exists():
            die(f"no Prove2me credentials at {CREDS} (did the setup script run?)")
        key = json.loads(CREDS.read_text()).get("api_key")
        if not key:
            die("credentials.json has no api_key")
        try:
            t = self._http("POST", "/agent/refresh", json_body={"api_key": key}, auth=False)
        except RuntimeError as e:
            if "HTTP 401" in str(e):
                die("Prove2me API key rejected (expired after 30 days?). Mint a new key on "
                    "prove2.me (account menu > API key) and update the PROVE2ME_CREDENTIALS secret.", 3)
            raise
        STATE.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({"access_token": t["access_token"], "expires_at": t["expires_at"],
                                               "version": t.get("version")}))
        self.token_file.chmod(0o600)
        self._token = t["access_token"]
        return self._token

    def platform_version(self) -> str | None:
        self.token()
        return json.loads(self.token_file.read_text()).get("version")


def _multipart(fields: dict, boundary: str) -> bytes:
    out = b""
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        if isinstance(value, tuple):  # (filename, bytes)
            out += f'Content-Disposition: form-data; name="{name}"; filename="{value[0]}"\r\n'.encode()
            out += b"Content-Type: text/plain\r\n\r\n" + value[1] + b"\r\n"
        else:
            out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            out += str(value).encode() + b"\r\n"
    return out + f"--{boundary}--\r\n".encode()


# ---------------------------------------------------------------- commands

def cmd_status(api: Api, cfg: dict, args) -> None:
    """Check credentials, platform version, environment pin. Prints no secrets."""
    me = api.get("/me")
    envs = api.get("/environments")["environments"]
    default = next(e for e in envs if e["is_default"])
    skill = WS / "SKILL.md"
    skill_ver = None
    if skill.exists():
        m = re.search(r'version:\s*"([^"]+)"', skill.read_text())
        skill_ver = m.group(1) if m else None
    local_rev = None
    lake = WS / "lakefile.lean"
    if lake.exists():
        m = re.search(r'"([0-9a-f]{40})"', lake.read_text())
        local_rev = m.group(1) if m else None
    out = {
        "username": me.get("username"),
        "platform_version": api.platform_version(),
        "skill_version": skill_ver,
        "default_env": default,
        "local_mathlib_rev": local_rev,
        "local_env_matches_default": local_rev == default["mathlib_rev"],
        "dry_run": cfg["dry_run"],
        "max_claims_per_run": cfg["max_claims_per_run"],
        "max_submissions_per_run": cfg["max_submissions_per_run"],
        "run_id": run_id(),
    }
    print(json.dumps(out, indent=2))


def cmd_pin_env(api: Api, cfg: dict, args) -> None:
    """Write lean-toolchain + lakefile.lean in the workspace for the default env."""
    envs = api.get("/environments")["environments"]
    env = next(e for e in envs if (e["mathlib_rev"] == args.rev if args.rev else e["is_default"]))
    (WS / "lean-toolchain").write_text(env["toolchain"] + "\n")
    (WS / "lakefile.lean").write_text(f'''import Lake
open Lake DSL

package «prove2me» where
  leanOptions := #[⟨`autoImplicit, false⟩]

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @
  "{env["mathlib_rev"]}"

lean_lib «Definitions» where
  globs := #[.submodules `Definitions]
lean_lib «Theorems» where
  globs := #[.submodules `Theorems]
@[default_target]
lean_lib «Solutions» where
  globs := #[.submodules `Solutions]
lean_lib «AutoproverCheck» where
  globs := #[.submodules `AutoproverCheck]
''')
    print(json.dumps({"toolchain": env["toolchain"], "mathlib_rev": env["mathlib_rev"]}))


def _theorem_rows(api: Api, cfg: dict, env_rev: str) -> list[dict]:
    sel = cfg["selection"]
    rows: list[dict] = []
    seen: set[str] = set()

    def add(r: dict, source: str, extra: dict | None = None) -> None:
        if r["theorem_id"] in seen:
            return
        seen.add(r["theorem_id"])
        rows.append({**r, "_source": source, **(extra or {})})

    for source in sel["sources"]:
        if source == "saved":
            for r in api.get("/saved", status="Open", limit=200)["saved"]:
                add(r, "saved")
        elif source == "missions":
            missions = sel["mission_ids"]
            if not missions:
                continue  # missions are only used when the user names them
            for mid in missions:
                m = api.get(f"/missions/{mid}")
                root = (m.get("main_theorem") or {}).get("theorem_id")
                if not root:
                    continue
                leaves = api.get(f"/theorems/{root}/open-leaves", limit=50)["open_leaves"]
                for leaf in leaves:
                    add({"theorem_id": leaf["theorem_id"], "theorem_name": leaf["theorem_name"]},
                        f"mission:{m.get('name', mid)}", {"closability": leaf.get("closability", 0)})
        elif source == "search":
            res = api.get("/theorems", status="Open", sort=sel["sort"], limit=200, env=env_rev,
                          q=sel["query"], tags=",".join(sel["tags"]))
            for r in res["theorems"]:
                add(r, "search")
    return rows


def cmd_candidates(api: Api, cfg: dict, args) -> None:
    """Print a ranked shortlist of claims to attempt, as JSON."""
    sel = cfg["selection"]
    env_rev = next(e for e in api.get("/environments")["environments"] if e["is_default"])["mathlib_rev"]
    skip = previously_attempted() if sel["skip_attempted_by_me"] else set()
    skip |= {e["theorem_id"] for e in ledger() if e.get("event") == "result"}
    out = []
    for r in _theorem_rows(api, cfg, env_rev):
        if len(out) >= sel["pool_size"]:
            break
        if r["theorem_id"] in skip:
            continue
        if "formal_statement" not in r or "mathlib_rev" not in r:
            r = {**api.get(f"/theorems/{r['theorem_id']}"), **{k: v for k, v in r.items() if k.startswith("_") or k == "closability"}}
        if r.get("status") != "Open" or r.get("deprecated_at") or r.get("mathlib_rev") != env_rev:
            continue
        if len(r.get("formal_statement", "")) > sel["max_statement_chars"]:
            continue
        if sel["skip_flagged"]:
            audits = r.get("audits")
            if audits is None:
                audits = api.get(f"/theorems/{r['theorem_id']}").get("audits", [])
            if any(a.get("decision") == "flag" for a in audits):
                continue
        out.append({
            "theorem_id": r["theorem_id"],
            "theorem_name": r["theorem_name"],
            "title": r.get("theorem_title"),
            "source": r["_source"],
            "closability": r.get("closability"),
            "votes": r.get("vote_count"),
            "statement_chars": len(r.get("formal_statement", "")),
            "platform_imports": len(platform_imports((r.get("preamble") or "") + r.get("formal_statement", ""))),
            "tags": r.get("tags", []),
        })
    print(json.dumps(out, indent=2, ensure_ascii=False))


def _resolve_module(api: Api, module: str, env_rev: str) -> dict:
    """Find the platform theorem/definition behind `Theorems.Thm_x` / `Definitions.Def_x`."""
    kind, name = module.split(".", 1)
    s = name.split("_", 1)[1]  # strip Thm_/Def_
    status = "Definition" if kind == "Definitions" else None
    hits = api.get("/theorems", theorem_name=s, env=env_rev)["theorems"]
    parts = s.split("_")
    for i in range(1, min(len(parts), 5)):  # namespaces come first: A_B_c_d -> A.B.c_d
        if hits:
            break
        guess = ".".join(parts[:i + 1]) + "".join("_" + p for p in parts[i + 1:])
        hits = api.get("/theorems", theorem_name=guess, env=env_rev)["theorems"]
    if not hits:  # theorem names contain dots; the slug replaced them with `_`
        for q in (s.split("_")[-1], s.rsplit("_", 2)[-2] if s.count("_") >= 2 else s):
            res = api.get("/theorems", q=q, env=env_rev, status=status, limit=200)["theorems"]
            hits = [r for r in res if slug(r["theorem_name"]) == s]
            if hits:
                break
    hits = [h for h in hits if (h["status"] == "Definition") == (kind == "Definitions")]
    if not hits:
        raise RuntimeError(f"cannot resolve platform module {module}")
    return hits[0]


def _module_source(row: dict, as_axiom: bool = False) -> str:
    """Lean source for a mirrored platform module.

    Platform theorems are stored as `theorem t ... := by sorry`. With
    `as_axiom`, we mirror them locally as `axiom t ...` instead: they are used
    exactly the same way in a proof, but `#print axioms solution` then names
    each imported lemma, so any `sorryAx` it reports must come from our code.
    """
    if row["status"] == "Definition":
        return row["definition"]
    stmt = row["formal_statement"]
    if as_axiom:
        ax = re.sub(r"^(\s*)(?:theorem|lemma)(\s+)", r"\1axiom\2", stmt, count=1, flags=re.M)
        ax = re.sub(r":=\s*(?:by\s+)?sorry\s*", "\n", ax, count=1)
        if ax != stmt and "sorry" not in ax:
            stmt = ax
    return (row.get("preamble") or "") + "\n\n" + stmt + "\n"


def _mirror(api: Api, modules: list[str], env_rev: str) -> dict[str, dict]:
    """Write every platform module in `modules` (and their imports) into the workspace."""
    todo = list(modules)
    done: dict[str, dict] = {}
    while todo:
        mod = todo.pop()
        if mod in done:
            continue
        if len(done) >= MAX_MIRRORED_MODULES:
            die(f"more than {MAX_MIRRORED_MODULES} platform imports; skip this claim", 4)
        row = _resolve_module(api, mod, env_rev)
        src = _module_source(row, as_axiom=True)
        path = WS / (mod.replace(".", "/") + ".lean")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src)
        done[mod] = {"id": row["theorem_id"], "name": row["theorem_name"], "status": row["status"]}
        todo.extend(platform_imports(src))
    MIRRORS.parent.mkdir(parents=True, exist_ok=True)
    known = json.loads(MIRRORS.read_text()) if MIRRORS.exists() else {}
    known.update(done)
    MIRRORS.write_text(json.dumps(known, indent=1))
    return done


def cmd_fetch(api: Api, cfg: dict, args) -> None:
    """Mirror a target (and every platform module it imports) into the workspace."""
    t = api.get(f"/theorems/{args.theorem_id}")
    env_rev = t["mathlib_rev"]
    target_src = _module_source(t, as_axiom=True)
    done = _mirror(api, platform_imports(target_src), env_rev)
    tpath = WS / "Theorems" / f"Thm_{slug(t['theorem_name'])}.lean"
    tpath.parent.mkdir(parents=True, exist_ok=True)
    tpath.write_text(target_src)

    subs = api.get(f"/theorems/{args.theorem_id}/submissions", limit=50).get("submissions", [])
    decomps = api.get(f"/theorems/{args.theorem_id}/decompositions").get("decompositions", [])
    ledger_append({"event": "fetched", "theorem_id": t["theorem_id"], "theorem_name": t["theorem_name"]})
    missions = api.get(f"/theorems/{args.theorem_id}/missions").get("missions", [])
    print(json.dumps({
        "theorem_id": t["theorem_id"],
        "theorem_name": t["theorem_name"],
        "title": t.get("theorem_title"),
        "natural_language_statement": t.get("natural_language_statement"),
        "source": t.get("source"),
        "mathlib_rev": env_rev,
        "target_file": str(tpath),
        "solution_file": str(WS / "Solutions" / f"Sol_{slug(t['theorem_name'])}.lean"),
        "mirrored_modules": sorted(done),
        "preamble": t.get("preamble"),
        "formal_statement": t["formal_statement"],
        "audits": t.get("audits", []),
        # View any of these with `p2m.py solution <id>`.
        "previous_submissions": [{"id": s["id"], "status": s["status"], "user": s.get("username"),
                                  "error": (s.get("error_message") or "")[:300]} for s in subs[:15]],
        "decompositions": decomps,
        "missions": missions,
    }, indent=2, ensure_ascii=False))


def cmd_solution(api: Api, cfg: dict, args) -> None:
    """Print the Lean source of an existing submission (read-only)."""
    r = api.get(f"/submissions/{args.submission_id}/solution")
    code = r.get("lean_code") or r.get("solution") or r.get("content") if isinstance(r, dict) else None
    if isinstance(code, str):
        meta = {k: v for k, v in r.items() if not isinstance(v, str) or len(v) < 300}
        print(json.dumps(meta, ensure_ascii=False))
        print(code)
    else:
        print(json.dumps(r, indent=2, ensure_ascii=False))


def _import_closure(imports: list[str]) -> set[str]:
    """Platform modules reachable from `imports` through the mirrored files."""
    seen: set[str] = set()
    todo = list(imports)
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        f = WS / (mod.replace(".", "/") + ".lean")
        if f.exists():
            todo.extend(platform_imports(f.read_text()))
    return seen


def cmd_mirror(api: Api, cfg: dict, args) -> None:
    """Mirror existing platform theorems/definitions you want to import in a sketch."""
    env_rev = next(e for e in api.get("/environments")["environments"] if e["is_default"])["mathlib_rev"]
    mods = []
    for n in args.names:
        if n.startswith(("Theorems.", "Definitions.")):
            mods.append(n)
        else:
            rows = api.get("/theorems", theorem_name=n, env=env_rev)["theorems"]
            if not rows:
                die(f"no platform theorem/definition named {n} in the default environment")
            kind = "Definitions.Def_" if rows[0]["status"] == "Definition" else "Theorems.Thm_"
            mods.append(kind + slug(n))
    done = _mirror(api, mods, env_rev)
    print(json.dumps({m: {**v, "import": f"import {m}"} for m, v in done.items()}, indent=2))


def _run(cmd: list[str], timeout_min: int) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=WS, capture_output=True, text=True, timeout=timeout_min * 60)
        return p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout_min} min"


def gate(api: Api | None, cfg: dict, theorem_id: str, sol: Path, proof_type: str) -> dict:
    """All local checks a solution must pass before it may be submitted."""
    t = api.get(f"/theorems/{theorem_id}")
    name = t["theorem_name"]
    text = sol.read_text()
    code = re.sub(r"/-.*?-/", "", text, flags=re.S)
    code = re.sub(r"--[^\n]*", "", code)
    problems: list[str] = []
    if not re.search(r"^theorem\s+solution\b", code, re.M):
        problems.append("no top-level `theorem solution` (must be named exactly `solution`, outside any namespace)")
    head = code[:m.start()] if (m := re.search(r"^theorem\s+solution\b", code, re.M)) else ""
    opened = re.findall(r"^\s*namespace\s+(\S+)", head, re.M)
    closed = re.findall(r"^\s*end\s+(\S+)", head, re.M)
    if any(opened.count(n) > closed.count(n) for n in opened):
        problems.append("`theorem solution` appears after a `namespace`; keep it at top level")
    if re.search(r"\b(sorry|admit)\b", code):
        problems.append("contains `sorry`/`admit`")
    if re.search(r"\baxiom\b", code):  # also `private axiom`, `@[simp] axiom`
        problems.append("declares an `axiom`")
    imports = platform_imports(code)
    if f"Theorems.Thm_{slug(name)}" in imports:
        problems.append("imports its own target theorem")
    thm_imports = [i for i in imports if i.startswith("Theorems.")]
    if proof_type == "disprove" and thm_imports:
        problems.append("disproofs may not import platform theorems")
    if thm_imports and not cfg["allow_sketches"]:
        problems.append("imports platform theorems (a sketch), but allow_sketches is false")
    known = json.loads(MIRRORS.read_text()) if MIRRORS.exists() else {}
    for i in imports:
        if i not in known or not (WS / (i.replace(".", "/") + ".lean")).exists():
            problems.append(f"import {i} is not an existing platform module mirrored by `fetch`/`mirror`")
    result = {"theorem_id": theorem_id, "theorem_name": name, "file": str(sol),
              "sha256": hashlib.sha256(text.encode()).hexdigest(), "proof_type": proof_type}
    if problems:
        return {**result, "ok": False, "problems": problems}

    timeout = cfg["build_timeout_minutes"]
    rel = sol.resolve().relative_to(WS.resolve())
    module = ".".join(rel.with_suffix("").parts)
    rc, out = _run(["lake", "build", module], timeout)
    if rc != 0:
        out = "\n".join(l for l in out.splitlines() if not l.startswith("trace:"))  # LEAN_PATH noise
        return {**result, "ok": False, "problems": ["lake build failed"], "build_log": out[-6000:]}

    # Ask Lean which axioms `solution` depends on, and whether its type is the
    # target's type (for a disproof: the negation of the target statement).
    check_dir = WS / "AutoproverCheck"
    check_dir.mkdir(exist_ok=True)
    ax_file = check_dir / "Axioms.lean"
    ax_file.write_text(f"import {module}\n#print axioms solution\n")
    rc, out = _run(["lake", "env", "lean", str(ax_file)], timeout)
    m = re.search(r"depends on axioms: \[([^\]]*)\]", out)
    # Imported platform theorems are mirrored as axioms, so they show up here
    # by name; they are allowed (that is what a sketch is), anything else is not.
    # Only modules this solution actually (transitively) imports count.
    reachable = _import_closure(imports)
    platform_axioms = {v["name"] for m, v in known.items() if m in reachable and v["status"] != "Definition"}
    if rc != 0:
        problems.append("axiom check failed to run: " + out[-1500:])
    elif m:
        used = {a.strip() for a in m.group(1).split(",") if a.strip()}
        if name in used:
            problems.append("depends on the target theorem itself")
        bad = sorted(used - STANDARD_AXIOMS - (platform_axioms - {name}))
        if bad:
            problems.append(f"non-standard axioms (sorryAx = a `sorry` somewhere): {bad}")
        result["axioms"] = sorted(used)
        result["kind"] = "sketch" if used & (platform_axioms - {name}) else "direct"
    elif "does not depend on any axioms" in out:
        result["axioms"] = []
    else:
        problems.append("could not read `#print axioms` output: " + out[-800:])

    target_mod = f"Theorems.Thm_{slug(name)}"
    if proof_type == "disprove":
        result["type_match"] = "unchecked for disproofs; the server checks the negation"
    elif _run(["lake", "build", target_mod], timeout)[0] != 0:
        result["type_match"] = "unchecked (target module did not build locally)"
    else:
        tc_file = check_dir / "TypeMatch.lean"
        tc_file.write_text(f"import {module}\nimport {target_mod}\n"
                           f"example : type_of% @{name} := @_root_.solution\n")
        rc, out = _run(["lake", "env", "lean", str(tc_file)], timeout)
        if rc == 0:
            result["type_match"] = "verified"
        elif "has already been declared" in out:
            result["type_match"] = "unchecked (solution and target modules declare the same names)"
        else:
            problems.append("`solution` does not have the target's type: " + out[-2000:])

    return {**result, "ok": not problems, "problems": problems}


def cmd_check(api: Api, cfg: dict, args) -> None:
    res = gate(api, cfg, args.theorem_id, Path(args.file), args.proof_type)
    ledger_append({"event": "check", **{k: v for k, v in res.items() if k != "build_log"}})
    print(json.dumps(res, indent=2, ensure_ascii=False))
    sys.exit(0 if res["ok"] else 2)


def cmd_submit(api: Api, cfg: dict, args) -> None:
    sol = Path(args.file)
    if args.proof_type == "disprove" and not cfg["allow_disproofs"]:
        die("disproofs are disabled in autoprover.config.json")
    submitted = [e for e in ledger() if e.get("event") == "submitted"]
    if not cfg["dry_run"] and len(submitted) >= cfg["max_submissions_per_run"]:
        die(f"max_submissions_per_run ({cfg['max_submissions_per_run']}) reached", 5)
    # Re-run every gate on the exact bytes we are about to send.
    res = gate(api, cfg, args.theorem_id, sol, args.proof_type)
    if not res["ok"]:
        ledger_append({"event": "check", **{k: v for k, v in res.items() if k != "build_log"}})
        print(json.dumps(res, indent=2, ensure_ascii=False))
        die("local gates failed; not submitting", 2)
    explanation = Path(args.explanation_file).read_text() if args.explanation_file else ""
    # Always marked, not configurable; see README "Automated submissions".
    explanation += ("\n\n---\n*Submitted automatically by "
                    f"[prove2me-autoprover]({SOURCE_URL}) (unattended run).*")
    base = {"theorem_id": args.theorem_id, "theorem_name": res["theorem_name"],
            "proof_type": args.proof_type, "sha256": res["sha256"]}
    if cfg["dry_run"]:
        out_dir = STATE / "dry_run_solutions" / run_id()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / sol.name).write_text(sol.read_text())
        (out_dir / (sol.stem + ".explanation.md")).write_text(explanation)
        ledger_append({"event": "result", **base, "status": "DRY_RUN_PASSED_LOCAL_CHECKS",
                       "saved_as": [sol.name, sol.stem + ".explanation.md"]})
        print(json.dumps({**base, "status": "DRY_RUN", "message": "dry run: passed all local gates, NOT submitted"}))
        return
    data = sol.read_bytes()
    if hashlib.sha256(data).hexdigest() != res["sha256"]:
        die("solution file changed after the gates ran; not submitting", 2)
    form = {"theorem_id": args.theorem_id, "proof_type": args.proof_type, "file": ("solution.lean", data)}
    if explanation.strip():
        form["explanation"] = explanation
    r = api._http("POST", "/verify", form=form)
    sid = r["submission_id"]
    ledger_append({"event": "submitted", **base, "submission_id": sid})
    status, err = "PENDING", ""
    deadline = time.time() + args.poll_minutes * 60
    while status == "PENDING" and time.time() < deadline:
        time.sleep(15)
        v = api.get("/verify", submission_id=sid)
        status, err = v["status"], v.get("error_message", "")
    ledger_append({"event": "result", **base, "submission_id": sid, "status": status, "error": err[:2000]})
    print(json.dumps({**base, "submission_id": sid, "status": status, "error_message": err[:4000]}, indent=2))


def cmd_record(api: Api, cfg: dict, args) -> None:
    """Record a claim the agent gave up on (no submission), with a short reason."""
    ledger_append({"event": "result", "theorem_id": args.theorem_id, "theorem_name": args.theorem_name,
                   "status": args.status, "note": args.note})
    print("recorded")


def cmd_schedule(api: Api | None, cfg: dict, args) -> None:
    """Turn weekly_reset + lead_hours from the config into cron lines (UTC)."""
    from zoneinfo import ZoneInfo
    r = cfg["weekly_reset"]
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    tz = ZoneInfo(r["timezone"])
    hh, mm = map(int, r["time"].split(":"))
    today = dt.datetime.now(tz).replace(hour=hh, minute=mm, second=0, microsecond=0)
    reset = today + dt.timedelta(days=(days.index(r["day"].lower()) - today.weekday()) % 7)
    out = []
    for lead in cfg["lead_hours"]:
        start = (reset - dt.timedelta(hours=lead)).astimezone(dt.timezone.utc)
        start += dt.timedelta(minutes=7)  # schedulers start late exactly on the hour
        cron_dow = (start.weekday() + 1) % 7  # cron: 0 = Sunday
        out.append({"lead_hours": lead,
                    "local_start": (start.astimezone(tz)).strftime("%A %H:%M %Z"),
                    "cron_utc": f"{start.minute} {start.hour} * * {cron_dow}"})
    print(json.dumps({"weekly_reset": f"{r['day']} {r['time']} {r['timezone']}", "runs": out}, indent=2))
    print("Note: a run that starts within ~1h of a daylight-saving change can be off by an hour.",
          file=sys.stderr)


def cmd_summary(api: Api | None, cfg: dict, args) -> None:
    """Write logs/<run_id>.{md,jsonl} (+ dry-run solutions) from this run's ledger; print the markdown."""
    events = ledger()
    rid = run_id()
    LOGS.mkdir(parents=True, exist_ok=True)
    # Dry-run solutions (and their explanations) go to logs/<run_id>/ so they persist.
    src_dir = STATE / "dry_run_solutions" / rid
    for name in sorted({n for e in events for n in e.get("saved_as", [])}):
        if (src_dir / name).exists():
            (LOGS / rid).mkdir(exist_ok=True)
            (LOGS / rid / name).write_text((src_dir / name).read_text())
    (LOGS / f"{rid}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    results = [e for e in events if e.get("event") == "result"]
    mode = "DRY RUN (nothing submitted)" if cfg["dry_run"] else "LIVE"
    lines = [f"# prove2me-autoprover run {rid}", "", f"Mode: **{mode}**", ""]
    if args.stop_reason:
        lines += [f"Stopped because: {args.stop_reason}", ""]
    lines += ["| Theorem | Outcome | Submission | Note |", "|---|---|---|---|"]
    for e in results:
        link = f"[{e['theorem_name']}](https://prove2.me/theorems/{e['theorem_id']})"
        note = (e.get("note") or e.get("error") or "").replace("\n", " ").replace("|", "/")[:200]
        lines.append(f"| {link} | {e['status']} | {e.get('submission_id', '')} | {note} |")
    if not results:
        lines.append("| (none) | | | |")
    md = "\n".join(lines) + "\n"
    (LOGS / f"{rid}.md").write_text(md)
    print(md)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="check credentials, versions, env pin, mode")
    s = sub.add_parser("pin-env", help="write lean-toolchain/lakefile.lean for an environment")
    s.add_argument("--rev", help="mathlib_rev (default: the platform default env)")
    sub.add_parser("candidates", help="ranked shortlist of open claims (JSON)")
    s = sub.add_parser("mirror", help="mirror existing platform theorems/definitions to import in a sketch")
    s.add_argument("names", nargs="+", help="platform names or module names (Theorems.Thm_x)")
    s = sub.add_parser("fetch", help="mirror a target and its platform imports locally")
    s.add_argument("theorem_id")
    s = sub.add_parser("solution", help="print the Lean source of an existing submission (read-only)")
    s.add_argument("submission_id")
    for name in ("check", "submit"):
        s = sub.add_parser(name, help="run local gates" if name == "check" else "gate, then submit (or dry-run)")
        s.add_argument("theorem_id")
        s.add_argument("file")
        s.add_argument("--proof-type", choices=["prove", "disprove"], default="prove")
        if name == "submit":
            s.add_argument("--explanation-file")
            s.add_argument("--poll-minutes", type=int, default=20)
    s = sub.add_parser("record", help="record a claim abandoned without submitting")
    s.add_argument("theorem_id")
    s.add_argument("theorem_name")
    s.add_argument("--status", default="GAVE_UP", choices=["GAVE_UP", "SKIPPED", "OUT_OF_TIME", "USAGE_LIMIT"])
    s.add_argument("--note", default="")
    sub.add_parser("schedule", help="print cron lines for the configured weekly reset and lead times")
    s = sub.add_parser("summary", help="write logs/<run>.md, .jsonl and dry-run solutions to the data repo")
    s.add_argument("--stop-reason", default="")
    args = p.parse_args()

    cfg = load_config()
    api = Api()  # lazy: only touches credentials on the first API call
    fn = globals()["cmd_" + args.cmd.replace("-", "_")]
    try:
        fn(api, cfg, args)
    except RuntimeError as e:
        die(str(e))


if __name__ == "__main__":
    main()
