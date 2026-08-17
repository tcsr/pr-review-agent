from __future__ import annotations

from app.http import raise_for_status


def post_json(client, path: str, payload: dict) -> dict:
    resp = client.post(path, json=payload)
    raise_for_status(resp)
    return resp.json()
