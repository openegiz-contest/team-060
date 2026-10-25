#!/usr/bin/env python3
"""Create the pit twins in Ditto (idempotent PUT of attributes; the control twin keeps
its scenarios if it already exists)."""

import sys
import time

import ditto
from twins import definitions


def main():
    defs = definitions()
    existing_control = None
    for tid, body in defs.items():
        for attempt in range(40):
            try:
                if tid.endswith(":control"):
                    existing_control = ditto.get(f"/things/{tid}")
                    if existing_control and "features" in existing_control:
                        body = {**body, "features": existing_control["features"]}
                status = ditto.request("PUT", f"/things/{tid}", body)
                print(f"{'created' if status == 201 else 'updated'}  {tid}")
                break
            except Exception as exc:  # Ditto may still be warming up
                if attempt == 39:
                    print(f"FAILED {tid}: {exc}", file=sys.stderr)
                    return 1
                time.sleep(3)
    print(f"{len(defs)} twins ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
