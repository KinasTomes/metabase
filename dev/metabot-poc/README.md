# MetaBot local POC

This is an isolated, source-built Metabase environment for the MetaBot POC.
It deliberately starts with only two services:

- `metabase`: built from the checked-out source tree as Enterprise Edition.
- `metabot-app-db`: a dedicated PostgreSQL application database for Metabase
  users, settings, collections, and metadata.

It does not mount BI data, seed sample content, configure an LLM provider, or
reuse infrastructure from `D:\Code\bi-agent`.

## First run

From the repository root, create a local environment file and choose a unique
local database password:

```powershell
Copy-Item dev\metabot-poc\.env.example dev\metabot-poc\.env
```

Validate the resolved Compose configuration before creating containers:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml config
```

Build the current branch and start the isolated stack:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml up --build
```

The first source build downloads the Java, Clojure, Node, and frontend
dependencies, so it can take several minutes. When the application is ready,
open `http://localhost:3000` and complete the Metabase admin-user setup.

To run it later without rebuilding:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml up
```

## Smoke check

After the initial setup, verify the application before adding data or a model
provider:

```powershell
Invoke-WebRequest http://localhost:3000/api/health | Select-Object -ExpandProperty Content
```

Expected result: a successful health response. In the UI, confirm that the
admin account can open **Admin > AI**. A valid entitlement is still required
for any Enterprise-gated MetaBot capability; this POC does not bypass licensing.

## Scope of this foundation

The next step is to add a separate PostgreSQL warehouse containing only curated
Gold/serving data, then provision the corresponding Metabase connection,
models, metrics, collection, and read-only permissions. Configure the LLM only
after that semantic layer exists, using the Admin UI or server-side secrets.

## Stop and reset

Stop the services while retaining the isolated metadata database:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml down
```

Use the following only when you intentionally want to delete this POC's
Metabase metadata, users, settings, and collections:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml down -v
```
