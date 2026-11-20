"""All pages and API routes. Written as plain Starlette handlers (the engine FastAPI
is built on) and plugged into the FastAPI app object in main.py."""
import hashlib
import os
import secrets
import uuid

from starlette.concurrency import run_in_threadpool as tp
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import (JSONResponse, PlainTextResponse, RedirectResponse,
                                 Response)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

import core
from core import (ALLOWED_EXT, APP_NAME, BASE_DIR, CATEGORIES, COURSES, FILENAME_RE,
                  MAX_UPLOAD, SEMESTERS, UNIVERSITIES, hash_password, now, safe_filename,
                  valid_identifier, verify_password)
from store import SupabaseStore, get_store

core.load_env()
store = get_store()
try:
    store.init()
    print("Storage:", store.kind)
except Exception as e:  # keep the site up; show a clear message in the logs
    print("STORAGE SETUP PROBLEM:", e)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ---- helpers ---------------------------------------------------------------
def csrf(request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_hex(16)
    return request.session["csrf"]


def flash(request, msg, cat="error"):
    request.session.setdefault("_flash", [])
    request.session["_flash"] = request.session["_flash"] + [[cat, msg]]


def render(request, name, status=200, **ctx):
    flashes = request.session.pop("_flash", [])
    tok = csrf(request)
    ctx.update(request=request, session=request.session, flashes=flashes,
               csrf_token=lambda: tok, APP_NAME=APP_NAME)
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def bad_token(request, form):
    return not secrets.compare_digest(str(request.session.get("csrf", "")), str(form.get("csrf", "x")))


def go(path):
    return RedirectResponse(path, status_code=303)


# ---- auth ------------------------------------------------------------------
async def index(request: Request):
    if "user" in request.session:
        return go("/admin" if request.session.get("role") == "admin" else "/dashboard")
    return go("/login")


async def login_get(request: Request):
    return render(request, "login.html", mode=request.query_params.get("mode", "signin"), ident="")


async def login_post(request: Request):
    form = await request.form()
    if bad_token(request, form):
        return PlainTextResponse("Invalid form token. Please reload the page.", status_code=400)
    ident = str(form.get("identifier", "")).strip()
    pw = str(form.get("password", ""))
    u = await tp(store.get_user, ident)
    # strict case-sensitive match
    if u and u["identifier"] == ident and verify_password(pw, u["password"]):
        csrf_old = request.session.get("csrf")
        request.session.clear()
        request.session.update(user=u["identifier"], role=u["role"], csrf=csrf_old or secrets.token_hex(16))
        return go("/")
    flash(request, "Wrong email/mobile or password. (Email is case-sensitive.)")
    return render(request, "login.html", 401, mode="signin", ident=ident)


async def signup_post(request: Request):
    form = await request.form()
    if bad_token(request, form):
        return PlainTextResponse("Invalid form token. Please reload the page.", status_code=400)
    ident = str(form.get("identifier", "")).strip()
    pw, pw2 = str(form.get("password", "")), str(form.get("confirm", ""))
    err = None
    if not valid_identifier(ident):
        err = "Enter a valid email (.com / .ac.in / .edu.in) or a 10-digit mobile number starting with 6-9."
    elif len(pw) < 6:
        err = "Password must be at least 6 characters."
    elif pw != pw2:
        err = "Passwords do not match."
    else:
        created = await tp(store.add_user, {"identifier": ident, "password": hash_password(pw),
                                            "role": "student", "created_at": now()})
        if not created:
            err = "This account already exists. Please sign in."
    if err:
        flash(request, err)
        return render(request, "login.html", 400, mode="signup", ident=ident)
    csrf_old = request.session.get("csrf")
    request.session.clear()
    request.session.update(user=ident, role="student", csrf=csrf_old or secrets.token_hex(16))
    return go("/dashboard")


async def logout(request: Request):
    request.session.clear()
    return go("/login")


# ---- student side ----------------------------------------------------------
async def dashboard(request: Request):
    if "user" not in request.session:
        return go("/login")
    cfg = {"universities": UNIVERSITIES, "courses": COURSES,
           "semesters": SEMESTERS, "categories": CATEGORIES}
    return render(request, "dashboard.html", cfg=cfg)


async def api_materials(request: Request):
    if "user" not in request.session:
        return JSONResponse({"error": "login required"}, status_code=401)
    out = []
    for m in await tp(store.list_materials):
        m = dict(m)
        m["url"] = "/files/" + m["file_path"]
        m["ext"] = os.path.splitext(m["file_path"])[1].lower().lstrip(".")
        out.append(m)
    return JSONResponse({"materials": out})


async def files(request: Request):
    if "user" not in request.session:
        return go("/login")
    name = request.path_params["name"]
    if not FILENAME_RE.match(name) or ".." in name:
        return PlainTextResponse("Not found", status_code=404)
    res = await tp(store.read_file, name)
    if not res:
        return PlainTextResponse("File not found", status_code=404)
    data, ctype = res
    return Response(data, media_type=ctype, headers={
        "Content-Disposition": 'inline; filename="%s"' % name,
        "Cache-Control": "private, max-age=3600"})


# ---- admin -----------------------------------------------------------------
def admin_guard(request):
    if "user" not in request.session:
        return go("/login")
    if request.session.get("role") != "admin":
        return PlainTextResponse("Admins only.", status_code=403)
    return None


async def admin_get(request: Request):
    blocked = admin_guard(request)
    if blocked:
        return blocked
    items = await tp(store.list_materials)
    return render(request, "admin.html", items=items, universities=UNIVERSITIES,
                  courses=COURSES, semesters=SEMESTERS, categories=CATEGORIES)


async def admin_post(request: Request):
    blocked = admin_guard(request)
    if blocked:
        return blocked
    form = await request.form()
    if bad_token(request, form):
        return PlainTextResponse("Invalid form token. Please reload the page.", status_code=400)
    uni, course, sem, cat = (form.get("university"), form.get("course"),
                             form.get("semester"), form.get("category"))
    subject, title = str(form.get("subject", "")).strip(), str(form.get("title", "")).strip()
    file = form.get("file")
    if uni not in [u["id"] for u in UNIVERSITIES] or course not in COURSES \
            or sem not in SEMESTERS or cat not in CATEGORIES:
        flash(request, "Invalid selection.")
    elif not subject or not title:
        flash(request, "Subject and title are required.")
    elif file is None or not getattr(file, "filename", ""):
        flash(request, "Please choose a file.")
    else:
        ext = os.path.splitext(file.filename)[1].lower()
        data = await file.read()
        if ext not in ALLOWED_EXT:
            flash(request, "Only .pdf, .pptx, .docx, .doc files are allowed.")
        elif len(data) > MAX_UPLOAD:
            flash(request, "File too large (max 25 MB).")
        elif not data:
            flash(request, "The file is empty.")
        else:
            mid = uuid.uuid4().hex[:10]
            fname = "%s_%s" % (mid, safe_filename(file.filename))
            meta = {"id": mid, "university": uni, "course": course, "semester": sem,
                    "subject": subject, "category": cat, "title": title, "uploaded_at": now()}
            try:
                await tp(store.add_material, meta, fname, data)
                flash(request, "Uploaded! It is now live for students.", "ok")
            except Exception as e:
                print("UPLOAD FAILED:", e)
                flash(request, "Upload failed: storage error. Check the server log.")
    return go("/admin")


async def admin_delete(request: Request):
    blocked = admin_guard(request)
    if blocked:
        return blocked
    form = await request.form()
    if bad_token(request, form):
        return PlainTextResponse("Invalid form token. Please reload the page.", status_code=400)
    await tp(store.delete_material, request.path_params["mid"])
    flash(request, "Deleted.", "ok")
    return go("/admin")


# ---- PWA / offline + health -------------------------------------------------
async def sw(request: Request):
    with open(os.path.join(BASE_DIR, "static", "js", "sw.js"), "rb") as f:
        return Response(f.read(), media_type="text/javascript", headers={"Cache-Control": "no-cache"})


async def manifest(request: Request):
    return JSONResponse({
        "name": APP_NAME, "short_name": APP_NAME, "start_url": "/dashboard",
        "display": "standalone", "background_color": "#0B1120", "theme_color": "#1a73e8",
        "icons": [{"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml",
                   "purpose": "any"}]})


async def healthz(request: Request):
    return PlainTextResponse("ok")


routes = [
    Route("/", index),
    Route("/login", login_get, methods=["GET"]),
    Route("/login", login_post, methods=["POST"]),
    Route("/signup", signup_post, methods=["POST"]),
    Route("/logout", logout),
    Route("/dashboard", dashboard),
    Route("/api/materials", api_materials),
    Route("/files/{name}", files),
    Route("/admin", admin_get, methods=["GET"]),
    Route("/admin", admin_post, methods=["POST"]),
    Route("/admin/delete/{mid}", admin_delete, methods=["POST"]),
    Route("/sw.js", sw),
    Route("/manifest.json", manifest),
    Route("/healthz", healthz),
    Mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static"),
]


def _secret_key():
    """Same key on every restart/replica, so logins keep working."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    if isinstance(store, SupabaseStore):
        return hashlib.sha256(("uc-session|" + store.key).encode()).hexdigest()
    path = os.path.join(store.dir, "secret.key")
    os.makedirs(store.dir, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


session_options = dict(secret_key=_secret_key(), max_age=60 * 60 * 24 * 30, same_site="lax",
                       https_only=bool(os.environ.get("UC_HTTPS_ONLY")))
