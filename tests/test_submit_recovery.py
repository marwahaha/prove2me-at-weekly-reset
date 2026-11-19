"""Offline tests of lost-upload recovery, `followup`, SERVER_ERROR, the pre-submit
liveness check and Definitions lookups. No network: a FakeApi stands in for Prove2me."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

P2M = Path(__file__).resolve().parent.parent / "scripts" / "p2m.py"


def load_p2m():
    tmp = Path(tempfile.mkdtemp())
    keys = ("AUTOPROVER_DATA", "AUTOPROVER_STATE", "AUTOPROVER_CONFIG", "AUTOPROVER_DRY_RUN",
            "AUTOPROVER_MAX_SUBMISSIONS_PER_RUN", "PROVE2ME_WORKSPACE")
    old = {k: os.environ.get(k) for k in keys}
    cfg = tmp / "autoprover.config.json"
    cfg.write_text(json.dumps({"dry_run": False, "max_submissions_per_run": 3}))
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update({"AUTOPROVER_DATA": str(tmp), "AUTOPROVER_STATE": str(tmp / "state"),
                       "AUTOPROVER_CONFIG": str(cfg), "PROVE2ME_WORKSPACE": str(tmp / "ws")})
    try:
        spec = importlib.util.spec_from_file_location(f"p2m_rec_{id(tmp)}", P2M)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    m.RECOVERY_WAIT_S = 0
    m.time = _FastTime()
    return m, tmp


class _FastTime:
    """`time` for the module under test: sleeps are free."""
    def __getattr__(self, name):
        return getattr(time, name)

    @staticmethod
    def sleep(_s):
        return None


SOURCE = "-- notice\ntheorem solution : True := trivial\n"
SHA = hashlib.sha256(SOURCE.encode()).hexdigest()


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


class FakeApi:
    """Prove2me stand-in. `post` is what POST /verify does: a dict to return or an exception."""
    def __init__(self, post=None, history=(), solutions=None, verdicts=None, theorem=None, catalog=None,
                 page_size=100):
        self.post, self.history, self.solutions = post, list(history), solutions or {}
        self.verdicts, self.theorem, self.catalog = verdicts or {}, theorem, catalog
        self.page_size = page_size
        self.posts, self.calls = 0, []

    def _http(self, method, path, **kw):
        assert (method, path) == ("POST", "/verify") and kw.get("retry") is False
        self.posts += 1
        if isinstance(self.post, Exception):
            raise self.post
        return self.post

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "/submissions":
            n = self.page_size
            rows = self.history[(params["page"] - 1) * n: params["page"] * n]
            return {"submissions": rows, "total": len(self.history)}
        if path.startswith("/submissions/") and path.endswith("/solution"):
            return {"content": self.solutions[path.split("/")[2]], "file_path": "x"}
        if path == "/verify":
            v = self.verdicts[params["submission_id"]]
            if isinstance(v, Exception):
                raise v
            return v
        if path.startswith("/theorems/"):
            return self.theorem
        if path in ("/theorems", "/definitions"):
            return self.catalog(path, params)
        raise AssertionError(path)


def theorem(**kw):
    return {"theorem_id": "T1", "theorem_name": "foo", "status": "Open", "deprecated_at": None,
            "formal_statement": "theorem foo : True := by sorry", "preamble": "", "mathlib_rev": "abc", **kw}


class Base(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = load_p2m()
        self.cfg = self.m.load_config()
        self.sol = self.tmp / "Sol.lean"
        self.sol.write_text(SOURCE)
        self.m.require_usage = lambda *a, **k: None
        self.m.add_tool_notice = lambda sol: None
        self.gate_res = {"theorem_id": "T1", "theorem_name": "foo", "file": str(self.sol), "sha256": SHA,
                         "proof_type": "prove", "ok": True, "problems": []}
        self.m.gate = lambda *a, **k: dict(self.gate_res)

    def submit(self, api, theorem_id="T1"):
        args = argparse.Namespace(file=str(self.sol), theorem_id=theorem_id, proof_type="prove",
                                  explanation_file=None, poll_minutes=1)
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.m.cmd_submit(api, self.cfg, args)
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def events(self, kind=None):
        return [e for e in self.m.ledger() if kind is None or e.get("event") == kind]


class LostSubmitTests(Base):
    def test_normal_submit_polls_and_records(self):
        api = FakeApi(post={"submission_id": "S1"}, verdicts={"S1": {"status": "ACCEPTED", "error_message": ""}})
        code, out, _ = self.submit(api)
        self.assertEqual(code, 0)
        self.assertEqual(api.posts, 1)
        self.assertEqual(self.events("submitted")[0]["submission_id"], "S1")
        self.assertEqual(self.events("result")[-1]["status"], "ACCEPTED")

    def test_timeout_recovered_from_history(self):
        now = time.time()
        history = [{"id": "other", "theorem_id": "T9", "created_at": iso(now), "status": "PENDING"},
                   {"id": "S-old", "theorem_id": "T1", "created_at": iso(now - 3 * 86400), "status": "FAILED"},
                   {"id": "S-diff", "theorem_id": "T1", "created_at": iso(now), "status": "PENDING"},
                   {"id": "S-mine", "theorem_id": "T1", "created_at": iso(now), "status": "PENDING"}]
        api = FakeApi(post=self.m.ApiError("POST /verify -> network error: timed out"), history=history,
                      solutions={"S-diff": "something else", "S-mine": SOURCE},
                      verdicts={"S-mine": {"status": "ACCEPTED", "error_message": ""}})
        code, out, err = self.submit(api)
        self.assertEqual(code, 0, err)
        self.assertEqual(api.posts, 1)
        sub = self.events("submitted")
        self.assertEqual([(e["submission_id"], e.get("recovered")) for e in sub], [("S-mine", True)])
        self.assertEqual(self.events("result")[-1]["status"], "ACCEPTED")
        fetched = [p for p, _ in api.calls if p.endswith("/solution")]
        self.assertNotIn("/submissions/S-old/solution", fetched)  # outside the time window
        self.assertNotIn("/submissions/other/solution", fetched)  # another theorem

    def test_5xx_not_found_is_unknown_counts_and_blocks(self):
        api = FakeApi(post=self.m.ApiError("POST /verify -> HTTP 502: bad gateway", 502), history=[])
        code, out, err = self.submit(api)
        self.assertEqual(code, 10)
        self.assertIn("Do NOT resubmit", err)
        self.assertEqual(api.posts, 1)
        self.assertFalse(self.events("submitted"))
        self.assertEqual(self.events("result")[-1]["status"], "SUBMISSION_UNKNOWN")
        self.assertEqual(self.m.submissions_used(self.m.ledger()), 1)
        # The agent tries again: refused before any upload.
        code, _, err = self.submit(api)
        self.assertEqual(code, 10)
        self.assertEqual(api.posts, 1)
        # Another theorem may still be submitted, and the unknown one counts against the cap.
        self.cfg["max_submissions_per_run"] = 1
        code, _, err = self.submit(FakeApi(post={"submission_id": "S2"}), theorem_id="T2")
        self.assertEqual(code, 5)

    def test_history_lookup_failure_is_unknown(self):
        class Broken(FakeApi):
            def get(self, path, **params):
                if path == "/submissions":
                    raise self_m.ApiError("GET /submissions -> HTTP 500: oops", 500)
                return super().get(path, **params)
        self_m = self.m
        api = Broken(post=TimeoutError("timed out"))
        code, _, err = self.submit(api)
        self.assertEqual(code, 10)
        self.assertIn("history lookup failed", self.events("result")[-1]["error"])
        self.assertEqual(api.posts, 1)

    def test_unreadable_200_is_recovered(self):
        now = time.time()
        api = FakeApi(post={"oops": 1}, history=[{"id": "S3", "theorem_id": "T1", "created_at": iso(now),
                                                   "status": "ACCEPTED", "error_message": ""}],
                      solutions={"S3": SOURCE})
        code, _, err = self.submit(api)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.events("result")[-1]["status"], "ACCEPTED")

    def test_4xx_is_refused_not_counted(self):
        api = FakeApi(post=self.m.ApiError("POST /verify -> HTTP 400: bad", 400))
        with self.assertRaises(RuntimeError):
            with contextlib.redirect_stdout(io.StringIO()):
                self.m.cmd_submit(api, self.cfg, argparse.Namespace(
                    file=str(self.sol), theorem_id="T1", proof_type="prove", explanation_file=None, poll_minutes=1))
        self.assertEqual(self.m.submissions_used(self.m.ledger()), 0)
        self.assertEqual(self.events("submit_refused")[0]["theorem_id"], "T1")
        self.assertEqual(api.posts, 1)

    def test_killed_mid_upload_counts_and_blocks(self):
        self.m.ledger_append({"event": "submit_started", "theorem_id": "T1", "sha256": SHA, "attempt_id": "a1"})
        api = FakeApi(post={"submission_id": "S1"})
        code, _, err = self.submit(api)
        self.assertEqual(code, 10)
        self.assertEqual(api.posts, 0)

    def test_same_proof_twice_refused(self):
        api = FakeApi(post={"submission_id": "S1"}, verdicts={"S1": {"status": "FAILED", "error_message": "x"}})
        self.assertEqual(self.submit(api)[0], 0)
        code, _, err = self.submit(api)
        self.assertEqual(code, 10)
        self.assertIn("already submitted", err)
        self.assertEqual(api.posts, 1)

    def test_storage_failure_row_matches_without_hash(self):
        now = time.time()
        row = {"id": "S5", "theorem_id": "T1", "created_at": iso(now), "status": "ERROR",
               "error_message": "Could not enqueue the submission: could not store the proof file: boom"}
        api = FakeApi(post=self.m.ApiError("timed out"), history=[row])
        code, out, _ = self.submit(api)
        self.assertEqual(code, 0)
        self.assertEqual(self.events("result")[-1]["status"], "SERVER_ERROR")
        self.assertFalse([p for p, _ in api.calls if p.endswith("/solution")])

    def test_history_pages_until_older_than_window(self):
        now = time.time()
        old = [{"id": f"o{i}", "theorem_id": "T1", "created_at": iso(now - 86400), "status": "FAILED"}
               for i in range(5)]
        api = FakeApi(history=old * 10, page_size=5)
        row, why = self.m.find_lost_submission(api, "T1", SHA, now)
        self.assertEqual((row, why), (None, "absent"))
        self.assertEqual(sum(1 for p, _ in api.calls if p == "/submissions"), 1)


class ServerErrorTests(Base):
    def test_server_error_recorded_and_retryable_later(self):
        msg = "Could not enqueue the submission: could not store the proof file: S3 down"
        api = FakeApi(post={"submission_id": "S1"}, verdicts={"S1": {"status": "ERROR", "error_message": msg}})
        code, out, _ = self.submit(api)
        self.assertEqual(code, 0)
        res = self.events("result")[-1]
        self.assertEqual((res["status"], res["server_status"]), ("SERVER_ERROR", "ERROR"))
        # Not retried in this run, even with a different proof.
        self.gate_res["sha256"] = "0" * 64
        code, _, err = self.submit(api)
        self.assertEqual(code, 10)
        self.assertIn("SERVER_ERROR", err)
        # A later run may retry it: write this run's log and ask previously_attempted.
        logs = self.m.LOGS
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "20260101-000000.jsonl").write_text("".join(json.dumps(e) + "\n" for e in self.m.ledger()))
        self.assertNotIn("T1", self.m.previously_attempted())

    def test_other_errors_stay_errors(self):
        self.assertEqual(self.m.classify_verdict("ERROR", "lean crashed"), "ERROR")
        self.assertEqual(self.m.classify_verdict("FAILED", "could not store the proof file"), "FAILED")

    def test_notify_text(self):
        events = [{"event": "result", "theorem_id": "T1", "theorem_name": "foo", "submission_id": "S1",
                   "status": "SERVER_ERROR"}]
        text = self.m.notify_text(events, self.cfg, "rid")
        self.assertIn("server error", text)
        self.assertNotIn("rejected", text)


class LivenessTests(Base):
    def test_target_changes(self):
        t = theorem()
        fetched = [{"event": "fetched", "theorem_id": "T1", "mathlib_rev": "abc",
                    "target_sha256": self.m.target_fingerprint(t)}]
        tc = self.m.target_changes
        self.assertEqual(tc(t, "T1", fetched), [])
        self.assertEqual(tc(t, "T1", []), [])
        self.assertIn("no longer Open", tc(theorem(status="Proved"), "T1", fetched)[0])
        self.assertIn("deprecated", tc(theorem(deprecated_at="2026-11-01"), "T1", [])[0])
        self.assertIn("statement", tc(theorem(formal_statement="theorem foo : 1 = 1 := by sorry"), "T1", fetched)[0])
        self.assertIn("environment", tc(theorem(mathlib_rev="def"), "T1", fetched)[0])
        # Without a fetch record only status/deprecation count.
        self.assertEqual(tc(theorem(formal_statement="x"), "T1", []), [])

    def test_gate_refuses_before_building(self):
        m, _ = load_p2m()  # a fresh module with the real gate
        m.require_usage = lambda *a, **k: None
        m.add_tool_notice = lambda sol: None
        m._run = lambda *a, **k: self.fail("must not build")
        api = FakeApi(post={"submission_id": "S1"}, theorem=theorem(status="Proved"))
        args = argparse.Namespace(file=str(self.sol), theorem_id="T1", proof_type="prove",
                                  explanation_file=None, poll_minutes=1)
        for cmd in (m.cmd_submit, m.cmd_check):
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                cmd(api, m.load_config(), args)
            self.assertEqual(cm.exception.code, 9)
        self.assertEqual(api.posts, 0)
        results = [e for e in m.ledger() if e.get("event") == "result"]
        self.assertEqual([e["status"] for e in results], ["TARGET_CHANGED"])  # recorded once
        self.assertNotIn("T1", {e["theorem_id"] for e in results if e["status"] not in m.RETRYABLE_STATUSES})


class FollowupTests(Base):
    def write_log(self, name, events):
        self.m.LOGS.mkdir(parents=True, exist_ok=True)
        (self.m.LOGS / f"{name}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))

    def followup(self, api):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.m.cmd_followup(api, self.cfg, argparse.Namespace())
        return json.loads(out.getvalue())

    def test_pending_resolved(self):
        t = iso(time.time() - 7 * 86400)
        self.write_log("20261111-000000", [
            {"time": t, "event": "submitted", "theorem_id": "T1", "theorem_name": "foo", "submission_id": "S1"},
            {"time": t, "event": "result", "theorem_id": "T1", "theorem_name": "foo", "submission_id": "S1",
             "status": "PENDING"},
            {"time": t, "event": "result", "theorem_id": "T2", "theorem_name": "bar", "submission_id": "S2",
             "status": "PENDING"},
            {"time": t, "event": "result", "theorem_id": "T3", "theorem_name": "baz", "submission_id": "S3",
             "status": "FAILED"}])
        api = FakeApi(verdicts={"S1": {"status": "ACCEPTED", "error_message": ""},
                                "S2": {"status": "PENDING", "error_message": ""}})
        rep = self.followup(api)
        self.assertEqual(sorted(params["submission_id"] for _, params in api.calls), ["S1", "S2"])
        fu = self.events("followup")
        self.assertEqual([(e["submission_id"], e["status"], e["followup_of"]) for e in fu],
                         [("S1", "ACCEPTED", "20261111-000000")])
        self.assertEqual(len(rep["followed_up"]), 2)
        # Summary and notification show it.
        text = self.m.notify_text(self.m.ledger(), self.cfg, "rid")
        self.assertIn("1 accepted (foo)", text)
        self.assertTrue(any("PENDING -> **ACCEPTED**" in l for l in self.m.followup_lines(self.m.ledger())))
        # Once this run's log exists, S1 is not looked up again.
        self.write_log("20261118-000000", self.m.ledger())
        api2 = FakeApi(verdicts={"S2": {"status": "PENDING"}})
        self.followup(api2)
        self.assertEqual([c[1]["submission_id"] for c in api2.calls], ["S2"])

    def test_bounds(self):
        now = time.time()
        events = [{"time": iso(now - i * 60), "event": "result", "theorem_id": f"T{i}", "submission_id": f"S{i}",
                   "status": "PENDING"} for i in range(30)]
        events.append({"time": iso(now - 61 * 86400), "event": "result", "theorem_id": "Told",
                       "submission_id": "Sold", "status": "PENDING"})
        self.write_log("20261001-000000", events)
        api = FakeApi(verdicts={f"S{i}": {"status": "PENDING"} for i in range(30)})
        rep = self.followup(api)
        looked = [c[1]["submission_id"] for c in api.calls]
        self.assertEqual(len(looked), 20)
        self.assertNotIn("Sold", looked)
        self.assertEqual(looked[0], "S0")  # newest first
        self.assertEqual(rep["not_looked_up"], 10)

    def test_server_error_followup_is_retryable(self):
        t = iso(time.time() - 86400)
        self.write_log("20261117-000000", [
            {"time": t, "event": "submitted", "theorem_id": "T1", "submission_id": "S1"},
            {"time": t, "event": "result", "theorem_id": "T1", "submission_id": "S1", "status": "PENDING"}])
        self.assertIn("T1", self.m.previously_attempted())
        msg = "Could not enqueue the submission: could not store the proof file: x"
        self.followup(FakeApi(verdicts={"S1": {"status": "ERROR", "error_message": msg}}))
        self.assertEqual(self.events("followup")[0]["status"], "SERVER_ERROR")
        self.write_log("20261118-000000", self.m.ledger())
        self.assertNotIn("T1", self.m.previously_attempted())

    def test_unknown_upload_resolved_or_lost(self):
        started = time.time() - 2 * 86400
        base = {"event": "result", "theorem_id": "T1", "theorem_name": "foo", "sha256": SHA,
                "started_at": iso(started), "status": "SUBMISSION_UNKNOWN"}
        self.write_log("20261116-000000", [
            {"event": "submit_started", "theorem_id": "T1", "sha256": SHA, "attempt_id": "a1"},
            {**base, "attempt_id": "a1"}])
        self.assertIn("T1", self.m.previously_attempted())
        # Found in the history: recorded with its submission id and verdict.
        api = FakeApi(history=[{"id": "S9", "theorem_id": "T1", "created_at": iso(started + 30),
                                "status": "ACCEPTED", "error_message": ""}], solutions={"S9": SOURCE})
        self.followup(api)
        fu = self.events("followup")
        self.assertEqual([(e["submission_id"], e["status"], e["attempt_id"]) for e in fu], [("S9", "ACCEPTED", "a1")])
        # Not in the history at all: lost, so a later run may try the theorem again.
        (self.m.STATE / "ledger.jsonl").unlink()
        self.followup(FakeApi(history=[]))
        self.assertEqual(self.events("followup")[0]["status"], "SUBMISSION_LOST")
        self.write_log("20261118-000000", self.m.ledger())
        self.assertNotIn("T1", self.m.previously_attempted())

    def test_followup_never_writes(self):
        class NoWrites(FakeApi):
            def _http(self, *a, **k):
                raise AssertionError("followup must not write")
        t = iso(time.time() - 3600)
        self.write_log("20261118-000000", [{"time": t, "event": "result", "theorem_id": "T1",
                                            "submission_id": "S1", "status": "PENDING"}])
        self.followup(NoWrites(verdicts={"S1": {"status": "ACCEPTED"}}))


class DefinitionLookupTests(Base):
    def test_definitions_use_status_filter(self):
        row = {"theorem_id": "D1", "theorem_name": "Foo_bar", "status": "Definition", "definition": "def x := 1"}

        def catalog(path, params):
            self.assertEqual(path, "/theorems")
            hidden = params.get("status") != "Definition"
            return {"theorems": [] if hidden else [row]}
        api = FakeApi(catalog=catalog)
        self.assertEqual(self.m._resolve_module(api, "Definitions.Def_Foo_bar", "abc")["theorem_id"], "D1")
        self.assertEqual(api.calls[0][1]["status"], "Definition")

    def test_theorems_unfiltered(self):
        row = {"theorem_id": "T7", "theorem_name": "Foo_bar", "status": "Proved"}
        api = FakeApi(catalog=lambda path, params: {"theorems": [] if params.get("status") else [row]})
        self.assertEqual(self.m._resolve_module(api, "Theorems.Thm_Foo_bar", "abc")["theorem_id"], "T7")
        self.assertIsNone(api.calls[0][1].get("status"))  # Api.get drops None params

    def test_definitions_endpoint_fallback(self):
        m = self.m

        def catalog(path, params):
            if path == "/theorems":
                raise m.ApiError("GET /theorems -> HTTP 422: bad status", 422)
            self.assertEqual(params.get("definition_name"), "Foo_bar")
            return {"definitions": [{"definition_id": "D2", "definition_name": "Foo_bar", "definition": "def y := 2"}]}
        api = FakeApi(catalog=catalog)
        row = m._resolve_module(api, "Definitions.Def_Foo_bar", "abc")
        self.assertEqual((row["theorem_id"], row["theorem_name"], row["status"]), ("D2", "Foo_bar", "Definition"))
        self.assertEqual(m._module_source(row), "def y := 2")


if __name__ == "__main__":
    unittest.main()
