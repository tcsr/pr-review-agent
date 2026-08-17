from __future__ import annotations

import httpx

from app.errors import AdapterError


def build_client(base_url: str, headers: dict[str, str], transport=None) -> httpx.Client:
    return httpx.Client(base_url=base_url, headers=headers, transport=transport,
                        timeout=30.0)


def raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 300:
        raise AdapterError(resp.status_code, resp.text)
