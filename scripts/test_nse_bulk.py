import requests
import time

def fetch_bulk_deals():
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive"
    }
    
    # Get cookies
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
    except Exception as e:
        print(f"Error getting cookies: {e}")
        
    time.sleep(1)
    
    # Try the API
    url = "https://nsearchives.nseindia.com/content/equities/block.csv"
    try:
        resp = session.get(url, headers=headers, timeout=10)
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            print("Successfully fetched CSV")
            print(resp.text[:200])
        else:
            print("Failed to fetch CSV")
    except Exception as e:
        print(f"Error getting bulk deals: {e}")

if __name__ == "__main__":
    fetch_bulk_deals()
