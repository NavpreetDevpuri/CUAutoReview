#!/usr/bin/env python3
"""Seed local demo accounts and bundled datasets without provider calls."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from seed_demo import GUIDE, MANIFEST, seed
from seed_distinct_demo import seed_datasets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("CUAUTOREVIEW_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--public-url", default=os.environ.get("CUAUTOREVIEW_PUBLIC_URL"))
    parser.add_argument("--admin-credentials", type=Path)
    parser.add_argument("--archive-fixtures", action="store_true", help="Explicitly soft-archive named old fixtures after import; default preserves their visibility.")
    parser.add_argument("--show-logins", action="store_true", help="Print existing generated demo logins only; does not contact the API or seed anything.")
    args = parser.parse_args()
    if args.show_logins:
        if not MANIFEST.is_file() or not GUIDE.is_file():
            parser.exit(1, "Demo login files are missing. Run the seed service first; no accounts were created by this command.\n")
        print(GUIDE.read_text(), end="")
        return
    try:
        seed(args.base_url, args.admin_credentials, args.public_url)
        seed_datasets(args.base_url, archive_old_fixtures=args.archive_fixtures)
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Workspace seed stopped: {exc}\n")
    print("Demo ready. View generated logins with: docker compose -f platform/compose.yaml run --rm --no-deps seed --show-logins")


if __name__ == "__main__":
    main()
