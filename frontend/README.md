# Multi Agent Starter Frontend

Beginner-friendly Next.js chat UI for the multi-agent backend.

## Features

- Register and login with email/password
- Stores JWT token in browser local storage
- Sends protected chat requests to the backend
- Shows assistant answers
- Shows route selected by supervisor
- Shows which agents were used
- Shows raw agent outputs for learning
- Can trigger sample Elasticsearch ingest from the UI

## Connected backend endpoints

### Public backend endpoints

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`

### Protected backend endpoints

These are called with `Authorization: Bearer <token>`:

- `POST /api/v1/chat`
- `POST /api/v1/ingest/sample-data`

## Tech stack

- Next.js
- React
- TypeScript

## Setup

```bash
cp .env.example .env.local
npm install
npm run dev
```

Open:

- `http://localhost:3000`

## Environment

```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

## Typical usage flow

1. Start the backend.
2. Open the frontend.
3. Register a new user.
4. Log in.
5. Optionally click `Ingest sample data`.
6. Send chat prompts.

## Example prompts

- `Summarize how LangGraph works`
- `Search for Redis caching`
- `Search and summarize observability with Langfuse`

## Why this UI is useful for learning

This UI is intentionally more informative than a normal chat box.

It helps you see:

- auth flow
- backend route decisions
- which agents ran
- final answer
- raw agent outputs

That makes it easier to understand how the backend orchestration works.