"""
database.py — FilterGuardian SQLite layer
=========================================
Handles all DB reads/writes. Schema is auto-migrated on init so existing
databases gain new columns without losing data.
"""

import sqlite3

DB_PATH = "proxies.db"

def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS blacklisted_urls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT UNIQUE,
            author      TEXT,
            channel_id  TEXT,
            status      TEXT    DEFAULT "pending",
            category    TEXT,
            site_name   TEXT,
            fingerprint TEXT,
            platform    TEXT,
            proxy_tech  TEXT,
            final_url   TEXT,
            timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Safe migration: add new columns to existing databases
    for col, defn in [
        ("platform",   "TEXT DEFAULT ''"),
        ("proxy_tech", "TEXT DEFAULT ''"),
        ("final_url",  "TEXT DEFAULT ''"),
    ]:
        try:
            c.execute(f"ALTER TABLE blacklisted_urls ADD COLUMN {col} {defn}")
        except sqlite3.OperationalError:
            pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS blacklisted_channels (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_name TEXT,
            server_name  TEXT,
            reason       TEXT,
            timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_name, server_name)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS filter_results (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            url        TEXT,
            site_name  TEXT,
            result     TEXT,
            detail     TEXT,
            method     TEXT,
            tested_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def sanitize_url(url: str) -> str:
    """
    Strip markdown/bracket/quote artifacts from a captured URL.

    Discord messages embed links as `[text](url)` or `<url>`, and scraping
    sometimes yields `url](url`. The first whitespace/bracket/quote/angle
    delimiter ends the real URL, so cut there and trim trailing punctuation.
    Funnels every entry path (scraper + manual entry) through one cleaner.
    """
    import re as _re
    if not url:
        return url
    url = url.strip()
    # Prefer an explicit http(s) URL anywhere in the string — handles
    # '[text](https://site)', '<https://site>', and 'https://site](https://site'.
    m = _re.search(r'https?://[^\s\'"<>\[\]()]+', url)
    token = m.group(0) if m else _re.split(r'[\s\'"<>\[\]()]+', url)[0]
    return token.rstrip('.,;!?)]}')


def add_url(url: str, author: str, channel_id: str, db_path=DB_PATH) -> bool:
    url = sanitize_url(url)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO blacklisted_urls (url, author, channel_id) VALUES (?,?,?)",
                  (url, author, channel_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_pending_urls(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, url FROM blacklisted_urls WHERE status='pending'")
    rows = c.fetchall()
    conn.close()
    return rows

def reset_failed_urls(db_path=DB_PATH) -> int:
    """
    Reset retriable failures back to 'pending' so the brain will retry them.
    Only resets entries whose failure reason was a connectivity problem
    (Unreachable / Analysis Error), not intentional rejections (Invalid URL).
    Returns the count of rows reset.
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        UPDATE blacklisted_urls
        SET status='pending', site_name=NULL, category=NULL,
            fingerprint=NULL, platform=NULL, proxy_tech=NULL, final_url=NULL
        WHERE status='failed'
          AND site_name IN ('Unreachable', 'Analysis Error', 'Hard Network Block')
    """)
    count = c.rowcount
    conn.commit()
    conn.close()
    return count

def update_analysis(url_id: int, status: str, category: str = None,
                    site_name: str = None, fingerprint: str = None,
                    platform: str = None, proxy_tech: str = None,
                    final_url: str = None, db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute('''UPDATE blacklisted_urls
        SET status=?, category=?, site_name=?, fingerprint=?, platform=?, proxy_tech=?, final_url=?
        WHERE id=?''',
        (status, category, site_name, fingerprint, platform, proxy_tech, final_url, url_id))
    conn.commit()
    conn.close()

def get_all_urls(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT id, status, site_name, category, platform, proxy_tech, url, channel_id, timestamp
                 FROM blacklisted_urls ORDER BY timestamp DESC""")
    rows = c.fetchall()
    conn.close()
    return rows

def search_urls(query: str, db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    q = f"%{query}%"
    c.execute("""SELECT id, status, site_name, category, platform, proxy_tech, url, channel_id, timestamp
                 FROM blacklisted_urls
                 WHERE url LIKE ? OR site_name LIKE ? OR category LIKE ?
                       OR platform LIKE ? OR proxy_tech LIKE ? OR channel_id LIKE ?
                 ORDER BY timestamp DESC""", (q,q,q,q,q,q))
    rows = c.fetchall()
    conn.close()
    return rows

def delete_url(url_id: int, db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM blacklisted_urls WHERE id=?", (url_id,))
    conn.commit()
    conn.close()

def update_url_manual(url_id: int, site_name: str, category: str,
                      platform: str, proxy_tech: str, status: str,
                      db_path=DB_PATH):
    """User-initiated edit of a URL record's classification fields."""
    conn = sqlite3.connect(db_path)
    conn.execute('''UPDATE blacklisted_urls
        SET site_name=?, category=?, platform=?, proxy_tech=?, status=?
        WHERE id=?''',
        (site_name, category, platform, proxy_tech, status, url_id))
    conn.commit()
    conn.close()

def requeue_url(url_id: int, db_path=DB_PATH):
    """Reset a single URL to pending so the brain re-analyzes it."""
    conn = sqlite3.connect(db_path)
    conn.execute('''UPDATE blacklisted_urls
        SET status='pending', site_name=NULL, category=NULL,
            fingerprint=NULL, platform=NULL, proxy_tech=NULL, final_url=NULL
        WHERE id=?''', (url_id,))
    conn.commit()
    conn.close()

def get_distinct_categories(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT DISTINCT category FROM blacklisted_urls
                 WHERE category IS NOT NULL AND category != ''
                 ORDER BY category""")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows

def get_distinct_platforms(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT DISTINCT platform FROM blacklisted_urls
                 WHERE platform IS NOT NULL AND platform != ''
                 ORDER BY platform""")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows

def get_url_detail(url_id: int, db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM blacklisted_urls WHERE id=?", (url_id,))
    row = c.fetchone()
    names = [d[0] for d in c.description]
    conn.close()
    return dict(zip(names, row)) if row else {}

def get_stats(db_path=DB_PATH) -> dict:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM blacklisted_urls"); total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM blacklisted_urls WHERE status='analyzed'"); analyzed = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM blacklisted_urls WHERE status='pending'"); pending = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM blacklisted_urls WHERE status='failed'"); failed = c.fetchone()[0]
    conn.close()
    return {"total": total, "analyzed": analyzed, "pending": pending, "failed": failed}

def get_category_breakdown(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT COALESCE(NULLIF(category,''),'Unclassified'), COUNT(*)
                 FROM blacklisted_urls WHERE status='analyzed'
                 GROUP BY category ORDER BY COUNT(*) DESC""")
    rows = c.fetchall()
    conn.close()
    return rows

def get_platform_breakdown(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT COALESCE(NULLIF(platform,''),'Unknown'), COUNT(*)
                 FROM blacklisted_urls WHERE status='analyzed'
                 GROUP BY platform ORDER BY COUNT(*) DESC LIMIT 12""")
    rows = c.fetchall()
    conn.close()
    return rows

def get_top_site_names(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT site_name, COUNT(*) as cnt
                 FROM blacklisted_urls
                 WHERE status='analyzed'
                   AND site_name IS NOT NULL
                   AND length(site_name) > 2
                   AND site_name NOT IN (
                       'Unknown','Analysis Error','Invalid URL',
                       'Unreachable','Self-Hosted / Unknown'
                   )
                 GROUP BY site_name
                 ORDER BY cnt DESC
                 LIMIT 15""")
    rows = c.fetchall()
    conn.close()
    return rows

def get_proxy_tech_breakdown(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT COALESCE(NULLIF(proxy_tech,''),'Unknown/Custom'), COUNT(*)
                 FROM blacklisted_urls WHERE status='analyzed'
                 GROUP BY proxy_tech ORDER BY COUNT(*) DESC LIMIT 10""")
    rows = c.fetchall()
    conn.close()
    return rows

def get_timeline(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT DATE(timestamp), COUNT(*) FROM blacklisted_urls
                 GROUP BY DATE(timestamp) ORDER BY DATE(timestamp) DESC LIMIT 30""")
    rows = list(reversed(c.fetchall()))
    conn.close()
    return rows

def get_top_sources(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT channel_id, COUNT(*) as cnt FROM blacklisted_urls
                 GROUP BY channel_id ORDER BY cnt DESC LIMIT 10""")
    rows = c.fetchall()
    conn.close()
    return rows

def get_site_name_by_domain(domain: str, db_path=DB_PATH) -> str:
    """Return the most-used site name for URLs whose host matches domain."""
    if not domain:
        return ""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""SELECT site_name, COUNT(*) as cnt
                 FROM blacklisted_urls
                 WHERE (url LIKE ? OR final_url LIKE ?)
                   AND status IN ('analyzed','reviewed')
                   AND site_name IS NOT NULL AND site_name != ''
                   AND site_name NOT IN ('Unknown','Analysis Error','Unreachable')
                 GROUP BY site_name ORDER BY cnt DESC LIMIT 1""",
              (f"%://{domain}/%", f"%://{domain}/%"))
    row = c.fetchone()
    # Also try without trailing slash (exact domain match)
    if not row:
        c.execute("""SELECT site_name, COUNT(*) as cnt
                     FROM blacklisted_urls
                     WHERE (url LIKE ? OR final_url LIKE ?)
                       AND status IN ('analyzed','reviewed')
                       AND site_name IS NOT NULL AND site_name != ''
                       AND site_name NOT IN ('Unknown','Analysis Error','Unreachable')
                     GROUP BY site_name ORDER BY cnt DESC LIMIT 1""",
                  (f"%://{domain}", f"%://{domain}"))
        row = c.fetchone()
    conn.close()
    return row[0] if row else ""

def update_site_name_by_domain(domain: str, site_name: str, db_path=DB_PATH) -> int:
    """Set site_name for all analyzed/reviewed records whose URL host matches domain."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""UPDATE blacklisted_urls SET site_name=?
                 WHERE (url LIKE ? OR url LIKE ?)
                   AND status IN ('analyzed','reviewed')""",
              (site_name, f"%://{domain}/%", f"%://{domain}"))
    count = c.rowcount
    conn.commit()
    conn.close()
    return count

def propagate_names_by_domain(db_path=DB_PATH) -> int:
    """
    For every domain that has at least one named analyzed/reviewed record,
    copy the most common name to all same-domain records that are unnamed.
    Returns total number of records updated.
    """
    from urllib.parse import urlparse
    from collections import defaultdict, Counter

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, url, final_url, site_name FROM blacklisted_urls WHERE status IN ('analyzed','reviewed')")
    rows = c.fetchall()
    conn.close()

    domain_names: dict[str, Counter] = defaultdict(Counter)
    domain_records: dict[str, list] = defaultdict(list)

    for uid, url, final_url, site_name in rows:
        for u in (url, final_url):
            if not u:
                continue
            try:
                d = urlparse(u).netloc.lower()
            except Exception:
                continue
            if d:
                domain_records[d].append((uid, site_name or ""))
                if site_name and site_name not in ("Unknown","Analysis Error","Unreachable"):
                    domain_names[d][site_name] += 1

    updated = 0
    for domain, counter in domain_names.items():
        canonical = counter.most_common(1)[0][0]
        for uid, name in domain_records.get(domain, []):
            if not name:
                conn2 = sqlite3.connect(db_path)
                conn2.execute("UPDATE blacklisted_urls SET site_name=? WHERE id=?",
                              (canonical, uid))
                conn2.commit()
                conn2.close()
                updated += 1
    return updated

def get_domain_groups(db_path=DB_PATH) -> list:
    """
    Return domains where records have conflicting or missing site names —
    potential duplicates for operator consolidation.
    Each entry: (domain, [(uid, url, site_name), ...])
    """
    from urllib.parse import urlparse
    from collections import defaultdict

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, url, site_name FROM blacklisted_urls WHERE status IN ('analyzed','reviewed')")
    rows = c.fetchall()
    conn.close()

    groups: dict[str, list] = defaultdict(list)
    for uid, url, site_name in rows:
        try:
            d = urlparse(url).netloc.lower()
        except Exception:
            continue
        if d:
            groups[d].append((uid, url, site_name or ""))

    result = []
    for domain, records in groups.items():
        if len(records) < 2:
            continue
        distinct_names = set(r[2] for r in records if r[2])
        has_unnamed = any(not r[2] for r in records)
        if len(distinct_names) > 1 or has_unnamed:
            result.append((domain, records))

    return sorted(result, key=lambda x: len(x[1]), reverse=True)

def mark_reviewed(url_id: int, db_path=DB_PATH):
    """Set a URL's status to 'reviewed' (operator confirmed: not a bypass proxy)."""
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE blacklisted_urls SET status='reviewed' WHERE id=?", (url_id,))
    conn.commit()
    conn.close()

def count_by_fingerprint(fingerprint: str, db_path=DB_PATH) -> int:
    """Return how many URL records share this fingerprint."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM blacklisted_urls WHERE fingerprint=?", (fingerprint,))
    count = c.fetchone()[0]
    conn.close()
    return count

def update_site_name_by_fingerprint(fingerprint: str, site_name: str, db_path=DB_PATH) -> int:
    """Update site_name for all analyzed records that share the same fingerprint."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""UPDATE blacklisted_urls SET site_name=?
                 WHERE fingerprint=? AND status='analyzed'""",
              (site_name, fingerprint))
    count = c.rowcount
    conn.commit()
    conn.close()
    return count

def export_blacklist(db_path=DB_PATH, export_file="export.txt") -> int:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT url FROM blacklisted_urls")
    urls = [r[0] for r in c.fetchall()]
    conn.close()
    with open(export_file, "w", encoding="utf-8") as f:
        f.write("\n".join(urls))
    return len(urls)

def blacklist_channel(channel_name, server_name, reason="trap", db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT OR IGNORE INTO blacklisted_channels (channel_name,server_name,reason) VALUES (?,?,?)",
                     (channel_name, server_name, reason))
        conn.commit()
    finally:
        conn.close()

def is_channel_blacklisted(channel_name, server_name, db_path=DB_PATH) -> bool:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id FROM blacklisted_channels WHERE channel_name=? AND server_name=?",
              (channel_name, server_name))
    row = c.fetchone()
    conn.close()
    return row is not None


def save_filter_results(session_id: str, results: list, method: str, db_path=DB_PATH):
    """Persist filter test results. results: [(url, site_name, result, detail), ...]"""
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO filter_results (session_id, url, site_name, result, detail, method) "
        "VALUES (?,?,?,?,?,?)",
        [(session_id, url, site, res, detail, method) for url, site, res, detail in results]
    )
    conn.commit()
    conn.close()


def get_filter_summary(db_path=DB_PATH) -> dict:
    """
    Returns stats on filter test results using the most recent test result per URL,
    so re-testing a URL that was later blocked won't inflate the bypass count.
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN result='allowed' THEN 1 ELSE 0 END) as allowed,
               SUM(CASE WHEN result='blocked' THEN 1 ELSE 0 END) as blocked,
               SUM(CASE WHEN result='dead' THEN 1 ELSE 0 END) as dead,
               MAX(tested_at) as last_tested
        FROM (
            SELECT url, result, MAX(tested_at) as tested_at
            FROM filter_results
            GROUP BY url
        )
    """)
    row = c.fetchone()
    c.execute("SELECT COUNT(DISTINCT session_id) FROM filter_results")
    sessions = c.fetchone()[0]
    conn.close()
    if not row or not row[0]:
        return {"total": 0, "allowed": 0, "blocked": 0, "dead": 0,
                "last_tested": None, "sessions": 0}
    return {
        "total":       row[0] or 0,
        "allowed":     row[1] or 0,
        "blocked":     row[2] or 0,
        "dead":        row[3] or 0,
        "last_tested": row[4],
        "sessions":    sessions or 0,
    }


def get_bypassing_urls(db_path=DB_PATH) -> list:
    """Return [(url, site_name, method, tested_at)] where most recent test result is 'allowed'."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT r.url, r.site_name, r.method, r.tested_at
        FROM filter_results r
        INNER JOIN (
            SELECT url, MAX(tested_at) as max_ts
            FROM filter_results GROUP BY url
        ) latest ON r.url = latest.url AND r.tested_at = latest.max_ts
        WHERE r.result = 'allowed'
        ORDER BY r.tested_at DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows
