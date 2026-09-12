# Workflows

**Every scheduled workflow here was disabled on 2026-09-12. Read this before re-enabling one.**

## Why they were disabled

A GitHub Actions runner starts from a fresh checkout, and `data/cache.sqlite`
and `data/graph.json` are gitignored. So every scheduled run operated on an
**empty, throwaway database**.

Each workflow tried to persist its work with a step like:

```yaml
git add data/ || true
git diff --staged --quiet || git commit -m "chore: ..."
git push || true
```

`git add` on a gitignored path stages nothing. Nothing was committed, nothing
was pushed, and `|| true` swallowed any complaint. **These jobs never had any
effect on real data** — while `refresh.py` and the daily pipeline both send
Telegram summaries, so they looked like they did.

The evidence that made this obvious, from 2026-09-11:

| Run | Companies | Graph | Verdict |
|---|---|---|---|
| EC2 cron, 17:42 IST | 1678 | 221 nodes, 249 edges | real |
| GitHub Actions, 22:16 IST | 184 | 0 nodes, 0 edges | meaningless |

Two "✅ Pipeline completed successfully" messages the same day, identical in
shape, one of them noise. That is the same class of failure as the original bug
this project spent weeks on: a green signal that means nothing.

## Where the real jobs run

EC2 is the only host with a persistent database (`/home/ubuntu/Insider-trading/data`).

The daily pipeline runs from the EC2 crontab at 11:30 UTC / 17:00 IST — see
`crontab_setup.txt`.

Reference-data refreshes must be run there too:

```bash
docker run --rm \
  --env-file /home/ubuntu/Insider-trading/.env \
  -v /home/ubuntu/Insider-trading/data:/app/data \
  alpha-tracker python refresh.py --mode annual      # donors
  #                                       quarterly  # watchlist + directors
  #                                       prune      # graph
```

## What is still active

| Workflow | Trigger | Purpose |
|---|---|---|
| `deploy.yml` | push to `main` | rebuilds the Docker image on EC2 — the only workflow that ever did real work |
| everything else | `workflow_dispatch` only | manual debugging |

## If you want the automation back

Don't re-enable the crons as they stand. Two options that actually work:

1. **SSH into EC2 from the workflow**, the way `deploy.yml` already does — the
   `EC2_HOST`, `EC2_USERNAME` and `EC2_SSH_KEY` secrets exist. The job then runs
   where the data lives. This preserves the original intent.
2. **Persist state deliberately**, via `actions/cache` or a committed artifact.
   Note the database is no longer small, so committing a binary SQLite file on
   every run will bloat the repository.

Option 1 is the better fit. Option 2 is what the original workflows were
reaching for and failing to achieve.
