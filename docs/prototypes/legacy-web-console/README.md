# Legacy Web Console Prototype

This directory keeps the historical single-file Web Console prototype for
reference and regression tests.

The production UI lives in `frontend/` and is built with React + Vite. FastAPI
serves the compiled frontend assets from `src/ragrig/static/dist`.

Only the historical HTML prototype belongs here. `src/ragrig/web_console.py`
remains an active backend workflow facade used by routers, tasks, services, and
tests.

Do not add new product UI here. Update `frontend/` instead.
