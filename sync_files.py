# sync_files.py
import urllib.request
import os
import time

FOLDER = os.path.dirname(os.path.abspath(__file__))

FILES = {
    "index.html": "https://raw.githubusercontent.com/tumsbux/daily-report/main/index.html",
    "sales_dashboard_v8.html": "https://raw.githubusercontent.com/tumsbux/daily-report/main/sales_dashboard_v8.html",
    "fraud_dashboard.html": "https://raw.githubusercontent.com/tumsbux/daily-report/main/fraud_dashboard.html",
    "index_for_lost_product.html": "https://raw.githubusercontent.com/tumsbux/daily-report/main/index_for_lost_product.html",
    "lost_product_data.json": "https://raw.githubusercontent.com/tumsbux/lost-Product/main/lost_product_data.json",
    "analytics.js": "https://raw.githubusercontent.com/tumsbux/daily-report/main/analytics.js",
    "product_dashboard.html": "https://raw.githubusercontent.com/tumsbux/daily-report/main/product_dashboard.html",
    "product_data.json": "https://raw.githubusercontent.com/tumsbux/daily-report/main/product_data.json"
}

def sync():
    print("Starting sync from GitHub raw content...", flush=True)
    ts = int(time.time())
    for name, url in FILES.items():
        dest = os.path.join(FOLDER, name)
        # Append query parameter to bypass CDN cache
        nocache_url = f"{url}?t={ts}"
        print(f"Downloading {nocache_url} -> {dest}...", end=" ", flush=True)
        try:
            req = urllib.request.Request(nocache_url, headers={'User-Agent': 'Mozilla/5.0'})
            # Timeout set to 180 seconds to accommodate large downloads
            with urllib.request.urlopen(req, timeout=180) as response:
                content = response.read()
            with open(dest, "wb") as f:
                f.write(content)
            print("OK", flush=True)
        except Exception as e:
            print(f"FAILED: {e}", flush=True)

if __name__ == "__main__":
    sync()
