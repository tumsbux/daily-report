# start_services.py
import sys
import time
import datetime
import subprocess
import threading
import os
import json
import urllib.request
import urllib.error

FOLDER = os.path.dirname(os.path.abspath(__file__))
os.chdir(FOLDER)

def run_http_server():
    print("[SERVER] Starting Python HTTP server on port 8080...", flush=True)
    cmd = [sys.executable, "-m", "http.server", "8080", "--bind", "0.0.0.0"]
    subprocess.run(cmd)

def get_db_config():
    try:
        with open(os.path.join(FOLDER, "db_config.json")) as f:
            return json.load(f)
    except Exception:
        return {}

def get_latest_commit_sha(repo, token):
    url = f"https://api.github.com/repos/{repo}/commits/main"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Mozilla/5.0"
        }
    )
    try:
        # Timeout set to 15 seconds
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            return data.get("sha")
    except Exception as e:
        print(f"[SCHEDULER] Error fetching commit for {repo}: {e}", flush=True)
        return None

def run_scheduler():
    print("[SCHEDULER] Starting SHA-based sync scheduler loop...", flush=True)
    
    sha_file = os.path.join(FOLDER, "synced_shas.json")
    
    # Load previously synced SHAs
    synced_shas = {}
    if os.path.exists(sha_file):
        try:
            with open(sha_file) as f:
                synced_shas = json.load(f)
        except Exception:
            pass
            
    print(f"[SCHEDULER] Loaded cached SHAs: {synced_shas}", flush=True)
    
    while True:
        try:
            cfg = get_db_config()
            token = cfg.get("github_token")
            
            if not token:
                print("[SCHEDULER] Warning: github_token not found in db_config.json, sleeping for 1 minute...", flush=True)
                time.sleep(60)
                continue
                
            repos = {
                "daily-report": "tumsbux/daily-report",
                "lost-Product": "tumsbux/lost-Product"
            }
            
            needs_sync = False
            current_shas = {}
            
            for key, repo_path in repos.items():
                sha = get_latest_commit_sha(repo_path, token)
                if sha:
                    current_shas[key] = sha
                    if synced_shas.get(key) != sha:
                        print(f"[SCHEDULER] Detect new commit in {repo_path}: {synced_shas.get(key)} -> {sha}", flush=True)
                        needs_sync = True
                else:
                    # Carry forward old SHA if fetch failed to prevent infinite reload on glitch
                    current_shas[key] = synced_shas.get(key)
            
            if needs_sync:
                print(f"[SCHEDULER] Time is {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. Executing sync_files.py...", flush=True)
                res = subprocess.run([sys.executable, "sync_files.py"], capture_output=True, text=True)
                
                print("--- SCHEDULER STDOUT ---", flush=True)
                print(res.stdout, flush=True)
                print("--- SCHEDULER STDERR ---", flush=True)
                print(res.stderr, flush=True)
                
                if res.returncode == 0:
                    print("[SCHEDULER] Sync completed successfully. Saving new SHAs.", flush=True)
                    synced_shas = current_shas
                    with open(sha_file, "w") as f:
                        json.dump(synced_shas, f)
                else:
                    print(f"[SCHEDULER] ERROR: Sync script returned code {res.returncode}. Retrying in 2 minutes...", flush=True)
                    time.sleep(120)
                    continue
            
            # Check every 10 minutes (600 seconds)
            time.sleep(600)
        except Exception as e:
            print(f"[SCHEDULER] Exception in scheduler loop: {e}", flush=True)
            time.sleep(60)

if __name__ == "__main__":
    # Start HTTP server in a separate thread
    server_thread = threading.Thread(target=run_http_server, daemon=True)
    server_thread.start()
    
    # Run scheduler in the main thread (blocking)
    run_scheduler()
