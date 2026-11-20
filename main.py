"""University Club - FastAPI entry point.

Run locally:      fastapi dev        (or)   uvicorn main:app --reload
Deploy to cloud:  fastapi deploy
"""
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from web import routes, session_options

app = FastAPI(title="University Club", docs_url=None, redoc_url=None, openapi_url=None)
app.router.routes.extend(routes)
app.add_middleware(SessionMiddleware, **session_options)
