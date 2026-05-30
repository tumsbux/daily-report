#!/usr/bin/env python3
"""
push_py_to_github.py
Uploads files to GitHub repo via Git Data API (handles any file size).
Run: py push_py_to_github.py
"""
import json, os, base64, urllib.request, urllib.error

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

FILES_TO_PUSH = [
    # HTML dashboards (large files — use Git Data API)
    'fraud_dashboard.html',
    'sales_dashboard_v8.html',
    # Python scripts
    'update_dashboard.py',
    'rebuild_fraud_analysis.py',
    'build_product_data.py',
    'inject_fraud_only.py',
    # Workflow
    '.github/workflows/daily-update.yml',
    # SQL files
    'data-lake_dim_branch.sql',
    'data-lake_dim_item_barcode.sql',
    'data-lake_dim_product.sql',
    # data-lake_fact_returns.sql — not needed, script queries fact_returns from MySQL directly
    # data-lake_fact_sales.sql   — not needed, script queries fact_sales from MySQL directly
]

def api_request(method, path, body=None):
    url  = f'{API}/{path}'
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'HTTP {e.code} on {method} {path}: {e.read().decode()[:300]}')

def get_branch_info():
    """Get current commit SHA and tree SHA for the branch."""
    ref, _ = api_request('GET', f'repos/{REPO}/git/ref/heads/{BRANCH}')
    commit_sha = ref['object']['sha']
    commit, _  = api_request('GET', f'repos/{REPO}/git/commits/{commit_sha}')
    tree_sha   = commit['tree']['sha']
    return commit_sha, tree_sha

def create_blob(content_bytes):
    """Upload raw bytes as a blob, return blob SHA."""
    body = {
        'content':  base64.b64encode(content_bytes).decode(),
        'encoding': 'base64',
    }
    result, _ = api_request('POST', f'repos/{REPO}/git/blobs', body)
    return result['sha']

def push_all():
    print('Reading current branch state...')
    parent_sha, base_tree_sha = get_branch_info()
    print(f'  Parent commit: {parent_sha[:8]}')

    tree_items = []
    for fname in FILES_TO_PUSH:
        local_path = os.path.join(FOLDER, fname)
        if not os.path.exists(local_path):
            print(f'  SKIP (not found): {fname}')
            continue

        size_kb = os.path.getsize(local_path) // 1024
        print(f'  Uploading {fname} ({size_kb:,} KB)...', end=' ', flush=True)
        with open(local_path, 'rb') as f:
            content = f.read()

        blob_sha = create_blob(content)
        tree_items.append({
            'path': fname,
            'mode': '100644',
            'type': 'blob',
            'sha':  blob_sha,
        })
        print('OK')

    if not tree_items:
        print('No files to push.')
        return

    print(f'\nCreating tree with {len(tree_items)} file(s)...')
    new_tree, _ = api_request('POST', f'repos/{REPO}/git/trees', {
        'base_tree': base_tree_sha,
        'tree':      tree_items,
    })

    print('Creating commit...')
    new_commit, _ = api_request('POST', f'repos/{REPO}/git/commits', {
        'message': 'update: push fixed dashboards + scripts',
        'tree':    new_tree['sha'],
        'parents': [parent_sha],
    })

    print('Updating branch ref...')
    api_request('PATCH', f'repos/{REPO}/git/refs/heads/{BRANCH}', {
        'sha':   new_commit['sha'],
        'force': True,
    })

    print(f'\nDone! {len(tree_items)} file(s) pushed to {BRANCH}.')
    print('Now go to GitHub Actions -> Daily Dashboard Update -> Run workflow.')

push_all()
