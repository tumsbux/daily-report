"""
dashboards/git_push.py — GitHub Pages push helper (Phase 3c, 2026-06-14)

Extracted from update_dashboard.py (Step 7 block).
"""

import os
import json
import shutil
import subprocess
from datetime import date


def push_to_github(folder, push_files, github_url, repo_dir,
                   days_elapsed, days_in_month, month_name):
    """Clone repo, copy files, commit, and push to GitHub Pages (main branch).

    Args:
        folder:       local working dir (source of push_files)
        push_files:   list of filenames to copy & commit
        github_url:   authenticated git remote URL
        repo_dir:     temp directory for the git clone
        days_elapsed: int — used in commit message
        days_in_month: int — used in commit message
        month_name:   str — used in commit message
    """
    try:
        if os.path.exists(os.path.join(repo_dir, '.git')):
            subprocess.run(['git', '-C', repo_dir, 'pull', '--ff-only'],
                           check=True, capture_output=True)
        else:
            subprocess.run(['git', 'clone', github_url, repo_dir],
                           check=True, capture_output=True)

        # Stamp product_data.json with today's date so it always gets committed
        prod_json = os.path.join(folder, 'product_data.json')
        if os.path.exists(prod_json):
            import json as _pj
            _pd = _pj.load(open(prod_json, encoding='utf-8'))
            _pd['generated'] = str(date.today())
            with open(prod_json, 'w', encoding='utf-8') as _pf:
                _pj.dump(_pd, _pf, ensure_ascii=False, separators=(',', ':'))
            print('    product_data.json generated -> %s' % date.today())

        for fname in push_files:
            src = os.path.join(folder, fname)
            dst = os.path.join(repo_dir, fname)
            if os.path.exists(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

        _env = os.environ.copy()
        _env['GIT_AUTHOR_NAME']     = 'Dashboard Bot'
        _env['GIT_AUTHOR_EMAIL']    = 'bot@dashboard'
        _env['GIT_COMMITTER_NAME']  = 'Dashboard Bot'
        _env['GIT_COMMITTER_EMAIL'] = 'bot@dashboard'

        subprocess.run(['git', '-C', repo_dir, 'add', '-A'],
                       capture_output=True, env=_env)
        _cr = subprocess.run(
            ['git', '-C', repo_dir, 'commit', '-m',
             'auto: Day %d/%d %s' % (days_elapsed, days_in_month, month_name)],
            capture_output=True, text=True, env=_env)

        if 'nothing to commit' in (_cr.stdout + _cr.stderr):
            print('  GitHub: nothing to commit (data unchanged)')
        else:
            _pr = subprocess.run(
                ['git', '-C', repo_dir, 'push', 'origin', 'main'],
                capture_output=True, text=True, env=_env)
            if _pr.returncode == 0:
                print('  GitHub: pushed OK')
            else:
                print('  WARNING: push failed: ' + _pr.stderr[-200:])

    except Exception as _e:
        print('  WARNING: GitHub push failed: ' + str(_e))
    finally:
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)
