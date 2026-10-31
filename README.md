# Political Alpha Tracker

A research pipeline that tests whether Indian listed companies connected to political donors, through electoral
bonds and electoral trusts, behave differently around contract announcements and in their share prices. It
ingests public disclosures every weekday, links donors, directors and companies in a graph, and tests the
hypothesis with event studies, cross-sectional backtests that include transaction costs, and multiple-testing
corrections.

The central hypothesis did not survive those tests. The findings below, and the commands that reproduce them,
are the main result.

## What the research found

- **The political lead-lag is refuted.** Kim, Kim, Pantzalis & Park (Financial Analysts Journal, 2018) report
  that returns of politically connected firms lead those of their unconnected peers. Re-tested on 64 connected
  companies, 0 of 4 specifications is significant after Bonferroni correction (monthly lag 2: β 0.08, t 0.87,
  p 0.38). A placebo arm, using unconnected leaders from the same sector matched on traded value, is significant
  (weekly lag 1: β 0.089, t 2.87). The diffusion is real, but it comes from size and liquidity, not political
  connection. Standard errors are clustered by period. `python cli.py research lead-lag`
- **The size lead-lag does not survive costs.** Gross of costs, the weekly rule's Sharpe ratio is 1.345. Its 184
  round trips at 0.422% bring it to 0.732, below buy-and-hold's 1.196. The monthly rule's Sharpe gain over
  buy-and-hold, +0.204, has a 95% paired-bootstrap interval of [-0.390, +0.678]. It comes from time spent in
  cash, not from added return. `python cli.py research leadlag-rule`
- **Cross-sectional factors add nothing here.** Selection by residual momentum, short-term reversal and low
  volatility is indistinguishable from random selection within the same universe. The universe's own premium is
  a post-COVID recovery that decays to a Sharpe ratio near 0.1. `python cli.py research factor`, `controls` and
  `universe`
- **Data quality decided the answer.**
  - Loose donor-name matching paired unrelated companies with similar names and inflated the connected universe
    to 93 companies. With boilerplate-normalised names, an exact first word and a stricter fuzzy scorer, it is
    64 of 1,472.
  - On 20 companies with known CINs, the name-to-CIN resolver found 16, got none wrong and refused 4.
  - Survivorship bias from delisted stocks is worth 0.45% a year.
  - Every connection found runs through a direct donation; none runs through the director-mediated path the
    design was built around.

## How it works

**Data.**
- Every weekday: BSE corporate announcements, NSE bulk and block deals, SEBI insider (SAST and PIT) disclosures,
  and promoter-pledge disclosures.
- Each quarter or year: the watchlist, company directors, and electoral-trust and electoral-bond donor records.
  Donor records come from ECI reports, then MyNeta, then ADR PDFs, in that order of preference.
- On demand: the NSE equity list mapped to BSE scrip codes, and an adjusted daily price panel (1,905 days ×
  1,588 symbols, Parquet).

**Entity resolution and the connection graph.**
- Company names are resolved to CINs through Zaubacorp. Only listed-company CINs (prefix L) are accepted, the
  first word must match exactly, and a weak match is refused rather than guessed.
- Directors and their DINs come from the MCA portal, with Zaubacorp as a fallback. Donor names are matched to
  listed companies.
- A NetworkX graph links listed companies, directors, donor companies, electoral trusts and parties. Each
  connection is scored by director exclusivity, path proximity and donation magnitude.
- A 1.5× boost applies when the receiving party faces an election in a hard-coded calendar. The calendar ends
  with the April 2026 state elections, so the boost needs a calendar update before it applies again.

**Signals.**
- Materiality: Gemini reads contract announcements and extracts the contract value, which is divided by market
  capitalisation.
- Insider buying: only open-market purchases count, by several insiders or one large buyer, net of internal
  transfers.
- Pledges: Gemini only extracts the figures from a filing, and rules decide whether a promoter's pledge was
  really released. The LLM made that decision until it raised a false alert.
- Volume and timing: volume spikes above 3 standard deviations, and technical indicators for entry timing.
- Alerts also list two or three listed competitors in the same niche, named by Gemini, keeping only those with
  no political connection.
- A government-tender monitor exists only as a stub over a simulated feed.

**Research tooling.**
- An event study with three tests: how often random small companies also have political connections (the base
  rate), whether connected contract winners outperform unconnected ones at 30, 60, 90 and 180 days, and the win
  rate. Below a minimum sample it reports INCONCLUSIVE instead of a verdict.
- A factor backtest with per-trade costs, a stationary block bootstrap, a deflated Sharpe ratio, purged and
  embargoed folds, and an append-only log of every trial (`python cli.py trials`).
- A delisting registry for survivorship correction.

**Operations.**
- A Docker container on AWS EC2, run by cron at 17:00 IST every weekday. EC2 is the only host with a
  persistent database.
- GitHub Actions redeploys to EC2 on every push to `main`. The scheduled workflows are disabled because they ran
  on an empty database; see `.github/workflows/README.md`.
- A reference-data health check opens every run.
- A paper portfolio buys on each alert and sells at an ATR stop-loss or after 90 days. Its costs follow a
  discount broker's delivery charges plus 0.1% slippage.
- Telegram alerts and a weekly tearsheet.
- A Streamlit dashboard with a Gemini text-to-SQL assistant. The assistant runs the SQL the model writes
  against the local database without restrictions, so keep it on your own machine.

## Running it

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env
python cli.py --help
```

In `.env`, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, and add `GEMINI_API_KEY` for the LLM steps.

| Command | What it does |
|---|---|
| `python cli.py health` | Reference-data health check |
| `python cli.py refresh --mode quarterly` | Rebuild the watchlist and directors |
| `python cli.py refresh --mode annual` | Reload donor records |
| `python cli.py refresh --mode prune` | Prune the graph |
| `python cli.py daily` | Run the daily pipeline |
| `python cli.py prices` | Build or update the price panel |
| `python cli.py research <study>` | Run a study: `event`, `factor`, `controls`, `universe`, `lead-lag`, `leadlag-rule` |
| `python cli.py trials` | Show the backtest trial log |
| `python cli.py purge-demo` | Find seeded demo rows in the paper portfolio; `--apply` deletes them |
| `python cli.py dashboard` | Print how to launch the Streamlit dashboard |

## Layout

```text
cli.py                       single entry point
main.py, refresh.py          daily pipeline and reference-data refreshes, also run directly by cron
app.py                       Streamlit dashboard
src/data/                    ingestion, entity resolution, watchlist, price panel, delisting registry
src/signals/                 signal monitors, connection graph, factor engine, lead-lag test
src/research/                event study; factor backtest and validation
src/execution/               Telegram notifier, paper portfolio and position sizing, weekly tearsheet
src/pipeline/                daily orchestrator
scripts/research/            the studies behind `python cli.py research`
tests/                       pytest suite
Dockerfile                   container image for EC2
crontab_setup.txt            the EC2 cron schedule
```

## Tests

```bash
pytest -q
```

The suite has 185 tests across 10 modules. They cover BSE announcement classification, entity resolution, the
CIN resolver, the cache, the graph, the factor engine, the lead-lag test, the delisting registry, the pledge
monitor, and an offline end-to-end run of the daily pipeline.

## Disclaimer

For research and education only. The pipeline reads public disclosures and places no real orders; its
portfolio is a paper portfolio. Nothing here is investment advice.
