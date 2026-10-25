import bcrypt
from flask import Blueprint, redirect, render_template, request, session, url_for
from flask.typing import ResponseReturnValue

from app import config

bp = Blueprint("auth", __name__)

_OPEN_ENDPOINTS = {"auth.login", "static"}


def _safe_next(target: str | None) -> str:
    # Relative paths only, so ?next= can't bounce to another site.
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("library.index")


@bp.before_app_request
def require_login() -> ResponseReturnValue | None:
    if request.endpoint in _OPEN_ENDPOINTS or session.get("user"):
        return None
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))


@bp.route("/login", methods=["GET", "POST"])
def login() -> ResponseReturnValue:
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "").encode()
        # Always run the slow hash check, so a wrong username isn't a free guess.
        password_ok = bcrypt.checkpw(password, config.AUTH_PASSWORD_HASH.encode())
        if password_ok and username == config.AUTH_USERNAME:
            session.clear()
            session.permanent = True
            session["user"] = username
            return redirect(_safe_next(request.args.get("next")))
        error = "Wrong username or password."
    return render_template("login.html", error=error), 401 if error else 200


@bp.route("/logout", methods=["POST"])
def logout() -> ResponseReturnValue:
    session.clear()
    return redirect(url_for("auth.login"))
