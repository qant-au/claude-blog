"""Behavioral tests for scripts/load_brand_context.py.

Stdlib + pytest only. No network. All file ops use tmp_path. Never depends
on the live qant brand directories — every test builds a synthetic brand
under a tmp dir and passes `--brands-root`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "load_brand_context.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("load_brand_context", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _make_brand(
    root: Path,
    slug: str,
    env_files: dict[str, str] | None = None,
    seo_yml: str | None = None,
) -> Path:
    brand_dir = root / slug
    brand_dir.mkdir(parents=True, exist_ok=True)
    if env_files:
        for name, body in env_files.items():
            (brand_dir / name).write_text(body, encoding="utf-8")
    if seo_yml is not None:
        (brand_dir / ".brand-seo.yml").write_text(seo_yml, encoding="utf-8")
    return brand_dir


# ---------------------------------------------------------------------------
# In-process tests of the public function
# ---------------------------------------------------------------------------


def test_loads_brand_key_and_api_url_from_env(tmp_path: Path):
    mod = _import_helper()
    _make_brand(
        tmp_path,
        "acme",
        env_files={
            ".env.stg": (
                "# brand env\n"
                "BRAND_KEY=brk_abc123\n"
                "API_URL=https://api-stg.example.com\n"
            )
        },
        seo_yml="brand: acme\ndisplay_name: Acme Cyber\n",
    )
    ctx = mod.load_brand_context("acme", staging=True, brands_root=tmp_path)
    assert ctx["brand_slug"] == "acme"
    assert ctx["brand_key"] == "brk_abc123"
    assert ctx["api_url"] == "https://api-stg.example.com"
    assert ctx["env_file"].endswith(".env.stg")
    assert ctx["brand_identity"]["display_name"] == "Acme Cyber"


def test_accepts_next_public_brand_key(tmp_path: Path):
    mod = _import_helper()
    _make_brand(
        tmp_path,
        "rbc",
        env_files={
            ".env.stg": (
                "NEXT_PUBLIC_BRAND_ENV=stg\n"
                "NEXT_PUBLIC_BRAND_KEY=brk_xyz\n"
            )
        },
    )
    ctx = mod.load_brand_context("rbc", staging=True, brands_root=tmp_path)
    assert ctx["brand_key"] == "brk_xyz"
    # API URL derived from NEXT_PUBLIC_BRAND_ENV=stg → api-stg.qant.au
    assert ctx["api_url"] == "https://api-stg.qant.au"


def test_default_env_when_no_flag(tmp_path: Path):
    mod = _import_helper()
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env": "BRAND_KEY=brk_prod\nAPI_URL=https://api.example.com\n"},
    )
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    assert ctx["env_file"].endswith("/.env")
    assert ctx["api_url"] == "https://api.example.com"


def test_development_flag_picks_env_dev(tmp_path: Path):
    mod = _import_helper()
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env.dev": "BRAND_KEY=brk_dev\n"},
    )
    ctx = mod.load_brand_context("acme", development=True, brands_root=tmp_path)
    assert ctx["env_file"].endswith(".env.dev")
    # No API_URL in env → fallback to dev default.
    assert ctx["api_url"] == "http://localhost:8000"


def test_missing_brand_raises(tmp_path: Path):
    mod = _import_helper()
    with pytest.raises(FileNotFoundError):
        mod.load_brand_context("nope", brands_root=tmp_path)


def test_missing_env_file_raises(tmp_path: Path):
    mod = _import_helper()
    _make_brand(tmp_path, "acme", env_files={".env": "BRAND_KEY=x\n"})
    # We ask for staging but only `.env` exists.
    with pytest.raises(FileNotFoundError):
        mod.load_brand_context("acme", staging=True, brands_root=tmp_path)


def test_missing_brand_key_raises(tmp_path: Path):
    mod = _import_helper()
    _make_brand(tmp_path, "acme", env_files={".env": "API_URL=https://x.example\n"})
    with pytest.raises(KeyError):
        mod.load_brand_context("acme", brands_root=tmp_path)


def test_env_parser_handles_quotes_comments_and_export(tmp_path: Path):
    mod = _import_helper()
    body = (
        "# comment line\n"
        "\n"
        "BRAND_KEY=\"brk_quoted\"\n"
        "API_URL='https://api.example.com'\n"
        "export NEXT_PUBLIC_BRAND_ENV=stg\n"
        "STRAY_INLINE=value # trailing comment\n"
    )
    _make_brand(tmp_path, "acme", env_files={".env": body})
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    assert ctx["brand_key"] == "brk_quoted"
    assert ctx["api_url"] == "https://api.example.com"


def test_seo_yml_extracts_canonical_and_target_keywords(tmp_path: Path):
    mod = _import_helper()
    seo = (
        "brand: acme\n"
        "display_name: Acme Cyber\n"
        "primary_author: adam\n"
        "canonical:\n"
        "  marketing: https://acme.example.com\n"
        "target_keywords:\n"
        "  - cyber hygiene\n"
        "  - \"SMB security\"\n"
    )
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env": "BRAND_KEY=brk_x\n"},
        seo_yml=seo,
    )
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    identity = ctx["brand_identity"]
    assert identity["display_name"] == "Acme Cyber"
    assert identity["primary_author"] == "adam"
    assert identity["canonical"]["marketing"] == "https://acme.example.com"
    assert identity["target_keywords"] == ["cyber hygiene", "SMB security"]


def test_missing_seo_yml_is_silent(tmp_path: Path):
    mod = _import_helper()
    _make_brand(tmp_path, "acme", env_files={".env": "BRAND_KEY=brk_x\n"})
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    assert ctx["brand_identity"] == {}


def test_staging_and_development_mutually_exclusive(tmp_path: Path):
    mod = _import_helper()
    _make_brand(tmp_path, "acme", env_files={".env": "BRAND_KEY=brk_x\n"})
    with pytest.raises(ValueError):
        mod.load_brand_context(
            "acme", staging=True, development=True, brands_root=tmp_path
        )


# ---------------------------------------------------------------------------
# CLI tests (subprocess)
# ---------------------------------------------------------------------------


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_emits_json_with_brand_key(tmp_path: Path):
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env.stg": "BRAND_KEY=brk_secret\nAPI_URL=https://api.example\n"},
        seo_yml="display_name: Acme\n",
    )
    proc = _run(
        [
            "--brand",
            "acme",
            "--staging",
            "--brands-root",
            str(tmp_path),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["brand_key"] == "brk_secret"
    assert payload["api_url"] == "https://api.example"


def test_cli_redact_key_zeroes_key(tmp_path: Path):
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env": "BRAND_KEY=brk_secret\n"},
    )
    proc = _run(
        [
            "--brand",
            "acme",
            "--redact-key",
            "--brands-root",
            str(tmp_path),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["brand_key"] is None
    # Plain-text scan: secret must not appear anywhere in stdout.
    assert "brk_secret" not in proc.stdout


def test_cli_missing_brand_exits_nonzero(tmp_path: Path):
    proc = _run(
        [
            "--brand",
            "nope",
            "--brands-root",
            str(tmp_path),
        ]
    )
    assert proc.returncode != 0
    assert "Error" in proc.stderr


def test_cli_does_not_leak_key_to_stderr(tmp_path: Path):
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env": "BRAND_KEY=brk_very_secret\n"},
    )
    proc = _run(
        [
            "--brand",
            "acme",
            "--brands-root",
            str(tmp_path),
        ]
    )
    assert proc.returncode == 0
    assert "brk_very_secret" not in proc.stderr
    # And it IS in stdout (the legitimate emit path).
    assert "brk_very_secret" in proc.stdout
