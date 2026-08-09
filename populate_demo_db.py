import json
import logging
from datetime import datetime
from src.cache_manager import CacheManager
from src.graph_manager import GraphManager

logging.basicConfig(level=logging.INFO)

cache = CacheManager()
graph = GraphManager(cache)

print("Populating alpha_graph table for dashboard...")

with cache._connect() as conn:
    conn.execute("DELETE FROM alpha_graph")
    
    companies = conn.execute("SELECT cin, scrip_code, name FROM companies").fetchall()
    
    count = 0
    for row in companies:
        cin, scrip_code, name = row
        connections = graph.alpha_query(cin)
        if connections:
            top = connections[0]
            score = top["alpha_score"]
            din = top["director_din"]
            
            # Since primary key is (din, cin), we can just insert or replace
            conn.execute("INSERT OR REPLACE INTO alpha_graph (din, cin, score) VALUES (?, ?, ?)", 
                         (din, cin, score))
            count += 1
            
print(f"Populated {count} entries in alpha_graph.")

print("Populating virtual_portfolio for dashboard...")
with cache._connect() as conn:
    existing = conn.execute("SELECT count(*) FROM virtual_portfolio").fetchone()[0]
    if existing == 0:
        top_companies = conn.execute("SELECT c.scrip_code, c.name, a.score FROM alpha_graph a JOIN companies c ON a.cin = c.cin ORDER BY a.score DESC LIMIT 5").fetchall()
        for i, (scrip, name, score) in enumerate(top_companies):
            buy_price = 100.0 + (i*15)
            qty = 100
            invested = buy_price * qty
            conn.execute("INSERT INTO virtual_portfolio (scrip_code, buy_date, buy_price, quantity, invested_amount, conviction_score) VALUES (?, ?, ?, ?, ?, ?)",
                         (scrip, "2026-07-03", buy_price, qty, invested, score + 4.0))
        print("Inserted 5 mock portfolio positions.")
    else:
        print("Portfolio already has data.")
        
print("Done.")
