# Barzo Analytics — always-current shared dashboard

A dark, Barzo-branded analytics page that a **GitHub Action rebuilds every hour** from
your PostHog data and publishes to **GitHub Pages**. Once set up, it runs entirely in
GitHub's cloud — nothing on your computer needs to be open, and the team link is always
current.

**Final link will be:** `https://<your-github-username>.github.io/<repo-name>/`

---

## One-time setup (~10 minutes)

You do these steps because they involve creating an account, a repo, an API key, and a
secret — things that must be yours. After this, it's fully automatic.

### 1. Create the repository
- Go to https://github.com/new
- Name it e.g. `barzo-analytics`
- **Public** is simplest (GitHub Pages is free for public repos). Private repos need a
  paid GitHub plan for Pages. The page will be public either way — that's the point.
- Create the repo.

### 2. Add these two files to the repo
Upload (drag-and-drop via the repo's "Add file → Upload files", or `git push`):
- `generate.py`
- `.github/workflows/deploy.yml`  ← keep this exact folder path

### 3. Create a PostHog API key and add it as a secret
- In PostHog: **Settings → Personal API keys → Create personal API key**
  - Scopes needed: **Insight: Read** AND **Query: Read** (both required — the dashboard
    now pulls each date range through the query API).
- Copy the key (starts with `phx_`).
- In GitHub: repo **Settings → Secrets and variables → Actions → New repository secret**
  - Name: `POSTHOG_API_KEY`
  - Value: paste the key → Save.

> Your key lives only in GitHub's encrypted secrets. It is never in the page, the repo
> files, or shared with anyone.

### 4. Turn on Pages
- Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.

### 5. Run it once
- Go to the **Actions** tab → "Build & deploy Barzo Analytics" → **Run workflow**.
- When it finishes (green check), your link is live at
  `https://<your-username>.github.io/<repo-name>/`.
- After that it re-runs **every hour** on its own. Share the link with your team.

---

## Adjusting things
- **Refresh cadence:** edit the `cron:` line in `.github/workflows/deploy.yml`
  (`0 * * * *` = hourly; `0 */6 * * *` = every 6 hours; `0 13 * * *` = daily 1pm UTC).
- **Different project/region:** edit `POSTHOG_HOST` / `POSTHOG_PROJECT` in the workflow.
- **Which insights / layout:** edit `INSIGHTS` and the template in `generate.py`.
- **Date-range options / default:** the page has a picker (Last 24 hours / 7 / 30 / 90 days,
  defaulting to 24h). Edit the `RANGES` list and `DEFAULT_RANGE` in `generate.py` to change
  the presets or default. (All presets are pre-built into the page; a fully custom calendar
  picker would require live querying and is not part of the static build.)

## Troubleshooting
- Action fails on "Generate dashboard": check the `POSTHOG_API_KEY` secret exists and has
  Insight:Read scope. The run log lists any insight it couldn't fetch.
- Page 404s right after setup: Pages can take a minute on first publish; confirm
  Settings → Pages source is "GitHub Actions".
