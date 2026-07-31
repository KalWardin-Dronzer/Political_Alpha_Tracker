# Alpha Maximization Roadmap

To squeeze every drop of alpha out of the Political Alpha Tracker, we will implement the 5 advanced features sequentially. This will transition the system from a simple binary tracker (win/loss) into a highly sophisticated, multi-factor quantitative engine.

## User Review Required
> [!CAUTION]
> Phase 1 (Materiality) and Phase 2 (Regional Mapping) will require the use of LLMs (like Gemini) to read and parse the unstructured BSE PDF announcements. We will need to set up API keys or use your existing Gemini configuration for this extraction step. 

## The Execution Plan

### Phase 1: The Materiality Threshold (Parsing Contract Size)
**Goal:** Only deploy capital on contracts that mathematically matter to the bottom line (>5% of Market Cap).
- **[MODIFY] `src/bse_monitor.py`**: Intercept the downloaded PDF attachments. Instead of just flagging it as a "Contract", send the PDF text to an LLM to extract the exact monetary value (e.g., "₹ 1,500 Crores").
- **[MODIFY] `src/cache_manager.py`**: Update the `announcements` schema to store `contract_value_cr`.
- **[NEW] `src/alpha_engine.py`**: Create a new module to calculate `Materiality = contract_value_cr / market_cap_cr`. 
- **[MODIFY] `src/notifier.py`**: Only send trade alerts if `Materiality > 5%`. 

### Phase 2: State vs. Central Mapping (Regional Precision)
**Goal:** Ensure the political donation matches the state government issuing the tender.
- **[MODIFY] `src/donor_ingester.py`**: Map the 225 major donors to their associated regional political parties (e.g., BRS in Telangana, DMK in Tamil Nadu) based on Election Commission data.
- **[MODIFY] `src/bse_monitor.py`**: Expand the LLM prompt from Phase 1 to also extract the "Issuing Authority" (e.g., "Government of Maharashtra" or "NHAI Central").
- **[MODIFY] `src/alpha_engine.py`**: Create a matrix cross-referencing the issuing state with the funded political party. If it's a regional contract, enforce a strict regional donor match.

### Phase 3: Smart Money Front-Running (Volume Anomalies)
**Goal:** Front-run insider accumulation before the BSE announcement drops.
- **[MODIFY] `src/financial_screener.py`**: Set up a daily cron job to pull 14-day average delivery volume for all highly connected Watchlist companies.
- **[NEW] `src/volume_tracker.py`**: Calculate z-scores for daily volume. If a connected company hits a volume spike >3 standard deviations with no accompanying news, trigger a "Pre-Announcement Accumulation" alert.

### Phase 4: Pair Trading (Shorting the Unconnected Losers)
**Goal:** Generate market-neutral alpha by shorting the competitors who lost the bid.
- **[NEW] `src/competitor_mapper.py`**: Build a matrix of direct competitors (e.g., L&T vs Afcons, Torrent vs Sun Pharma).
- **[MODIFY] `src/notifier.py`**: When a highly connected company wins a material contract, simultaneously issue a "Short Alert" for their primary unconnected competitors.

### Phase 5: Election Cycle Macro Weighting
**Goal:** Increase position sizing aggressively 12-18 months before general elections.
- **[MODIFY] `src/config.py`**: Hardcode the dates of upcoming major State and General elections.
- **[MODIFY] `src/alpha_engine.py`**: Apply a multiplier (1.5x to 2x) to the `alpha_score` for all infrastructure/defense companies in the 18 months preceding an election to capture the budget-clearing frenzy.

---

## Next Steps
We will begin with **Phase 1: The Materiality Threshold**. 
Please review the roadmap and click **Proceed** when you're ready to start building Phase 1!
