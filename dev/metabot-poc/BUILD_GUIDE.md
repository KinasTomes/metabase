# MetaBot POC build guide

Use this guide to build and run the local MetaBot POC without repeating the
initial source-build investigation.

## One-time setup

From the repository root, create the ignored local config:

```powershell
Copy-Item dev\metabot-poc\.env.example dev\metabot-poc\.env
```

Set a long local password for `METABOT_APP_DB_PASSWORD` in `.env`. If port
`3000` is already in use, for example by `D:\Code\bi-agent`, set:

```text
METABOT_HOST_PORT=3002
METABOT_SITE_URL=http://localhost:3002
```

## First source build

The first build compiles the Metabase frontend and uberjar. It can take about
20–30 minutes depending on Docker cache and network speed. Use quiet output so
Docker Desktop does not need to stream a huge progress log:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml build --quiet metabase
```

Confirm the image exists:

```powershell
docker image inspect metabase-metabot-poc:local --format 'ID={{.Id}} Created={{.Created}} Size={{.Size}}'
```

Then start the POC without rebuilding:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml up
```

Open the URL configured by `METABOT_SITE_URL` and complete initial Metabase
admin setup.

## Normal daily use

If neither Dockerfile nor Metabase source changed, do not pass `--build`:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml up
```

Stop it while retaining the POC metadata database:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml down
```

## When to rebuild

Rebuild only after changing Metabase source, `Dockerfile`, or build-relevant
configuration:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml build --quiet metabase
```

Docker reuses completed layers, so later builds should be materially faster.
Avoid `--no-cache` unless diagnosing a cache-specific issue; it forces the
slowest path again.

## Troubleshooting

- **Port is already allocated:** change `METABOT_HOST_PORT` and
  `METABOT_SITE_URL` together in `.env`.
- **Docker network download fails:** re-run the same quiet build. Docker retains
  completed layers, so it resumes from cache where possible.
- **Docker Desktop loses the BuildKit status stream:** use the quiet build
  command above; it avoids sending extensive build output through the CLI.
- **Need a clean POC only:** `down -v` deletes the dedicated MetaBot metadata
  database, users, settings, and collections. Do not use it unless that reset
  is intentional.

The Dockerfile already normalizes Windows shell-script line endings inside the
Linux builder and supplies local Git metadata required by the frontend build.
Do not manually convert the working tree or add `.git` back into the Docker
context.
