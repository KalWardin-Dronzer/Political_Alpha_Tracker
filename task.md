- `[x]` **Phase 1: Materiality Threshold**
  - `[x]` Alter `announcements` database schema to include `contract_value_cr`
  - `[x]` Install `google-generativeai` and `PyPDF2`
  - `[x]` Create `AlphaEngine` for LLM parsing
  - `[x]` Modify `BSEMonitor` to download PDFs and invoke AlphaEngine
  - `[x]` Modify `Notifier` to append Contract Value and % to Telegram messages
  - `[x]` Enforce >5% Materiality Threshold in `main.py`

- `[x]` **Phase 2: State vs Central Mapping**
- `[x]` **Phase 3: Smart Money Front-Running**
- `[x]` **Phase 4: Pair Trading**
- `[x]` **Phase 5: Election Cycle Weighting**

- `[x]` **Phase 6: Virtual Paper Trading Engine**
  - `[x]` Create `virtual_portfolio` and `trade_history` tables in `cache_manager.py`
  - `[x]` Create `src/portfolio_manager.py` (PaperTrader with tax & slippage math)
  - `[x]` Update `main.py` to trigger PaperTrader on high conviction signals
  - `[x]` Verify with `test_paper_trader.py` script

- `[x]` **Phase 7: Cloud Deployment**
  - `[x]` Create `aws_deploy.sh` script
  - `[x]` Create `crontab_setup.txt` for 5:00 PM IST schedule
  - `[x]` Lock down `.gitignore` for `.env` and `data/`
