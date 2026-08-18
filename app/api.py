from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.auth import verify_session_token


def build_api_router(settings, queue) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _require(request: Request) -> str:
        user = verify_session_token(request.cookies.get("session"),
                                    settings.ui.session_secret)
        if not user:
            raise HTTPException(status_code=401)
        return user

    @router.get("/stats")
    def stats(request: Request):
        _require(request)
        return queue.stats()

    @router.get("/jobs")
    def jobs(request: Request):
        _require(request)
        return {"jobs": queue.list_jobs()}

    @router.get("/dead-letter")
    def dead_letter(request: Request):
        _require(request)
        return {"dead_letter": queue.list_dead_letter()}

    @router.get("/repos")
    def repos(request: Request):
        _require(request)
        return {"repos": [{"platform": r.platform.value, "full_name": r.full_name,
                           "tasks": r.tasks} for r in settings.repos]}

    @router.post("/jobs/{job_id}/rerun")
    def rerun(request: Request, job_id: int):
        _require(request)
        ok = queue.requeue(job_id)
        if not ok:
            raise HTTPException(status_code=404)
        return {"requeued": True}

    return router
