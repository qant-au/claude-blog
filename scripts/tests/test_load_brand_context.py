"""Behavioral tests for scripts/load_brand_context.py.

Stdlib + pytest only. No network. All file ops use tmp_path. Never depends
on the live qant brand directories — every test builds a synthetic brand
under a tmp dir and passes `--brands-root`.

Tests the POST-E4.5 contract: the loader returns
``{brand_slug, brand_dir, env_file, brand_domain, brand_identity}``.
The retired surface (``brand_key`` / ``api_url`` outputs, ``--staging`` /
``--development`` flags, disk author enumeration) is asserted ABSENT —
see the canonical spec §7 retirement table.
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


def test_loads_core_context_shape(tmp_path: Path):
    mod = _import_helper()
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env": "NEXT_PUBLIC_BRAND_DOMAIN=acme.example.com\n"},
        seo_yml="brand: acme\ndisplay_name: Acme Cyber\n",
    )
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    assert ctx["brand_slug"] == "acme"
    assert ctx["brand_dir"].endswith("/acme")
    assert ctx["env_file"].endswith("/.env")
    assert ctx["brand_domain"] == "acme.example.com"
    assert ctx["brand_identity"]["display_name"] == "Acme Cyber"


def test_retired_fields_are_absent(tmp_path: Path):
    """brand_key / api_url were retired in E4.5 — the SA env-var pair
    replaced them. They must never reappear in the payload."""
    mod = _import_helper()
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env": "BRAND_KEY=brk_legacy\nAPI_URL=https://api.example\n"},
    )
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    assert "brand_key" not in ctx
    assert "api_url" not in ctx
    assert "authors" not in ctx  # disk enumeration retired in F-post


def test_env_flags_are_retired():
    """--staging / --development kwargs were dropped in E4.5."""
    mod = _import_helper()
    with pytest.raises(TypeError):
        mod.load_brand_context("acme", staging=True)
    with pytest.raises(TypeError):
        mod.load_brand_context("acme", development=True)


def test_env_file_precedence_env_first(tmp_path: Path):
    mod = _import_helper()
    _make_brand(
        tmp_path,
        "acme",
        env_files={
            ".env":     "NEXT_PUBLIC_BRAND_DOMAIN=prod.example.com\n",
            ".env.stg": "NEXT_PUBLIC_BRAND_DOMAIN=stg.example.com\n",
        },
    )
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    assert ctx["env_file"].endswith("/.env")
    assert ctx["brand_domain"] == "prod.example.com"


def test_missing_env_file_is_soft(tmp_path: Path):
    """No env file is a soft miss — brand_domain falls back to the YAML's
    canonical.marketing host."""
    mod = _import_helper()
    _make_brand(
        tmp_path,
        "acme",
        seo_yml=(
            "brand: acme\n"
            "canonical:\n"
            "  marketing: https://acme.example.com/\n"
        ),
    )
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    assert ctx["env_file"] is None
    assert ctx["brand_domain"] == "acme.example.com"


def test_missing_brand_raises(tmp_path: Path):
    mod = _import_helper()
    with pytest.raises(FileNotFoundError):
        mod.load_brand_context("nope", brands_root=tmp_path)


def test_env_parser_handles_quotes_comments_and_export(tmp_path: Path):
    mod = _import_helper()
    body = (
        "# comment line\n"
        "\n"
        "NEXT_PUBLIC_BRAND_DOMAIN=\"quoted.example.com\"\n"
        "export OTHER_VAR=stg\n"
        "STRAY_INLINE=value # trailing comment\n"
    )
    _make_brand(tmp_path, "acme", env_files={".env": body})
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    assert ctx["brand_domain"] == "quoted.example.com"


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
    _make_brand(tmp_path, "acme", seo_yml=seo)
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    identity = ctx["brand_identity"]
    assert identity["display_name"] == "Acme Cyber"
    assert identity["primary_author"] == "adam"
    assert identity["canonical"]["marketing"] == "https://acme.example.com"
    assert identity["target_keywords"] == ["cyber hygiene", "SMB security"]


def test_missing_seo_yml_is_silent(tmp_path: Path):
    mod = _import_helper()
    _make_brand(tmp_path, "acme", env_files={".env": "X=1\n"})
    ctx = mod.load_brand_context("acme", brands_root=tmp_path)
    assert ctx["brand_identity"] == {}


def test_list_brands_enumerates_seo_yml_dirs(tmp_path: Path):
    mod = _import_helper()
    _make_brand(tmp_path, "acme", seo_yml="display_name: Acme\n")
    _make_brand(tmp_path, "zeta", seo_yml="brand: zeta\n")
    _make_brand(tmp_path, "no-yml")  # excluded — no .brand-seo.yml
    out = mod.list_brands(tmp_path)
    assert out == [
        {"slug": "acme", "display_name": "Acme"},
        {"slug": "zeta", "display_name": "zeta"},
    ]


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


def test_cli_emits_context_json(tmp_path: Path):
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env": "NEXT_PUBLIC_BRAND_DOMAIN=acme.example.com\n"},
        seo_yml="display_name: Acme\n",
    )
    proc = _run(["--brand", "acme", "--brands-root", str(tmp_path)])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["brand_slug"] == "acme"
    assert payload["brand_domain"] == "acme.example.com"
    assert "brand_key" not in payload
    assert "api_url" not in payload


def test_cli_list_brands(tmp_path: Path):
    _make_brand(tmp_path, "acme", seo_yml="display_name: Acme\n")
    proc = _run(["--list-brands", "--brands-root", str(tmp_path)])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload == [{"slug": "acme", "display_name": "Acme"}]


def test_cli_staging_flag_is_gone(tmp_path: Path):
    _make_brand(tmp_path, "acme", seo_yml="display_name: Acme\n")
    proc = _run(["--brand", "acme", "--staging", "--brands-root", str(tmp_path)])
    assert proc.returncode != 0  # argparse rejects the retired flag


def test_cli_missing_brand_exits_nonzero(tmp_path: Path):
    proc = _run(["--brand", "nope", "--brands-root", str(tmp_path)])
    assert proc.returncode != 0
    assert "Error" in proc.stderr


def test_get_author_returns_the_full_firestore_doc():
    """--get-author is the skill's ONLY author surface: it must return every
    voice field from qant-blog-drafts, so the drafting/rewrite prompts never
    fall back to stale on-disk author-profile-*.json exports."""
    mod = _import_helper()

    doc = {
        "name":            "Adam Burgess",
        "byline":          "Founder, Red Bridge Cyber",
        "bio":             "Thirty years in Australian ICT.",
        "target_audience": "Australian SMB owner-operators.",
        "locale":          "en-AU",
        "pronoun_stance":  "first_person_singular",
        "register":        "sharp",
        "banned_phrases":  ["journey", "leverage"],
        "signature_moves": ["answer-first"],
        "writing_style":   "Plain English. No corporate-speak.",
        "brand_slug":      "redbridgecyber",
    }

    class _Snap:
        exists = True
        id = "adam-burgess"

        @staticmethod
        def to_dict():
            return dict(doc)

    class _Ref:
        def get(self):
            return _Snap()

    class _Chain:
        def collection(self, _name):
            return self

        def document(self, _name):
            return self

        def get(self):
            return _Snap()

    out = mod.get_author_from_drafts("redbridgecyber", "adam-burgess", _client=_Chain())
    assert out["slug"] == "adam-burgess"
    for field in (
        "name", "byline", "bio", "target_audience", "locale",
        "pronoun_stance", "register", "banned_phrases",
        "signature_moves", "writing_style",
    ):
        assert out[field] == doc[field], field


def test_get_author_missing_points_at_axiom():
    """A missing author must fail loudly with the Axiom management path,
    not silently fall back to disk files."""
    mod = _import_helper()

    class _Snap:
        exists = False

        @staticmethod
        def to_dict():
            return {}

    class _Chain:
        def collection(self, _name):
            return self

        def document(self, _name):
            return self

        def get(self):
            return _Snap()

    with pytest.raises(LookupError) as exc:
        mod.get_author_from_drafts("redbridgecyber", "ghost", _client=_Chain())
    assert "Axiom" in str(exc.value)
    assert "ghost" in str(exc.value)


def test_cli_get_author_requires_brand(tmp_path: Path):
    proc = _run(["--get-author", "adam-burgess", "--brands-root", str(tmp_path)])
    assert proc.returncode == 2
    assert "--brand" in proc.stderr


def test_cli_get_author_without_env_exits_2(tmp_path: Path):
    proc = subprocess.run(
        [sys.executable, str(HELPER), "--get-author", "adam-burgess",
         "--brand", "redbridgecyber", "--brands-root", str(tmp_path)],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin"},  # no QANT_BLOG_DRAFTS_* vars
    )
    assert proc.returncode == 2
    assert "QANT_BLOG_DRAFTS" in proc.stderr


def test_cli_does_not_leak_env_secrets(tmp_path: Path):
    """Legacy env files may still carry BRAND_KEY lines; the loader must
    not echo their values anywhere in its output."""
    _make_brand(
        tmp_path,
        "acme",
        env_files={".env": "BRAND_KEY=brk_very_secret\nNEXT_PUBLIC_BRAND_DOMAIN=a.example\n"},
    )
    proc = _run(["--brand", "acme", "--brands-root", str(tmp_path)])
    assert proc.returncode == 0
    assert "brk_very_secret" not in proc.stdout
    assert "brk_very_secret" not in proc.stderr
