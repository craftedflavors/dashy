"""SQLite system of record. One connection per thread; WAL so the web threads and agents don't block."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from . import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
  id INTEGER PRIMARY KEY, hash TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL, sector TEXT, country TEXT, location TEXT, employer TEXT,
  salary_text TEXT, url TEXT, source TEXT, source_tier INTEGER DEFAULT 4,
  visa_signal INTEGER DEFAULT 0, status TEXT DEFAULT 'lead', summary TEXT,
  found_at TEXT, updated_at TEXT, expires_at TEXT
);
CREATE INDEX IF NOT EXISTS opp_status ON opportunities(status, found_at);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, ref TEXT UNIQUE NOT NULL, product TEXT, name TEXT, contact TEXT,
  details TEXT, amount_pkr INTEGER, status TEXT DEFAULT 'requested', method TEXT,
  created_at TEXT, claimed_at TEXT, paid_at TEXT, delivered_at TEXT, consent_at TEXT
);
CREATE TABLE IF NOT EXISTS profiles (
  id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, name TEXT, contact TEXT, data TEXT,
  created_at TEXT, consent_at TEXT
);
CREATE TABLE IF NOT EXISTS partners (
  id INTEGER PRIMARY KEY, org_name TEXT, org_type TEXT, country TEXT, licence_no TEXT,
  registry_no TEXT, contact_name TEXT, email TEXT, phone TEXT, website TEXT, tier TEXT,
  message TEXT, status TEXT DEFAULT 'pending', slug TEXT UNIQUE, created_at TEXT,
  decided_at TEXT, consent_at TEXT
);
CREATE TABLE IF NOT EXISTS employer_requests (
  id INTEGER PRIMARY KEY, company TEXT, country TEXT, sector TEXT, roles TEXT, headcount INTEGER,
  contact_name TEXT, email TEXT, phone TEXT, message TEXT, status TEXT DEFAULT 'new',
  created_at TEXT, consent_at TEXT
);
CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY, created_at TEXT, colour TEXT, score INTEGER, traps TEXT, channel TEXT
);
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY, created_at TEXT, mode TEXT, matched TEXT, answered INTEGER
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, at TEXT, actor TEXT, action TEXT, target TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS dsar (
  id INTEGER PRIMARY KEY, at TEXT, contact TEXT, kind TEXT, status TEXT DEFAULT 'open',
  resolved_at TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS scout_runs (
  id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, source TEXT,
  fetched INTEGER DEFAULT 0, added INTEGER DEFAULT 0, error TEXT
);
"""

_local = threading.local()
_init_lock = threading.Lock()
_initialised = set()


def now_iso(delta_days=0):
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).isoformat(timespec="seconds")


def db_path():
    return os.environ.get("MUSA_DB") or os.path.join(DATA_DIR, "musa.db")


def conn():
    path = db_path()
    c = getattr(_local, "conns", {}).get(path)
    if c is None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        c = sqlite3.connect(path, timeout=10, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        with _init_lock:
            if path not in _initialised:
                c.executescript(SCHEMA)
                _initialised.add(path)
        if not hasattr(_local, "conns"):
            _local.conns = {}
        _local.conns[path] = c
    return c


def q(sql, args=(), one=False):
    cur = conn().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def x(sql, args=()):
    c = conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur.lastrowid


def xc(sql, args=()):
    """Execute and return the number of rows changed."""
    c = conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur.rowcount


def insert(table, **fields):
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    return x("INSERT INTO %s (%s) VALUES (%s)" % (table, cols, marks), tuple(fields.values()))


def audit(actor, action, target="", detail=None):
    insert("audit", at=now_iso(), actor=actor, action=action, target=str(target),
           detail=json.dumps(detail, ensure_ascii=False) if detail is not None else "")


def count(sql, args=()):
    row = q(sql, args, one=True)
    return row[0] if row else 0
