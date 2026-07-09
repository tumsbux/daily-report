#!/usr/bin/env python3
"""
push_files_api.py — push ไฟล์ที่ระบุ (เท่านั้น) ขึ้น main ผ่าน Git Data API
ใช้แทน push_py_to_github.py เมื่อแก้ไฟล์ไม่กี่ตัว — กัน regression จาก dashboard HTML เก่าใน list ใหญ่

รัน: py push_files_api.py <file1> [file2 ...] [-m "commit message"]
เช่น: py push_files_api.py product_dashboard.html -m "feat: rename avg qty/day column"
"""
import json, os, sys, base64, time, urllib.request, urllib.error

FOLDER = os.path.dirname(os.path.abspath(__file__))
cfg    = json.load(open(os.path.join(FOLDER, 'db_config.json')))
TOKEN  = cfg['github_token']
REPO   = cfg.get('github_repo', 'tumsbux/daily-report')
BRANCH = 'main'
API    = 'https://api.github.com'

HEADERS = {
    'Authorization': f'token {TOKEN}',
    'Accept':        'application/vnd.github+json',
    'Content-Type':  'application/json',
}


def api(method, path, body=None, retries=4):
    url  = f'{API}/{path}'
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < retries - 1:
                wait = 10 * (attempt + 1)
                print(f'\n    HTTP {e.code} — retry {attempt + 1}/{retries - 1} in {wait}s...', flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f'HTTP {e.code} on {method} {path}: {e.read().decode()[:300]}')
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(10 * (attempt + 1))
                continue
            raise


def main():
    args = sys.argv[1:]
    msg = 'update: push via push_files_api.py'
    if '-m' in args:
        i = args.index('-m')
        msg = args[i + 1]
        args = args[:i] + args[i + 2:]
    raw = [a.replace('\\', '/') for a in args]
    files = []
    for a in raw:
        local = os.path.join(FOLDER, a)
        if os.path.isdir(local):
            for root, _dirs, fnames in os.walk(local):
                for fn in fnames:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, FOLDER).replace('\\', '/')
                    files.append(rel)
        else:
            files.append(a)
    if not files:
        print(__doc__)
        sys.exit(1)

    # ห้าม push secrets / cache
    BLOCKED = {'db_config.json'}
    for f in files:
        if os.path.basename(f) in BLOCKED or f.startswith('cache/'):
            print(f'ERROR: {f} ห้าม push (secrets/cache)'); sys.exit(1)

    ref    = api('GET', f'repos/{REPO}/git/ref/heads/{BRANCH}')
    parent = ref['object']['sha']
    commit = api('GET', f'repos/{REPO}/git/commits/{parent}')
    print(f'Parent: {parent[:8]}')

    tree_items = []
    for fname in files:
        local = os.path.join(FOLDER, fname)
        if not os.path.exists(local):
            print(f'  SKIP (not found): {fname}'); continue
        print(f'  Uploading {fname} ({os.path.getsize(local)//1024:,} KB)...', end=' ', flush=True)
        with open(local, 'rb') as fh:
            blob = api('POST', f'repos/{REPO}/git/blobs', {
                'content': base64.b64encode(fh.read()).decode(), 'encoding': 'base64'})
        tree_items.append({'path': fname, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        print('OK')

    if not tree_items:
        print('No files to push.'); return
    tree = api('POST', f'repos/{REPO}/git/trees',
               {'base_tree': commit['tree']['sha'], 'tree': tree_items})
    new = api('POST', f'repos/{REPO}/git/commits',
              {'message': msg, 'tree': tree['sha'], 'parents': [parent]})
    api('PATCH', f'repos/{REPO}/git/refs/heads/{BRANCH}', {'sha': new['sha'], 'force': False})
    print(f'\nDone! commit {new["sha"][:8]} — {len(tree_items)} file(s) -> {BRANCH}')


main()
