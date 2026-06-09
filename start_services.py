# start_services.py
import sys
import time
import datetime
import subprocess
import threading
import os

FOLDER = os.path.dirname(os.path.abspath(__file__))
os.chdir(FOLDER)

def run_http_server():
    print("[SERVER] Starting Python HTTP server on port 8080...", flush=True)
    cmd = [sys.executable, "-m", "http.server", "8080", "--bind", "0.0.0.0"]
    subprocess.run(cmd)

def run_scheduler():
    print("[SCHEDULER] Starting daily sync scheduler loop...", flush=True)
    last_run_date = None
    while True:
        try:
            now = datetime.datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            
            # Target time: 09:00 AM (Bangkok time)
            if now.hour == 9 and now.minute == 0 and last_run_date != today_str:
                print(f"[SCHEDULER] Time is 09:00. Starting daily sync for {today_str}...", flush=True)
                
                # Execute sync_files.py
                print("[SCHEDULER] Executing sync_files.py...", flush=True)
                res = subprocess.run([sys.executable, "sync_files.py"], capture_output=True, text=True)
                
                print("--- SCHEDULER STDOUT ---", flush=True)
                print(res.stdout, flush=True)
                print("--- SCHEDULER STDERR ---", flush=True)
                print(res.stderr, flush=True)
                
                if res.returncode == 0:
                    print(f"[SCHEDULER] Daily sync for {today_str} completed successfully.", flush=True)
                    last_run_date = today_str
                else:
                    print(f"[SCHEDULER] ERROR: Sync script returned non-zero code {res.returncode}. Will retry in 5 minutes.", flush=True)
                    time.sleep(300)
                    continue
            
            time.sleep(30)
        except Exception as e:
            print(f"[SCHEDULER] Exception in scheduler loop: {e}", flush=True)
            time.sleep(60)

if __name__ == "__main__":
    # Start HTTP server in a separate thread
    server_thread = threading.Thread(target=run_http_server, daemon=True)
    server_thread.start()
    
    # Run scheduler in the main thread (blocking)
    run_scheduler()
