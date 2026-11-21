# NIGHTSHIFT — automation for everything

No-code automation that runs forever on GitHub's servers — and, with the
local agent, on **your PC**: flows, headless-browser jobs, schedules,
notifications, YouTube uploads, email, file organizing.

- **FLOWS** — build automations from blocks (HTTP, email, Telegram, YouTube,
  shell commands…). Outputs chain: `{{step1.url}}` feeds the next step.
- **SCHEDULES** — `pipelines.json`: cron schedules that fire tasks/flows.
- **BROWSER** — headless Chromium snapshots / scrapes / uptime checks.
- **AGENT** — your PC pulls queued local jobs (full-computer access,
  pull-based, nothing listens).
- **PIPELINE** — edit `tasks.json` / `pipelines.json` right in the browser.

Full setup (website-only, ~10 minutes, no terminal):
[docs/AUTOMATION_SETUP.md](docs/AUTOMATION_SETUP.md)
