#!/usr/bin/env python3
"""Brand-key HTTP client for the QANT brand-blog API.

The /blog skill's only data surface: every author read, draft submission,
hero-image attach, rewrite-queue read, and post-rewrite cleanup goes over
``https://api[-stg].qant.au/brand/blog/*`` authenticated with the brand's
own key (``X-Brand-Key``). Direct Firestore access (the qant-blog-drafts
project + service-account key) was retired 2026-06.

Per-brand config comes from the brand directory's env file
(``/Users/adam/Projects/qant/brands/<slug>/.env`` → ``.env.stg`` →
``.env.dev``, first existing wins):

* ``NEXT_PUBLIC_BRAND_KEY``  — the brk_ key (also used by the brand site)
* ``NEXT_PUBLIC_BRAND_ENV``  — ``stg``/``dev`` → api-stg.qant.au,
  anything else → api.qant.au

``QANT_BLOG_API_URL`` (env var) overrides the derived API base when set —
useful for local API testing.

Stdlib only (urllib) — no requests/google-cloud deps.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

QANT_BRANDS_ROOT = Path("/Users/adam/Projects/qant/brands")

# Tried in order; first existing file wins (matches load_brand_context.py).
ENV_FILE_PRECEDENCE: tuple[str, ...] = (".env", ".env.stg", ".env.dev")

_API_URLS = {
    "stg": "https://api-stg.qant.au",
    "dev": "https://api-stg.qant.au",
}
_API_URL_PROD = "https://api.qant.au"


class ApiError(RuntimeError):
    """Non-2xx API response. ``status`` is the HTTP code; ``detail`` the
    parsed ``detail`` payload (str or dict) when the body was JSON."""

    def __init__(self, status: int, detail: Any):
        self.status = status
        self.detail = detail
        super().__init__(f"API error {status}: {detail}")


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal `.env` parser (KEY=VALUE, quotes, comments, `export `)."""
    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value and value[0] not in {'"', "'"} and " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def brand_api_config(brand_slug: str, *, brands_root: Path | None = None) -> tuple[str, str]:
    """Resolve (api_url, brand_key) for a brand from its on-disk env file.

    Raises RuntimeError with an actionable message when the brand dir,
    env file, or key is missing.
    """
    root = brands_root if brands_root is not None else QANT_BRANDS_ROOT
    brand_dir = root / brand_slug
    if not brand_dir.is_dir():
        raise RuntimeError(f"brand directory not found: {brand_dir}")

    env: dict[str, str] = {}
    for fname in ENV_FILE_PRECEDENCE:
        candidate = brand_dir / fname
        if candidate.is_file():
            env = _parse_env_file(candidate)
            break
    else:
        raise RuntimeError(
            f"no env file under {brand_dir} (tried {', '.join(ENV_FILE_PRECEDENCE)})"
        )

    brand_key = env.get("NEXT_PUBLIC_BRAND_KEY") or ""
    if not brand_key.startswith("brk_"):
        raise RuntimeError(
            f"NEXT_PUBLIC_BRAND_KEY missing or malformed in {brand_dir} env — "
            f"issue one in Axiom (Instances → Brands → {brand_slug} → Keys)."
        )

    api_url = os.environ.get("QANT_BLOG_API_URL") or _API_URLS.get(
        env.get("NEXT_PUBLIC_BRAND_ENV", ""), _API_URL_PROD,
    )
    return api_url.rstrip("/"), brand_key


def request(
    brand_slug: str,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    none_on_404: bool = False,
    timeout: int = 60,
    brands_root: Path | None = None,
) -> Any:
    """One brand-key API call. Returns the parsed JSON body (None for 204).

    ``none_on_404=True`` maps a 404 to None instead of raising — used for
    optional resources (hero image, idempotent deletes).
    """
    api_url, brand_key = brand_api_config(brand_slug, brands_root=brands_root)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{api_url}{path}",
        method=method.upper(),
        data=data,
        headers={
            "X-Brand-Key": brand_key,
            "Content-Type": "application/json",
            # Cloudflare's bot rules reject urllib's default Python-urllib UA.
            "User-Agent": "qant-blog-skill/2.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if e.code == 404 and none_on_404:
            return None
        try:
            detail = json.loads(e.read().decode("utf-8", "replace")).get("detail")
        except Exception:  # noqa: BLE001 — non-JSON error body
            detail = e.reason
        raise ApiError(e.code, detail) from None


def list_brands_with_keys(*, brands_root: Path | None = None) -> list[str]:
    """Brand slugs under the brands root whose env file carries a brand key.

    Used by ``--all-brands`` queue drains: each brand is queried with its
    own key (there is no cross-brand credential any more).
    """
    root = brands_root if brands_root is not None else QANT_BRANDS_ROOT
    out: list[str] = []
    if not root.is_dir():
        return out
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        try:
            brand_api_config(p.name, brands_root=root)
        except RuntimeError:
            continue
        out.append(p.name)
    return out
