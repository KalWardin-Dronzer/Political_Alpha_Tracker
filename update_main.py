import re

file_path = r"c:\Users\legen\OneDrive\Documents\QEDS\Insider trading\main.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

macro_event_code = """
    # ── Step 5.5b: Global Macro-Event Monitoring ──
    logger.info("Step 5.5b: Scanning for Global Macro-Events...")
    try:
        from src.macro_event_monitor import MacroEventMonitor
        macro_monitor = MacroEventMonitor(cache, alpha_engine)
        global_events = macro_monitor.fetch_global_events()
        
        if global_events:
            for event in global_events:
                event_type = event.get('event_type')
                logger.info(f"  🌍 Found Global Macro Event: {event_type} - {event.get('catalyst')}")
                
                # We need the watchlist full data to iterate
                watchlist = cache.get_watchlist()
                for company in watchlist:
                    cin = company.get("cin")
                    scrip_code = company.get("scrip_code")
                    niche = (company.get("micro_niche") or "unknown").lower()
                    
                    if not cin or niche == "unknown":
                        continue
                        
                    # Use LLM to check if company benefits
                    benefits = alpha_engine.check_company_macro_benefit(
                        company_name=company.get('name'), 
                        company_niche=niche, 
                        event_summary=event.get('summary')
                    )
                    
                    if benefits:
                        # Check political connection
                        connections = graph.alpha_query(cin)
                        if connections:
                            top_conn = connections[0]
                            if top_conn["alpha_score"] >= ALPHA_SCORE_THRESHOLD:
                                logger.info(f"  🚨 GLOBAL MACRO EVENT ALPHA DETECTED for {scrip_code} ({company['name']})")
                                if not dry_run:
                                    notifier.send_macro_event_alert(
                                        company=company,
                                        connection=top_conn,
                                        event=event
                                    )
                                    alerts_fired += 1
                                else:
                                    logger.info("  [DRY RUN] Would have sent macro event alert")
    except Exception as e:
        logger.error(f"  ❌ Error in Macro Event Scans: {e}")
"""

# Insert right before Step 5.6
if "# ── Step 5.5b: Global Macro-Event Monitoring ──" not in content:
    content = content.replace("    # ── Step 5.6: Advanced Alpha Scans", macro_event_code + "\n    # ── Step 5.6: Advanced Alpha Scans")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated main.py successfully.")
else:
    print("main.py already updated.")
