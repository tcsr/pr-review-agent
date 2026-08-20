from __future__ import annotations

import json

from fastapi import FastAPI, Request, Response

from app.config import find_repo, resolve_tasks
from app.ingress.events import parse_github_event, parse_gitlab_event
from app.ingress.security import verify_github_signature, verify_gitlab_token


def create_app(settings, queue, verify: bool = True) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/webhook/{platform}")
    async def webhook(platform: str, request: Request):
        body = await request.body()
        secret = settings.ingress.webhook_secret
        if platform == "github":
            if verify and secret and not verify_github_signature(
                    secret, body, request.headers.get("X-Hub-Signature-256")):
                return Response(status_code=401)
            parse = lambda p: parse_github_event(p, request.headers.get("X-GitHub-Event"))
        elif platform == "gitlab":
            if verify and secret and not verify_gitlab_token(
                    secret, request.headers.get("X-Gitlab-Token")):
                return Response(status_code=401)
            parse = lambda p: parse_gitlab_event(p, request.headers.get("X-Gitlab-Event"))
        else:
            return Response(status_code=404)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return Response(status_code=400)
        event = parse(payload)
        if event is None:
            return {"enqueued": 0}
        repo_cfg = find_repo(settings, event.platform.value, event.repo)
        if repo_cfg is None:
            return {"enqueued": 0}
        if event.action == "comment":
            handle = settings.bot_handle
            if handle and event.comment_author == handle:
                return {"enqueued": 0}
            if not handle or f"@{handle}".lower() not in (event.comment_body or "").lower():
                return {"enqueued": 0}
            jobs = queue.enqueue_event(event, ["qa_reply"])
            return {"enqueued": len(jobs)}
        jobs = queue.enqueue_event(event, resolve_tasks(settings, repo_cfg))
        return {"enqueued": len(jobs)}

    if settings.ui.enabled:
        from app.api import build_api_router
        from app.ui import build_ui_router
        app.include_router(build_api_router(settings, queue))
        app.include_router(build_ui_router(settings, queue))

    return app
