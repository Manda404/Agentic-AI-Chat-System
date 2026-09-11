# Cloud deployment using free-tier services

This guide describes the repository's deployment layout, separating the application from managed storage services. Provider plan limits and available deployment settings should be checked in the respective dashboards.

## Deployment layout

```text
Next.js frontend       -> Vercel Hobby
FastAPI Docker backend -> Render Free
MongoDB Atlas          -> existing managed cluster
Redis                  -> existing Redis Cloud instance
LLM                    -> Hugging Face Router
Optional web search    -> Tavily
```

## 1. Backend on Render

`render.yaml` declares a Docker web service using `backend/Dockerfile`.

1. Connect the GitHub repository in Render.
2. Select **New → Blueprint** and the repository.
3. Let Render detect `render.yaml`.
4. Supply the variables marked `sync: false`.

Required environment values:

```dotenv
BACKEND_CORS_ORIGINS=https://your-frontend.vercel.app
HUGGINGFACE_API_KEY=...
MONGODB_URI=...
REDIS_URL=...
AUTH_SECRET_KEY=...
```

Set `TAVILY_API_KEY` to enable web search. Local `.env` values are not automatically copied to Render. Generate an authentication secret with:

```sh
openssl rand -hex 32
```

After deployment, check `https://your-backend.onrender.com/health`.

Account for free-service cold starts and ephemeral storage. A sleeping service may take time to start; files uploaded under `backend/data` are not a durable object store. Confirm current plan behavior in Render before relying on it.

## 2. Frontend on Vercel

1. Import the GitHub repository.
2. Set **Root Directory** to `frontend`.
3. Use the Next.js defaults: build with `npm run build`, install with `npm install`, output detection automatic.
4. Set the backend URL and redeploy:

```dotenv
NEXT_PUBLIC_BACKEND_URL=https://your-backend.onrender.com
```

## 3. MongoDB Atlas

Keep Atlas as an external service. Ensure that `documents_search` and `documents_vector` exist in the configured collection. Vector dimensions must match `MODEL_EMBEDDING`; the example `BAAI/bge-small-en-v1.5` configuration uses 384. Owner-scoped vector queries also require owner/visibility filter fields in the index. See [RAG_SYSTEM.md](RAG_SYSTEM.md).

## 4. Redis

Set the managed Redis URL on Render:

```dotenv
REDIS_URL=redis://default:password@host.redis.io:port
```

Use `rediss://` when the provider enables TLS/SSL. Local-memory fallback is not durable cloud storage: accounts can disappear after restart, conversations are not shared across instances and temporary values are lost.

## 5. Deployment order

1. Push the working branch to GitHub.
2. Check MongoDB Atlas and Redis.
3. Deploy the Render backend and check `/health`.
4. Deploy the Vercel frontend with `NEXT_PUBLIC_BACKEND_URL`.
5. Add the frontend URL to Render's `BACKEND_CORS_ORIGINS`.
6. Test registration, login, ingestion, upload and chat.

## 6. CI/CD

`.github/workflows/ci.yml` runs backend tests and a Next.js build for configured push/pull-request events targeting `main`.

Use a working branch, open a pull request, wait for successful checks and merge when reviewed. Git-connected Vercel/Render deployments should use the intended production branch. When available, Render's **After CI Checks Pass** auto-deploy setting waits for checks; **On Commit** deploys without that wait. Vercel can create pull-request previews and production deployments from the configured branch.

## Follow-up improvements

- Move uploads to durable object storage such as R2, S3 or Supabase Storage.
- Add a protected administrator view for index diagnostics.
- Choose generation models that fit the account's available quota; model availability and plan limits require provider verification.
