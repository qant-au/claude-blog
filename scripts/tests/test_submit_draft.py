"""Behavioral tests for scripts/submit_draft.py.

A short-lived stdlib HTTP server runs in a thread on a random port; tests
configure the script's API URL to point at it. No external network.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "submit_draft.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("submit_draft", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _StubServer:
    """A tiny HTTP server that records requests and replies per a script.

    `script` is a list of (status, body_dict) pairs. The Nth POST gets the
    Nth scripted response. If the script runs out, the server returns 500.
    """

    def __init__(self, script: list[tuple[int, dict[str, Any] | str]]):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a, **kw):
                pass  # silence

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    body = {"_raw": raw.decode("utf-8", errors="replace")}
                outer.calls.append(
                    {
                        "path": self.path,
                        "headers": {k: v for k, v in self.headers.items()},
                        "body": body,
                    }
                )
                if outer.script:
                    status, response_body = outer.script.pop(0)
                else:
                    status, response_body = 500, {"error": "no script left"}
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if isinstance(response_body, dict):
                    payload = json.dumps(response_body).encode("utf-8")
                else:
                    payload = response_body.encode("utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_StubServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _make_payload() -> dict[str, Any]:
    return {
        "brand_slug": "redbridgecyber",
        "title": "Test Article",
        "slug": "test-article",
        "category": "guides",
        "target_keyword": "cyber hygiene",
        "author": {
            "slug": "adam",
            "name": "Adam Burgess",
            "byline": "...",
            "bio": "...",
        },
        "hero_image_url": "https://example.com/hero.jpg",
        "og": {"title": "...", "description": "...", "image": "..."},
        "body_markdown": "# Test\n\nbody",
        "flow_score": 92,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# In-process tests
# ---------------------------------------------------------------------------


def test_happy_path_returns_response_body():
    mod = _import_helper()
    with _StubServer([(200, {"draft_id": "abc123", "status": "draft"})]) as srv:
        resp = mod.submit(srv.url, "brk_test", "redbridgecyber", _make_payload())
    assert resp == {"draft_id": "abc123", "status": "draft"}
    assert len(srv.calls) == 1
    call = srv.calls[0]
    assert call["path"] == "/private/blog/drafts"
    assert call["headers"]["Authorization"] == "Bearer brk_test"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["body"]["brand_slug"] == "redbridgecyber"
    assert call["body"]["title"] == "Test Article"


def test_4xx_surfaces_immediately_no_retry():
    mod = _import_helper()
    with _StubServer([(400, {"error": "missing field"})]) as srv:
        with pytest.raises(mod.SubmitError) as exc:
            mod.submit(srv.url, "brk_test", "redbridgecyber", _make_payload())
    assert exc.value.status == 400
    assert "missing field" in exc.value.body
    # Only one call — no retry on HTTP errors.
    assert len(srv.calls) == 1


def test_5xx_surfaces_immediately_no_retry():
    mod = _import_helper()
    with _StubServer([(500, {"error": "boom"})]) as srv:
        with pytest.raises(mod.SubmitError) as exc:
            mod.submit(srv.url, "brk_test", "redbridgecyber", _make_payload())
    assert exc.value.status == 500
    assert len(srv.calls) == 1


def test_retries_once_on_transient_network_error(monkeypatch):
    mod = _import_helper()
    calls = {"n": 0}

    real_do_post = mod._do_post
    server_holder: list[_StubServer] = []

    def flaky(url, brand_key, body, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            import socket
            raise socket.timeout("simulated timeout")
        return real_do_post(url, brand_key, body, timeout)

    monkeypatch.setattr(mod, "_do_post", flaky)

    with _StubServer([(200, {"draft_id": "ok"})]) as srv:
        server_holder.append(srv)
        resp = mod.submit(
            srv.url,
            "brk_test",
            "redbridgecyber",
            _make_payload(),
            retry_backoff=0.0,
        )
    assert resp == {"draft_id": "ok"}
    assert calls["n"] == 2


def test_gives_up_after_one_retry(monkeypatch):
    mod = _import_helper()
    calls = {"n": 0}

    def always_fail(url, brand_key, body, timeout):
        calls["n"] += 1
        import socket
        raise socket.timeout(f"simulated {calls['n']}")

    monkeypatch.setattr(mod, "_do_post", always_fail)

    with pytest.raises(mod.SubmitError) as exc:
        mod.submit(
            "http://127.0.0.1:1",
            "brk_test",
            "redbridgecyber",
            _make_payload(),
            retry_backoff=0.0,
        )
    assert calls["n"] == 2
    assert exc.value.status == 0
    assert "transient" in exc.value.body


def test_rejects_non_absolute_api_url():
    mod = _import_helper()
    with pytest.raises(ValueError):
        mod.submit("api.example.com", "brk", "slug", _make_payload())


def test_sets_brand_slug_from_arg_when_payload_missing():
    mod = _import_helper()
    payload = _make_payload()
    payload.pop("brand_slug")
    with _StubServer([(201, {"draft_id": "x"})]) as srv:
        mod.submit(srv.url, "brk_test", "from-arg", payload)
        assert srv.calls[0]["body"]["brand_slug"] == "from-arg"


# ---------------------------------------------------------------------------
# CLI tests (subprocess)
# ---------------------------------------------------------------------------


def _write_payload(tmp_path: Path) -> Path:
    p = tmp_path / "draft.json"
    p.write_text(json.dumps(_make_payload()), encoding="utf-8")
    return p


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_happy_path_exits_zero_and_prints_response(tmp_path: Path):
    payload_path = _write_payload(tmp_path)
    with _StubServer([(201, {"draft_id": "abc", "status": "draft"})]) as srv:
        proc = _run_cli(
            [
                "--api-url",
                srv.url,
                "--brand-key",
                "brk_test",
                "--brand-slug",
                "redbridgecyber",
                "--payload",
                str(payload_path),
            ]
        )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["draft_id"] == "abc"
    # brand_key never appears in stdout or stderr.
    assert "brk_test" not in proc.stdout
    assert "brk_test" not in proc.stderr


def test_cli_4xx_exits_one(tmp_path: Path):
    payload_path = _write_payload(tmp_path)
    with _StubServer([(403, "forbidden brand key")]) as srv:
        proc = _run_cli(
            [
                "--api-url",
                srv.url,
                "--brand-key",
                "brk_test",
                "--brand-slug",
                "redbridgecyber",
                "--payload",
                str(payload_path),
            ]
        )
    assert proc.returncode == 1
    assert "403" in proc.stderr
    assert "brk_test" not in proc.stderr


def test_cli_bad_payload_exits_two(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    proc = _run_cli(
        [
            "--api-url",
            "http://127.0.0.1:1",
            "--brand-key",
            "brk_test",
            "--brand-slug",
            "redbridgecyber",
            "--payload",
            str(bad),
        ]
    )
    assert proc.returncode == 2
    assert "not valid JSON" in proc.stderr
