"""Behavioral tests for scripts/qant_api.py::brand_api_config.

Locks in the production-only contract: the /blog skill resolves the
production AU API base (``https://api-au.qant.au``) and reads the brand key
from ``.env.prod`` in preference to ``.env``; staging env files are never
read. Stdlib + pytest only; no network — every test builds a synthetic brand
under tmp_path and passes ``brands_root``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "qant_api.py"

PROD_URL = "https://api-au.qant.au"


def _import_helper():
    spec = importlib.util.spec_from_file_location("qant_api", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _make_brand(root: Path, slug: str, env_files: dict[str, str]) -> Path:
    brand_dir = root / slug
    brand_dir.mkdir(parents=True, exist_ok=True)
    for name, body in env_files.items():
        (brand_dir / name).write_text(body, encoding="utf-8")
    return brand_dir


def test_resolves_prod_url_and_prod_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("QANT_BLOG_API_URL", raising=False)
    mod = _import_helper()
    _make_brand(tmp_path, "acme", {".env.prod": "NEXT_PUBLIC_BRAND_KEY=brk_prod\n"})
    api_url, brand_key = mod.brand_api_config("acme", brands_root=tmp_path)
    assert api_url == PROD_URL
    assert brand_key == "brk_prod"


def test_env_prod_takes_precedence_over_env(tmp_path: Path):
    mod = _import_helper()
    _make_brand(
        tmp_path,
        "acme",
        {
            ".env.prod": "NEXT_PUBLIC_BRAND_KEY=brk_prod\n",
            ".env":      "NEXT_PUBLIC_BRAND_KEY=brk_plain\n",
        },
    )
    _, brand_key = mod.brand_api_config("acme", brands_root=tmp_path)
    assert brand_key == "brk_prod"


def test_staging_env_file_is_never_read(tmp_path: Path):
    """A brand carrying only a staging env file has no usable config — the
    staging key must never be picked up."""
    mod = _import_helper()
    _make_brand(tmp_path, "acme", {".env.stg": "NEXT_PUBLIC_BRAND_KEY=brk_staging\n"})
    with pytest.raises(RuntimeError):
        mod.brand_api_config("acme", brands_root=tmp_path)


def test_override_env_var_changes_base_only(tmp_path: Path, monkeypatch):
    """QANT_BLOG_API_URL overrides the base for local API dev; the key still
    comes from .env.prod."""
    mod = _import_helper()
    _make_brand(tmp_path, "acme", {".env.prod": "NEXT_PUBLIC_BRAND_KEY=brk_prod\n"})
    monkeypatch.setenv("QANT_BLOG_API_URL", "http://localhost:8080")
    api_url, brand_key = mod.brand_api_config("acme", brands_root=tmp_path)
    assert api_url == "http://localhost:8080"
    assert brand_key == "brk_prod"


def test_missing_key_raises(tmp_path: Path):
    mod = _import_helper()
    _make_brand(tmp_path, "acme", {".env.prod": "NEXT_PUBLIC_BRAND_DOMAIN=acme.example\n"})
    with pytest.raises(RuntimeError):
        mod.brand_api_config("acme", brands_root=tmp_path)
