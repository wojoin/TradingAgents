"""The FastAPI server behind the web front end: start analyses, follow them live, read and download reports."""
from web.server import v8guard

# Before anything calls AKShare: V8 must never be entered from two threads at once.
v8guard.install()
