from __future__ import annotations

import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import make_session_token, verify_password, verify_session_token

_TEMPLATES = Jinja2Templates(
    directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_templates"))


def build_ui_router(settings, queue) -> APIRouter:
    router = APIRouter(prefix="/admin")
    secret = settings.ui.session_secret

    def _user(request: Request):
        return verify_session_token(request.cookies.get("session"), secret)

    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return _TEMPLATES.TemplateResponse(request, "login.html", {})

    @router.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...)):
        ok = (username == settings.ui.admin_user
              and verify_password(password, settings.ui.admin_password_hash))
        if not ok:
            return _TEMPLATES.TemplateResponse(
                request, "login.html", {"error": "Invalid credentials"}, status_code=401)
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie("session", make_session_token(username, secret),
                        httponly=True, samesite="lax", secure=settings.ui.cookie_secure,
                        max_age=settings.ui.cookie_max_age)
        return resp

    @router.get("/logout")
    def logout():
        resp = RedirectResponse("/admin/login", status_code=303)
        resp.delete_cookie("session")
        return resp

    @router.get("", response_class=HTMLResponse)
    def dashboard(request: Request):
        if not _user(request):
            return RedirectResponse("/admin/login", status_code=303)
        return _TEMPLATES.TemplateResponse(request, "dashboard.html",
            {"stats": queue.stats(), "jobs": queue.list_jobs()})

    return router
