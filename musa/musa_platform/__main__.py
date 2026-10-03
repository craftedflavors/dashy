"""python -m musa_platform serve | scout | seed | retention"""
import argparse
import json

from . import compliance, scout, web


def main(argv=None):
    p = argparse.ArgumentParser(prog="musa_platform", description="MUSA Corridor platform")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the web platform, WhatsApp bot and background agents")
    s.add_argument("--port", type=int)
    sub.add_parser("scout", help="run Scout once over enabled sources")
    sub.add_parser("seed", help="load research signals into the opportunity board")
    sub.add_parser("retention", help="apply the data-retention policy now")
    a = p.parse_args(argv)
    if a.cmd == "serve":
        web.serve(a.port)
    elif a.cmd == "scout":
        print(json.dumps(scout.run_all(), indent=2))
    elif a.cmd == "seed":
        print("added", scout.seed())
    else:
        print(json.dumps(compliance.run_retention(), indent=2))


if __name__ == "__main__":
    main()
