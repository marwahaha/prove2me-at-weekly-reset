"""Offline tests of the automatic Prove2me key renewal (no network, no git push)."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

P2M = Path(__file__).resolve().parent.parent / "scripts" / "p2m.py"
os.environ.setdefault("AUTOPROVER_NO_PIP", "1")  # never pip-install from tests
try:
    import cryptography  # noqa: F401
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False
needs_crypto = unittest.skipUnless(HAVE_CRYPTO, "needs the Python package cryptography")
PASTED = '{"api_key":"p2m_pasted_test_key"}'


def load_p2m(tmp: Path, pasted: str | None = PASTED):
    """Import p2m.py with its paths pointed into tmp."""
    data = tmp / "data"
    data.mkdir(exist_ok=True)
    (data / "autoprover.config.json").write_text("{}")
    env = {"AUTOPROVER_DATA": str(data), "AUTOPROVER_STATE": str(tmp / "state"),
           "PROVE2ME_WORKSPACE": str(tmp / "ws"), "PROVE2ME_CREDENTIALS_FILE": str(tmp / "ws" / "credentials.json")}
    old = {k: os.environ.get(k) for k in [*env, "PROVE2ME_CREDENTIALS", "AUTOPROVER_CONFIG"]}
    os.environ.update(env)
    os.environ.pop("AUTOPROVER_CONFIG", None)
    os.environ.pop("PROVE2ME_CREDENTIALS", None)
    os.environ.pop("AUTOPROVER_ENCRYPTION_SECRET", None)  # tests set it with mock.patch.dict
    if pasted is not None:  # what prepare.sh writes from $PROVE2ME_CREDENTIALS
        (tmp / "ws").mkdir(exist_ok=True)
        (tmp / "ws" / "credentials.json").write_text(pasted)
    try:
        spec = importlib.util.spec_from_file_location(f"p2m_{id(tmp)}", P2M)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return m


class FakeApi:
    """Stands in for Api: records calls, mints keys, rejects keys listed in `dead`."""
    def __init__(self, m, dead=()):
        self.m, self.dead, self.calls, self.minted = m, set(dead), [], 0

    def token(self):
        return "tok"

    def _http(self, method, path, json_body=None, auth=True, retry=True):
        self.calls.append((method, path, (json_body or {}).get("api_key")))
        if path == "/agent/refresh":
            if json_body["api_key"] in self.dead:
                raise RuntimeError("POST /agent/refresh -> HTTP 401: expired")
            return {"access_token": "tok", "expires_at": time.time() + 3600, "version": "x"}
        if path == "/agent/api-key":
            self.minted += 1
            return {"api_key": f"p2m_minted_{self.minted}", "expires_at": int(time.time() + 30 * 86400)}
        raise AssertionError(path)


def args(**kw):
    return types.SimpleNamespace(**{"no_push": True, "strict": False, **kw})


@needs_crypto
class SealTests(unittest.TestCase):
    def setUp(self):
        self.m = load_p2m(Path(tempfile.mkdtemp()))

    def test_roundtrip_wrong_password_and_tamper(self):
        blob = self.m.seal(b'{"api_key":"p2m_x"}', b"pw")
        self.assertEqual(self.m.unseal(blob, b"pw"), b'{"api_key":"p2m_x"}')
        self.assertIsNone(self.m.unseal(blob, b"other"))
        bad = dict(blob, fernet=blob["fernet"][:-8] + "AAAAAAAA")
        self.assertIsNone(self.m.unseal(bad, b"pw"))
        self.assertIsNone(self.m.unseal(dict(blob, format="p2m-key-v1"), b"pw"))
        self.assertNotIn("p2m_x", json.dumps(blob))
        self.assertEqual(blob["iterations"], 600_000)


@needs_crypto
class RenewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.m = load_p2m(self.tmp)

    def renew(self, api, **kw):
        try:
            self.m.cmd_renew_key(api, {}, args(**kw))
        except SystemExit as e:
            return e.code
        return 0

    def test_mints_on_every_run(self):
        api = FakeApi(self.m)
        self.assertEqual(self.renew(api), 0)
        self.assertEqual(api.minted, 1)
        self.assertTrue(self.m.KEY_FILE.exists())
        self.assertNotIn("p2m_minted", self.m.KEY_FILE.read_text())  # encrypted
        self.assertEqual(self.m.stored_key()["api_key"], "p2m_minted_1")
        self.renew(api)  # still fresh, renewed anyway
        self.assertEqual(api.minted, 2)
        self.assertEqual(self.m.stored_key()["api_key"], "p2m_minted_2")
        self.assertEqual([c[2] for c in api.calls if c[1] == "/agent/api-key"], [None, None])

    def test_new_pasted_key_overrides_old_file(self):
        self.renew(FakeApi(self.m))
        self.m.CREDS.write_text('{"api_key":"p2m_new_pasted"}')
        self.assertIsNone(self.m.stored_key())  # old file no longer decrypts

    def test_refresh_prefers_renewed_and_falls_back(self):
        self.renew(FakeApi(self.m))
        real = self.m.Api()
        fake = FakeApi(self.m, dead={"p2m_minted_1"})
        real._http = fake._http
        real._refresh()
        self.assertEqual([c[2] for c in fake.calls], ["p2m_minted_1", "p2m_pasted_test_key"])

    def test_failure_is_logged_not_fatal(self):
        class Broken(FakeApi):
            def _http(self, method, path, **kw):
                raise RuntimeError("POST /agent/api-key -> HTTP 500: boom")
        self.assertEqual(self.renew(Broken(self.m)), 0)
        self.assertEqual(self.m.ledger()[-1]["event"], "key_renewal_failed")
        self.assertEqual(self.renew(Broken(self.m), strict=True), 8)
        self.assertIn("renewal failed", self.m.notify_text(self.m.ledger(), {}, "r") or "")

    def test_creds_file_written_from_environment(self):
        m = load_p2m(Path(tempfile.mkdtemp()), pasted=None)
        self.assertFalse(m.CREDS.exists())
        with mock.patch.dict(os.environ, {"PROVE2ME_CREDENTIALS": PASTED}):
            m.ensure_creds_file()
        self.assertEqual(m.CREDS.read_text(), PASTED)
        self.assertEqual(m.CREDS.stat().st_mode & 0o777, 0o600)

    def test_separate_password(self):
        with mock.patch.dict(os.environ, {"AUTOPROVER_ENCRYPTION_SECRET": "separate-pw"}):
            self.renew(FakeApi(self.m))
            blob = json.loads(self.m.KEY_FILE.read_text())
            self.assertIsNone(self.m.unseal(blob, PASTED.encode()))  # sealed with the separate one
            self.assertIsNotNone(self.m.unseal(blob, b"separate-pw"))
            # The pasted key can now be removed: the renewed key alone logs in.
            self.m.CREDS.unlink()
            self.assertEqual(self.m.stored_key()["api_key"], "p2m_minted_1")
            real, fake = self.m.Api(), FakeApi(self.m)
            real._http = fake._http
            real._refresh()
            self.assertEqual([c[2] for c in fake.calls], ["p2m_minted_1"])
        # Without the separate secret and without the pasted key, nothing decrypts.
        self.assertIsNone(self.m.stored_key())

    def test_switch_to_separate_password_keeps_working(self):
        self.renew(FakeApi(self.m))  # sealed with the pasted key
        with mock.patch.dict(os.environ, {"AUTOPROVER_ENCRYPTION_SECRET": "separate-pw"}):
            self.assertEqual(self.m.stored_key()["api_key"], "p2m_minted_1")  # still decrypts
            self.renew(FakeApi(self.m))
            blob = json.loads(self.m.KEY_FILE.read_text())
            self.assertIsNotNone(self.m.unseal(blob, b"separate-pw"))  # re-sealed

    def test_no_credentials_at_all_exits_3(self):
        self.m.CREDS.unlink()
        real = self.m.Api()
        real._http = FakeApi(self.m)._http
        with self.assertRaises(SystemExit) as e:
            real._refresh()
        self.assertEqual(e.exception.code, 3)

    def test_refuses_without_data_repo(self):
        (self.tmp / "data" / "autoprover.config.json").unlink()
        api = FakeApi(self.m)
        self.assertEqual(self.renew(api), 0)
        self.assertEqual(api.minted, 0)


class NewSecretTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.m = load_p2m(self.tmp)

    def run_cmd(self, file=None):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.m.cmd_new_secret(None, {}, types.SimpleNamespace(file=file))
        return out.getvalue()

    def test_clipboard_gets_line_stdout_never_does(self):
        sent = []
        def fake_run(cmd, input=None, **kw):
            sent.append((cmd, input.decode()))
            return types.SimpleNamespace(returncode=1 if cmd[0] == "broken" else 0)
        with mock.patch.object(self.m, "_clipboard_commands", return_value=[["broken"], ["pbcopy"]]), \
             mock.patch.object(self.m.subprocess, "run", fake_run):
            out = self.run_cmd()
        self.assertEqual([c[0][0] for c in sent], ["broken", "pbcopy"])  # falls through to the next tool
        line = sent[-1][1]
        self.assertRegex(line, r"^AUTOPROVER_ENCRYPTION_SECRET=[A-Za-z0-9_-]{43}$")
        self.assertIn("clipboard (pbcopy)", out)
        self.assertNotIn(line.split("=", 1)[1], out)

    def test_private_file_when_no_clipboard(self):
        f = self.tmp / "secret.txt"
        with mock.patch.object(self.m, "_clipboard_commands", return_value=[]), \
             mock.patch.object(self.m.Path, "home", return_value=self.tmp):
            out = self.run_cmd()  # no tools: falls back to ~/autoprover-secret.txt
        self.assertIn(str(self.tmp / "autoprover-secret.txt"), out)
        self.assertTrue((self.tmp / "autoprover-secret.txt").exists())
        out = self.run_cmd(file=str(f))  # --file skips the clipboard
        line = f.read_text().strip()
        self.assertRegex(line, r"^AUTOPROVER_ENCRYPTION_SECRET=[A-Za-z0-9_-]{43}$")
        self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(line.split("=", 1)[1], out)

    def test_clipboard_order(self):
        with mock.patch.object(self.m.sys, "platform", "linux"), \
             mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}), \
             mock.patch("shutil.which", lambda c: "/bin/" + c):
            cmds = [c[0] for c in self.m._clipboard_commands()]
        self.assertEqual(cmds, ["clip.exe", "wl-copy", "xclip", "xsel"])


if __name__ == "__main__":
    unittest.main()
