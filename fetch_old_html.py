#!/usr/bin/env python3
"""
fetch_old_html.py
Fetches the last known-good fraud_dashboard.html from GitHub repo history.
Run: py fetch_old_html.py
"""
import json, os, base64, urllib.request, urllib.error

FOLDER = os.path.dirname(os.path.abspath(__file__))
cfg    = json.load(open(os.path.join(FOLDER, 'db_config.json')))
TOKEN  = cfg['github_token']
REPO   = cfg.get('github_repo', 'tumsbux/daily-report')
API    = 'https://api.github.com'

HEADERS = {
    'Authorization': f'token {TOKEN}',
    'Accept':        'application/vnd.github+json',
}

def api_get(path):
    req = urllib.request.Request(f'{API}/{path}', headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def fetch_file_at_commit(commit_sha, filename):
    print(f'Getting tree for commit {commit_sha[:8]}...')
    tree = api_get(f'repos/{REPO}/git/trees/{commit_sha}?recursive=1')
    blob_sha = None
    for item in tree.get('tree', []):
        if item['path'] == filename:
            blob_sha = item['sha']
            print(f'  Found {filename}, blob SHA: {blob_sha[:8]}, size: {item.get("size",0)//1024} KB')
            break
    if not blob_sha:
        print(f'  ERROR: {filename} not found in tree')
        return None
    print(f'  Downloading blob...')
    blob = api_get(f'repos/{REPO}/git/blobs/{blob_sha}')
    content = base64.b64decode(blob['content'])
    return content

# Get commit history for fraud_dashboard.html to find complete versions
print('Fetching commit history for fraud_dashboard.html...')
commits = api_get(f'repos/{REPO}/commits?path=fraud_dashboard.html&per_page=10')
print(f'Found {len(commits)} commits:')
for i, c in enumerate(commits):
    sha = c['sha'][:8]
    msg = c['commit']['message'][:60]
    date = c['commit']['author']['date'][:10]
    print(f'  [{i}] {sha} {date} {msg}')

print()
# Try each commit until we find a complete file (has </script>)
for i, c in enumerate(commits):
    sha = c['sha']
    print(f'\nTrying commit [{i}] {sha[:8]}...')
    content = fetch_file_at_commit(sha, 'fraud_dashboard.html')
    if content is None:
        continue
    text = content.decode('utf-8', errors='replace')
    has_end = '</script>' in text and '</html>' in text
    size_kb = len(content) // 1024
    print(f'  Size: {size_kb} KB | Has </script>: {has_end}')
    if has_end:
        # Count braces to verify D block is closed
        d_pos = text.find('const D = {')
        if d_pos >= 0:
            d_start = d_pos + len('const D = ')
            depth = 0; i2 = d_start; d_end = None
            in_str = False; esc = False
            while i2 < len(text):
                ch = text[i2]
                if esc: esc = False
                elif ch == '\\': esc = True
                elif ch == '"' and not esc: in_str = not in_str
                elif not in_str:
                    if ch == '{': depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0: d_end = i2 + 1; break
                i2 += 1
            print(f'  D block closed: {d_end is not None}')
            if d_end:
                suffix_len = len(text) - d_end
                print(f'  JS after D block: {suffix_len} chars')
        out_path = os.path.join(FOLDER, 'fraud_dashboard_recovered.html')
        with open(out_path, 'wb') as f:
            f.write(content)
        print(f'\n  SAVED to fraud_dashboard_recovered.html')
        print('  Now verify it looks correct, then rename it to fraud_dashboard.html')
        break
else:
    print('\nNo complete version found in recent history.')
    print('Try fetching an older commit manually.')
