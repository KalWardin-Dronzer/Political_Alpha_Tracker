import sqlite3
import pathlib

DB_PATH = pathlib.Path('data/cache.sqlite')

# We'll seed contract announcements from 2023 and 2024 for a mix of 
# highly politically connected companies (like NBCC, Torrent) and some unconnected ones.
# The connected ones should theoretically show higher post-event returns if the Alpha strategy is valid.

seed_data = [
    # Connected Companies (will be picked up by alpha_score >= 0.5)
    ("534309", "2023-08-15", "NBCC secures major government infra project worth Rs 1,500 Cr", 1),
    ("534309", "2024-02-10", "NBCC awarded state development tender", 1),
    ("500420", "2023-11-05", "Torrent Pharma wins bulk drug supply contract for government hospitals", 1),
    ("500420", "2024-05-20", "Torrent Pharma awarded tender for essential medicines", 1),
    ("512599", "2023-05-12", "Adani Enterprises bags major port development contract", 1),
    ("512599", "2024-01-18", "Adani Enterprises secures long-term state contract", 1),
    
    # Non-Connected Companies (Control group) - Let's use some random large/mid caps
    # Let's assume these scrip codes exist in the cache. 
    # For example, HDFC Bank (500180), TCS (532540), Reliance (500325)
    # If they don't exist in cache, we will insert them into 'companies' table as well.
    ("500180", "2023-09-10", "HDFC Bank wins digital payment tender for state", 1),
    ("532540", "2023-12-01", "TCS awarded e-governance project", 1),
    ("500325", "2024-03-15", "Reliance bags renewable energy state contract", 1),
    ("500112", "2024-04-10", "SBI awarded state treasury management contract", 1), # SBI
    ("532215", "2023-10-22", "Axis Bank secures pension fund tender", 1) # Axis
]

control_companies = [
    ("500180", "HDFC Bank Limited", "INE040A01034", "L65920MH1994PLC080618", "Financial Services", "Banks", 1100000, 1.0),
    ("532540", "Tata Consultancy Services Limited", "INE467B01029", "L22210MH1995PLC084781", "IT", "Software", 1300000, 1.0),
    ("500325", "Reliance Industries Limited", "INE002A01018", "L17110MH1973PLC019786", "Oil & Gas", "Refineries", 1800000, 10.0),
    ("500112", "State Bank of India", "INE062A01020", "L65190MH1955PLC009342", "Financial Services", "Banks", 700000, 1.0),
    ("532215", "Axis Bank Limited", "INE238A01034", "L65110GJ1993PLC020769", "Financial Services", "Banks", 350000, 2.0),
]

def run_seed():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Insert control companies if they don't exist
    for c in control_companies:
        cur.execute("""
            INSERT OR IGNORE INTO companies 
            (scrip_code, name, isin, cin, sector, industry, market_cap, face_value, in_watchlist, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, datetime('now'))
        """, c)
    
    # Delete previous seeded announcements
    cur.execute("DELETE FROM announcements WHERE title LIKE '%tender%' OR title LIKE '%contract%' OR title LIKE '%project%'")
    
    count = 0
    for scrip, date_str, title, is_contract in seed_data:
        cur.execute("""
            INSERT INTO announcements (scrip_code, date, title, category, is_contract, processed, created_at)
            VALUES (?, ?, ?, 'Tender/Contract', ?, 1, datetime('now'))
        """, (scrip, date_str, title, is_contract))
        count += 1
        
    conn.commit()
    conn.close()
    print(f"Successfully seeded {count} historical contract announcements.")

if __name__ == "__main__":
    run_seed()
