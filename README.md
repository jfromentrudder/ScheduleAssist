# ScheduleAssist

**A smart scheduler for bad schedulers.**

ScheduleAssist is a web-based scheduling application designed to make task
management easier for people who struggle with time management. It connects to
your existing calendars (Google Calendar, Outlook Calendar) and automatically
builds a high-school/college-style schedule around your events — allocating
dedicated work **"periods"** during your chosen workdays (Mon–Fri by default)
based on upcoming deadlines and events, so the work of planning out the day is
already done for you.

*CS 406 project with Bill Pfeil — Summer 2026 — Jay Froment-Rudder*

## How it works

1. Create an account and sign in with Google or Microsoft to connect your
   calendar.
2. Existing events are imported automatically; you can also add events manually.
3. Enrich events with details: expected prep time, deadline vs. one-time event,
   and a description.
4. Set your workdays and preferences, and ScheduleAssist generates a schedule
   that allocates periods around your commitments.
5. Work through your periods — the schedule auto-updates as things change.

While aimed primarily at working professionals with unstructured days, it works
just as well for students who want extra structure.

## Project links

- [Project board](https://github.com/users/jfromentrudder/projects/5/views/1)

## Tech stack

- **Frontend** — React built with Vite
- **Backend** — Python FastAPI
- **Database** — PostgreSQL
- **Project management** — GitHub Projects

## Project layout

```
frontend/   React + TypeScript + Vite
backend/    FastAPI + SQLAlchemy
  app/
    main.py       app entrypoint, routes
    config.py     settings (env vars / .env)
    database.py   engine, session, Base
    models.py     ORM models
docker-compose.yml   PostgreSQL 16
```

## Prerequisites

- Node.js 20+
- Python 3.10+
- Docker

## Getting started

### 1. Database

```sh
docker compose up -d
```

Postgres runs on `localhost:5432` (user/password/db: `scheduleassist`).

### 2. Backend

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head   # apply database migrations
uvicorn app.main:app --reload
```

API at http://localhost:8000 — interactive docs at http://localhost:8000/docs.

### 3. Frontend

```sh
cd frontend
npm install
npm run dev
```

App at http://localhost:5173. Requests to `/api/*` are proxied to the backend
(see `frontend/vite.config.ts`).

## Configuration

Backend settings come from environment variables or `backend/.env`
(see `backend/.env.example`). Defaults match the docker-compose database.

## Database migrations

The schema is managed with [Alembic](https://alembic.sqlalchemy.org/)
(`backend/alembic/`). Common commands (from `backend/`, venv active):

```sh
alembic upgrade head                          # apply pending migrations
alembic revision --autogenerate -m "message"  # generate a migration after model changes
alembic downgrade -1                          # roll back one migration
```

After changing `app/models.py`, generate a migration, review the generated
file in `alembic/versions/`, then apply it.
