from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import time
import os
import sqlite3
from contextlib import closing


app = Flask(__name__, static_folder='public', static_url_path='/static')
CORS(app)


GRAPHQL_ENDPOINTS = {
    'com': 'https://leetcode.com/graphql',
    'cn': 'https://leetcode.cn/graphql'
}

# REST endpoints (more stable, no CSRF):
REST_ENDPOINTS = {
    'com': 'https://leetcode.com/api/problems/all/',
    'cn': 'https://leetcode.cn/api/problems/all/'
}

# Simple in-memory cache for REST list
_CACHE = {
    'com': { 'ts': 0, 'data': [] },
    'cn': { 'ts': 0, 'data': [] }
}
_CACHE_TTL_SECONDS = 600


# ---------------------- SQLite storage (SRS) ----------------------
DB_PATH = os.path.join(os.path.dirname(__file__), 'data.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(get_db()) as db:
        cur = db.cursor()
        cur.execute(
            '''CREATE TABLE IF NOT EXISTS user_items (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   title_slug TEXT UNIQUE,
                   title TEXT,
                   link TEXT,
                   frontend_id TEXT,
                   difficulty TEXT,
                   stage INTEGER DEFAULT 0,
                   next_due_ts INTEGER DEFAULT 0,
                   last_result TEXT,
                   created_ts INTEGER,
                   updated_ts INTEGER
               )'''
        )
        db.commit()
        # --- Migration for older DBs: ensure 'link' column exists ---
        try:
            cur.execute("PRAGMA table_info(user_items)")
            cols = [r['name'] for r in cur.fetchall()]
            if 'link' not in cols:
                # Add 'link' column for custom problem URLs
                cur.execute("ALTER TABLE user_items ADD COLUMN link TEXT")
                db.commit()
        except Exception:
            # If PRAGMA or ALTER fails for any reason, continue silently;
            # application will still work for new tables.
            pass


def _start_of_today_ts() -> int:
    # Local timezone midnight
    t = time.localtime()
    midnight_struct = (t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, t.tm_wday, t.tm_yday, t.tm_isdst)
    return int(time.mktime(midnight_struct))


def srs_intervals_days():
    # in days: 0, 1, 3, 7, 14, 30, 60
    return [0, 1, 3, 7, 14, 30, 60]


def schedule_next(stage: int, success: bool) -> int:
    # Return unix ts at local midnight for the target day
    days = srs_intervals_days()
    today0 = _start_of_today_ts()
    if success:
        next_stage = min(stage + 1, len(days) - 1)
        offset_days = days[next_stage]
    else:
        # on fail, review tomorrow and step back a stage (handled by caller)
        offset_days = 1
    return today0 + offset_days * 86400


init_db()


def _perform_request(endpoint: str, query: str, variables: dict, headers: dict):
    resp = requests.post(endpoint, json={'query': query, 'variables': variables}, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _fetch_all_problems_rest(site: str):
    # Use cached if fresh
    now = int(time.time())
    cache = _CACHE.get(site) or {'ts': 0, 'data': []}
    if cache['data'] and now - cache['ts'] < _CACHE_TTL_SECONDS:
        return cache['data']

    url = REST_ENDPOINTS.get(site, REST_ENDPOINTS['com'])
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'Referer': 'https://leetcode.cn/' if site == 'cn' else 'https://leetcode.com/'
    }

    # 尝试请求当前站点，如遇 403（尤其是 leetcode.cn 常见的风控）则自动降级为 .com 站点
    resp = requests.get(url, headers=headers, timeout=25)
    if resp.status_code == 403 and site == 'cn':
        # fallback 到 leetcode.com 的 REST 列表，题目 ID 和 slug 仍然可用于跳转到 .cn 站点
        alt_url = REST_ENDPOINTS['com']
        alt_headers = {
            'User-Agent': headers['User-Agent'],
            'Referer': 'https://leetcode.com/'
        }
        alt_resp = requests.get(alt_url, headers=alt_headers, timeout=25)
        alt_resp.raise_for_status()
        data = alt_resp.json() or {}
    else:
        resp.raise_for_status()
        data = resp.json() or {}
    pairs = data.get('stat_status_pairs') or []

    def to_diff(level: int) -> str:
        return 'Easy' if level == 1 else ('Medium' if level == 2 else ('Hard' if level == 3 else 'Unknown'))

    normalized = []
    for it in pairs:
        stat = it.get('stat') or {}
        total_acs = stat.get('total_acs') or 0
        total_submitted = stat.get('total_submitted') or 0
        ac_rate = (float(total_acs) / float(total_submitted) * 100.0) if total_submitted else 0.0
        normalized.append({
            'acRate': ac_rate,
            'difficulty': to_diff(((it.get('difficulty') or {}).get('level')) or 0),
            'frontendQuestionId': str(stat.get('frontend_question_id') or ''),
            'paidOnly': bool(it.get('paid_only')),
            'title': stat.get('question__title') or '',
            'titleSlug': stat.get('question__title_slug') or '',
            'topicTags': []  # REST endpoint doesn't include tags
        })

    _CACHE[site] = { 'ts': now, 'data': normalized }
    return normalized


def search_problems(keyword: str, skip: int, limit: int, site: str):
    # Prefer REST (more reliable) and filter locally; keep GraphQL code below as fallback if needed
    all_items = _fetch_all_problems_rest(site)
    key = (keyword or '').strip().lower()
    if key:
        filtered = [x for x in all_items if (key in (x.get('title','').lower()) or key in (x.get('titleSlug','').lower()) or key in (x.get('frontendQuestionId','').lower()))]
    else:
        filtered = all_items
    total = len(filtered)
    page_slice = filtered[skip: skip + limit]
    return { 'total': total, 'questions': page_slice }

    # --- GraphQL fallback (unused unless you decide to switch back) ---
    query = '''
    query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
      problemsetQuestionList(categorySlug: $categorySlug, limit: $limit, skip: $skip, filters: $filters) {
        total: total
        questions: questions {
          acRate
          difficulty
          freqBar
          frontendQuestionId
          isFavor
          paidOnly
          status
          title
          titleSlug
          hasSolution
          hasVideoSolution
          topicTags { name slug }
        }
      }
    }
    '''
    # LeetCode 需要有效的 categorySlug；普遍可用的是 'all'（有时 'algorithms'）
    variables_primary = {
        'categorySlug': 'all',
        'skip': skip,
        'limit': limit,
        'filters': {'searchKeywords': keyword} if keyword else {}
    }
    variables_fallback = {
        'categorySlug': 'algorithms',
        'skip': skip,
        'limit': limit,
        'filters': {'searchKeywords': keyword} if keyword else {}
    }

    headers = {
        'Content-Type': 'application/json',
        'Referer': 'https://leetcode.cn' if site == 'cn' else 'https://leetcode.com',
        'Origin': 'https://leetcode.cn' if site == 'cn' else 'https://leetcode.com',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'
    }

    # 先用 'all'，如出错再用 'algorithms'，最后尝试切换站点
    try:
        data = _perform_request(endpoint, query, variables_primary, headers)
    except Exception as e_primary:
        try:
            data = _perform_request(endpoint, query, variables_fallback, headers)
        except Exception as e_fallback:
            # 最后尝试切换站点
            alt_site = 'cn' if site == 'com' else 'com'
            alt_endpoint = GRAPHQL_ENDPOINTS.get(alt_site, GRAPHQL_ENDPOINTS['com'])
            try:
                data = _perform_request(alt_endpoint, query, variables_primary, headers)
            except Exception as e_alt:
                raise RuntimeError(f"LeetCode API error: {str(e_alt)} | primary: {str(e_primary)} | fallback: {str(e_fallback)}")
    if 'errors' in data and data['errors']:
        messages = '; '.join([e.get('message', 'Unknown error') for e in data['errors']])
        raise RuntimeError(messages)
    list_obj = (((data or {}).get('data') or {}).get('problemsetQuestionList')) or {}
    return {
        'total': list_obj.get('total', 0),
        'questions': list_obj.get('questions', [])
    }


@app.route('/api/search', methods=['GET'])
def api_search():
    try:
        keyword = str(request.args.get('q', '')).strip()
        try:
            page = int(request.args.get('page', '1'))
        except Exception:
            page = 1
        page = max(1, page)
        try:
            limit = int(request.args.get('limit', '20'))
        except Exception:
            limit = 20
        limit = max(1, min(50, limit))
        # Force CN site only as requested
        site = 'cn'
        skip = (page - 1) * limit

        result = search_problems(keyword, skip, limit, site)
        return jsonify({
            'ok': True,
            'total': result['total'],
            'page': page,
            'limit': limit,
            'site': site,
            'questions': result['questions']
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

# Backward-compat static paths (in case cached HTML still references root paths)
@app.route('/styles.css')
def legacy_styles():
    return send_from_directory(app.static_folder, 'styles.css')

@app.route('/main.js')
def legacy_mainjs():
    return send_from_directory(app.static_folder, 'main.js')


# ---------------------- SRS endpoints ----------------------
@app.route('/api/my/add', methods=['POST'])
def api_my_add():
    try:
        data = request.get_json(force=True) or {}
        title_slug = (data.get('titleSlug') or '').strip()
        title = data.get('title') or ''
        link = data.get('link') or ''
        frontend_id = str(data.get('frontendQuestionId') or '')
        difficulty = data.get('difficulty') or ''
        if not title_slug:
            return jsonify({'ok': False, 'error': 'titleSlug required'}), 400
        now = int(time.time())
        with closing(get_db()) as db:
            cur = db.cursor()
            cur.execute(
                '''INSERT OR IGNORE INTO user_items (title_slug, title, link, frontend_id, difficulty, stage, next_due_ts, last_result, created_ts, updated_ts)
                   VALUES (?, ?, ?, ?, ?, 0, ?, NULL, ?, ?)''',
                (title_slug, title, link, frontend_id, difficulty, now, now, now)
            )
            db.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# 新增自定义题目接口
@app.route('/api/custom_add', methods=['POST'])
def api_custom_add():
    try:
        data = request.get_json(force=True) or {}
        title = (data.get('title') or '').strip()
        link = (data.get('link') or '').strip()
        if not title or not link:
            return jsonify({'ok': False, 'error': 'title和link必填'}), 400
        # 自定义题目没有 title_slug，使用 title 作为唯一标识
        title_slug = title
        now = int(time.time())
        with closing(get_db()) as db:
            cur = db.cursor()
            cur.execute(
                '''INSERT OR IGNORE INTO user_items (title_slug, title, link, frontend_id, difficulty, stage, next_due_ts, last_result, created_ts, updated_ts)
                   VALUES (?, ?, ?, '', '', 0, ?, NULL, ?, ?)''',
                (title_slug, title, link, now, now, now)
            )
            db.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/my/list', methods=['GET'])
def api_my_list():
    try:
        with closing(get_db()) as db:
            cur = db.cursor()
            cur.execute('SELECT title_slug, title, link, frontend_id, difficulty, stage, next_due_ts, last_result FROM user_items ORDER BY updated_ts DESC')
            rows = [dict(r) for r in cur.fetchall()]
        return jsonify({'ok': True, 'items': rows})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/my/today', methods=['GET'])
def api_my_today():
    try:
        today0 = _start_of_today_ts()
        with closing(get_db()) as db:
            cur = db.cursor()
            cur.execute('SELECT title_slug, title, link, frontend_id, difficulty, stage, next_due_ts, last_result FROM user_items WHERE next_due_ts <= ? ORDER BY next_due_ts ASC', (today0,))
            rows = [dict(r) for r in cur.fetchall()]
        return jsonify({'ok': True, 'items': rows, 'today0': today0})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/my/check', methods=['POST'])
def api_my_check():
    try:
        data = request.get_json(force=True) or {}
        title_slug = (data.get('titleSlug') or '').strip()
        success = bool(data.get('success', False))
        if not title_slug:
            return jsonify({'ok': False, 'error': 'titleSlug required'}), 400
        now = int(time.time())
        with closing(get_db()) as db:
            cur = db.cursor()
            cur.execute('SELECT stage FROM user_items WHERE title_slug = ?', (title_slug,))
            row = cur.fetchone()
            stage = int(row['stage']) if row else 0
            next_due = schedule_next(stage, success)
            new_stage = min(stage + 1, len(srs_intervals_days()) - 1) if success else max(stage - 1, 0)
            cur.execute('''UPDATE user_items
                           SET stage = ?, next_due_ts = ?, last_result = ?, updated_ts = ?
                           WHERE title_slug = ?''',
                        (new_stage, next_due, 'ok' if success else 'again', now, title_slug))
            db.commit()
        return jsonify({'ok': True, 'nextDueTs': next_due, 'stage': new_stage})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/my/delete', methods=['POST'])
def api_my_delete():
    try:
        data = request.get_json(force=True) or {}
        title_slug = (data.get('titleSlug') or '').strip()
        if not title_slug:
            return jsonify({'ok': False, 'error': 'titleSlug required'}), 400
        with closing(get_db()) as db:
            cur = db.cursor()
            cur.execute('DELETE FROM user_items WHERE title_slug = ?', (title_slug,))
            db.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '3000'))
    print(f"[boot] Starting Flask server on http://localhost:{port}")
    app.run(host='0.0.0.0', port=port)


