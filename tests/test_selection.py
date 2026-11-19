"""Offline tests of candidate selection: fields, search fallback and source order."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

P2M = Path(__file__).resolve().parent.parent / "scripts" / "p2m.py"


def load_p2m():
    tmp = Path(tempfile.mkdtemp())
    old = {k: os.environ.get(k) for k in ("AUTOPROVER_DATA", "AUTOPROVER_STATE", "AUTOPROVER_CONFIG")}
    os.environ.update({"AUTOPROVER_DATA": str(tmp), "AUTOPROVER_STATE": str(tmp / "state"),
                       "AUTOPROVER_CONFIG": str(tmp / "none.json")})
    try:
        spec = importlib.util.spec_from_file_location(f"p2m_sel_{id(tmp)}", P2M)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return m


def mission(i, slug, status="Open"):
    return {"id": f"m{i}", "name": f"M{i}", "fields": [{"slug": slug}],
            "main_theorem": {"theorem_id": f"root{i}", "status": status}}


class FakeApi:
    def __init__(self, missions, leaves, theorems=(), saved=()):
        self.missions, self.leaves, self.theorems, self.saved = missions, leaves, list(theorems), list(saved)
        self.calls = []

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "/missions":
            o, n = params["offset"], params["limit"]
            return {"missions": self.missions[o:o + n], "total": len(self.missions)}
        if path.startswith("/theorems/") and path.endswith("/open-leaves"):
            return {"open_leaves": self.leaves.get(path.split("/")[2], [])}
        if path == "/theorems":
            assert "tags" not in params  # Prove2me's server-side tags filter returns HTTP 500
            return {"theorems": self.theorems}
        if path == "/saved":
            return {"saved": self.saved}
        raise AssertionError(path)


def leaf(tid, c=0):
    return {"theorem_id": tid, "theorem_name": tid, "closability": c}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.m = load_p2m()

    def sel(self, **kw):
        return {**self.m.DEFAULT_CONFIG["selection"], **kw}

    def test_fields_filter_open_missions_and_rank_by_closability(self):
        missions = [mission(i, "quantum-information") for i in range(150)]
        missions += [mission(900, "number-theory"), mission(901, "quantum-information", status="Proved")]
        leaves = {"root3": [leaf("a", 0), leaf("b", 5)], "root900": [leaf("x")], "root901": [leaf("y")]}
        api = FakeApi(missions, leaves)
        rows = self.m._field_rows(api, self.sel(fields=["Quantum-Information"], missions_per_run=200))
        ids = [r["theorem_id"] for r in rows]
        self.assertEqual(ids[0], "b")  # highest closability first
        self.assertIn("a", ids)
        self.assertNotIn("x", ids)  # other field
        self.assertNotIn("y", ids)  # finished mission
        self.assertEqual(sum(1 for p, _ in api.calls if p == "/missions"), 2)  # paged 100 + 52

    def test_missions_per_run_caps_the_sample(self):
        api = FakeApi([mission(i, "tcs") for i in range(40)], {})
        self.m._field_rows(api, self.sel(fields=["tcs"], missions_per_run=7))
        self.assertEqual(sum(1 for p, _ in api.calls if p.endswith("/open-leaves")), 7)

    def test_search_only_without_fields_and_sorted(self):
        th = [{"theorem_id": "long", "vote_count": 1, "formal_statement": "x" * 50, "tags": ["q"]},
              {"theorem_id": "short", "vote_count": 1, "formal_statement": "x", "tags": []},
              {"theorem_id": "none", "vote_count": 0, "formal_statement": "", "tags": ["q"]}]
        cfg = {"selection": self.sel(sources=["search"])}
        rows = self.m._theorem_rows(FakeApi([], {}, th), cfg, "rev")
        self.assertEqual([r["theorem_id"] for r in rows], ["short", "long", "none"])
        cfg["selection"]["tags"] = ["Q"]  # filtered here, any tag matches
        rows = self.m._theorem_rows(FakeApi([], {}, th), cfg, "rev")
        self.assertEqual([r["theorem_id"] for r in rows], ["long", "none"])
        cfg = {"selection": self.sel(sources=["fields", "search"], fields=["tcs"])}
        api = FakeApi([mission(1, "tcs")], {"root1": [leaf("f")]}, th)
        rows = self.m._theorem_rows(api, cfg, "rev")
        self.assertEqual([r["theorem_id"] for r in rows], ["f"])  # fields replace the search

    def test_saved_comes_first(self):
        cfg = {"selection": self.sel(fields=["tcs"])}
        api = FakeApi([mission(1, "tcs")], {"root1": [leaf("f"), leaf("s")]},
                      saved=[{"theorem_id": "s", "theorem_name": "s"}])
        rows = self.m._theorem_rows(api, cfg, "rev")
        self.assertEqual([(r["theorem_id"], r["_source"]) for r in rows], [("s", "saved"), ("f", "field:M1")])


class FieldsSnapshotTests(unittest.TestCase):
    def test_without_a_key_lists_the_snapshot_and_never_calls_the_api(self):
        import contextlib, io, json, types
        from unittest import mock
        m = load_p2m()
        m.CREDS = m.KEY_FILE = Path(tempfile.mkdtemp()) / "missing"
        out = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=False), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            os.environ.pop("PROVE2ME_CREDENTIALS", None)
            m.cmd_fields(FakeApi([], {}), {}, types.SimpleNamespace(q="QUANTUM", live=False))
        rows = json.loads(out.getvalue())
        self.assertIn("quantum-information", [r["slug"] for r in rows])
        self.assertTrue(all("quantum" in r["slug"] or "quantum" in r["name"].lower() for r in rows))


class ToolNoticeTests(unittest.TestCase):
    def test_notice_is_first_line_once_and_imports_still_parse(self):
        m = load_p2m()
        sol = Path(tempfile.mkdtemp()) / "Sol.lean"
        sol.write_text("import Mathlib\nimport Theorems.Thm_foo\n\ntheorem solution : True := trivial\n")
        m.add_tool_notice(sol)
        m.add_tool_notice(sol)  # idempotent
        lines = sol.read_text().splitlines()
        self.assertTrue(lines[0].startswith("-- Proved automatically by prove2me-at-weekly-reset ("))
        self.assertIn(m.SOURCE_URL, lines[0])
        self.assertEqual(lines[1], "import Mathlib")
        self.assertEqual(sum(1 for l in lines if "prove2me-at-weekly-reset" in l), 1)
        self.assertIn("Theorems.Thm_foo", m.platform_imports(sol.read_text()))


if __name__ == "__main__":
    unittest.main()
