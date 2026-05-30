#!/bin/sh
set -e
alembic upgrade head
python seed.py
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
