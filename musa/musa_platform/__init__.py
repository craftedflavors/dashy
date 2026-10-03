"""MUSA Corridor — the verify-first platform for Pakistan → Cyprus/EU work, study and hiring.

One process, standard library only: web app + JSON API + background agents (Scout scraper,
retention) on SQLite. Reuses the MUSA Sentinel engine for scam detection, matching and payments.
"""
import os
import sys

__version__ = "1.0.0"

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
MUSA_DIR = os.path.dirname(PKG_DIR)
DATA_DIR = os.environ.get("MUSA_DATA_DIR", os.path.join(MUSA_DIR, "data"))
STATIC_DIR = os.path.join(PKG_DIR, "static")

if MUSA_DIR not in sys.path:  # allow `python -m musa_platform` from anywhere
    sys.path.insert(0, MUSA_DIR)
