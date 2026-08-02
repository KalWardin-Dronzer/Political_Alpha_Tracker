import requests
from bs4 import BeautifulSoup
import time

def fetch_screener_shareholding(symbol):
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
    }
    url = f"https://www.screener.in/company/{symbol}/"
    try:
        resp = session.get(url, headers=headers)
        print("GET Status:", resp.status_code)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Look for shareholding tables
            for row in soup.find_all('tr'):
                if row.has_attr('class') and 'sub-holder' in ' '.join(row['class']):
                    print("Subholder:", row.text.strip().replace('\n', ' '))
                elif len(row.find_all('td')) > 1:
                    name = row.find_all('td')[0].text.strip()
                    if len(name) > 5 and 'Public' not in name and 'FIIs' not in name:
                        print("Row:", name)
    except Exception as e:
        print(e)

if __name__ == "__main__":
    fetch_screener_shareholding("RVNL")
