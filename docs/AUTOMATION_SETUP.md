# NIGHTSHIFT — Setup (website only, no terminal)

An automation app that runs forever on GitHub's servers — flows, browser
jobs, schedules — plus an optional local agent that gives your flows **full
access to your own PC** (YouTube uploads, file organizing, shell commands).

> **It's your app, your repo, your token.** No third party sees anything.
> Local access is pull-based: your PC polls your repo; nothing listens.

---

## 1 · Create the repo (2 min)

1. Go to **github.com/new**
2. Repository name: `nightshift` (or anything)
3. Visibility: **Public** ← important (free Actions minutes + free Pages; a
   fine-grained token below keeps control private to you)
4. **Create repository**

## 2 · Upload the files (3 min)

1. Run this once on your PC: `python scripts/make_github_bundle.py`
   (it builds a clean **`github-upload/`** folder — secrets and caches excluded)
2. On the new repo's page, click **"uploading an existing file"** link
3. Open the `github-upload` folder, **select everything, drag it into the
   browser**, wait for the upload
4. **Commit changes**

## 3 · Add your secrets (optional, 2 min)

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value | Required? |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | from @BotFather | optional (phone alerts) |
| `TELEGRAM_CHAT_ID` | your chat id | optional |
| `EMAIL_HOST` / `EMAIL_PORT` | e.g. smtp.gmail.com / 587 | optional (email blocks) |
| `EMAIL_USER` / `EMAIL_PASS` | Gmail: use an **App Password** | optional |

Nothing is required to start — flows with browser/HTTP blocks work with zero
secrets. YouTube credentials go in the **local agent's** `.env` (§ YouTube below).

## 4 · Turn everything on (2 min)

1. Repo → **Actions** tab → if prompted, *“I understand my workflows, go ahead”*
2. Repo → **Settings → Pages** → Source: **GitHub Actions**
3. Repo → **Settings → Actions → General → Workflow permissions** →
   *Read and write* (lets the scheduler save its heartbeat)

The app is now live at **`https://YOUR-NAME.github.io/nightshift/`**
(give the first deploy ~1 min).

## 5 · Link the console to you (2 min)

1. Open the console URL → **settings** (top right)
2. `owner/repo` — auto-filled if you came from the Pages URL; fix if needed
3. Paste a **fine-grained token**: create it at
   **github.com/settings/personal-access-tokens/new**
   - Repository access: *only select* this repo
   - Permissions: **Actions → Read and write**, **Contents → Read and write**
4. **save & link** — buttons light up, done.

The token lives only in your browser's localStorage and is sent only to
api.github.com. Revoke it any time on GitHub.

---

## What happens now (forever)

| Schedule | What |
|---|---|
| every 5 min | **scheduler** checks `pipelines.json` and runs whatever pipelines are due |
| on demand | **tasks** workflow: whatever you launch from the console — flows, browser jobs, scripts |
| Mondays 03:17 UTC | **keepalive**: re-enables schedules (GitHub disables cron workflows after 60 days of inactivity) + pings a marker |
| console change | **dashboard** workflow: redeploys the site |

Cron runs can lag a few minutes under GitHub's load — that's normal; design
schedules coarser than 5 minutes.

## Customizing the automation pipeline (from the console)

The whole point: **you never touch YAML or a terminal.**

- **FLOWS panel** — the no-code builder (Zapier-style): pick blocks from the
  action library, fill the fields, **commit flow**. Run with *run now*, or
  schedule it from `pipelines.json` (task `flow`, args `{"flow": "name"}`).
  Outputs chain — put `{{step1.url}}` in a later field to use step 1's output.
- **Action library** (`actions/library.py`): `http_request`, `download_file`,
  `email_send`, `telegram_notify`, `youtube_upload` *(your PC)*,
  `organize_folder` *(your PC)*, `run_command` *(your PC)*, `open_url`
  *(your PC)*. Add your own block = one Python function with a params schema.
- **SCHEDULES panel** shows `pipelines.json` — what runs automatically:
  `name` + `cron` (UTC) + `task` + `args`. Pause with `"enabled": false`.
- **PIPELINE panel** edits `tasks.json` (the runnable registry) and
  `pipelines.json` straight from the browser. Task `run` entries are fixed
  argv (no shell), so the dispatch API stays safe to expose.
- **Browser jobs**: URL + preset (snapshot / read text / uptime), or a full
  multi-step spec — step reference in `scripts/browser_job.py`.

## The local agent — full-computer access (your PC)

Local blocks (YouTube upload, folder organizing, shell commands, opening
apps) run on **your Windows PC** via a tiny pull-based agent:

1. Create `agent/.env`:
   ```
   AGENT_REPO=your-name/nightshift
   AGENT_TOKEN=<fine-grained PAT: this repo only, Contents: read+write>
   ```
2. Double-click `agent/install_startup.bat` once — auto-starts with Windows.
3. Test from the console: run the **sort-downloads** flow (dry-run sorts your
   Downloads folder).

Security: pull-based only — your PC polls your repo every 15s, nothing
listens, no ports opened. Only someone with **write** access to your repo can
queue jobs (that's you). Results land in `state/agent_results/`.

### YouTube uploads (one-time, ~10 min)

1. [console.cloud.google.com](https://console.cloud.google.com) → new project →
   enable **YouTube Data API v3** → OAuth consent (test mode, add yourself) →
   create **OAuth client ID** (Desktop app) → download JSON → copy the
   *client_id* + *client_secret*.
2. Get a refresh token (one-time grant): in the agent folder run
   `python -c` snippet from `actions/library.py` docs, or any OAuth playground
   with scope `https://www.googleapis.com/auth/youtube.upload`.
3. Put `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` in `agent/.env`.
4. Flow: step 1 `youtube_upload` (file path + title), step 2
   `telegram_notify` with `{{step1.url}}`.

Uploads default to **private** — flip to public when you trust the flow.

### Email sending

`EMAIL_HOST` (default smtp.gmail.com), `EMAIL_PORT` (587), `EMAIL_USER`,
`EMAIL_PASS` — for Gmail use an **App Password** (Google Account → Security →
2-Step Verification → App passwords). Works both in the cloud and on your PC.

## Costs

Public repo: Actions runners are **free** (unlimited standard minutes), Pages
is free. The bot ticks cost nothing.

## Troubleshooting

| Symptom | Fix |
|---|---|
| console shows "not linked" | settings → set `owner/repo` + token |
| runs panel empty | run **bot** once from the Actions tab |
| dispatch buttons do nothing | token missing or lacks *Actions: write* |
| "runs unavailable 404" | private repo — add the token, or make repo public |
| bot run fails fast | check the Actions log — usually a missing secret or a bad task arg |
| schedule stopped after 2 months | keepalive handles it; check Actions tab isn't disabled repo-wide |
