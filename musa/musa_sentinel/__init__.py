"""MUSA Visa Sentinel — cross-border recruitment due-diligence & transaction-control engine.

Pure standard library. Every output is decision support: it surfaces evidence gaps,
contradictions and risk signals; it never asserts that someone is a fraud and never
authorises a payment without a human.
"""
import os

__version__ = "1.0.0"

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("MUSA_DATA_DIR", os.path.join(os.path.dirname(PACKAGE_DIR), "data"))
