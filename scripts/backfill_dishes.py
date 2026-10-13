"""Sends every active dish of core.dishes to RECO-01 (POST /dishes/upsert) once.

Use it after seeding the backend database and before the outbox worker exists: the worker sends
later dish changes. Running it again is harmless: unchanged dishes answer "unchanged".

The reco service itself never reads schema core; only this script does, with the backend role:

    python scripts/backfill_dishes.py \\
        --core-database-url postgresql://angi_backend:backend_dev@localhost:5432/angi \\
        --reco-url http://localhost:8000

RECO_API_KEY is read like the service reads it (environment, then .env).
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import get_settings

_QUERY = """
    SELECT id, name, description, dish_form, restaurant_id, updated_at
    FROM core.dishes
    WHERE status = 'active'
    ORDER BY id
"""


def to_payload(row: dict[str, Any]) -> dict[str, Any]:
    """One core.dishes row -> the RECO-01 body; occurred_at is the row's last change."""
    updated_at: datetime = row["updated_at"]
    return {
        "dish_id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "dish_form": row["dish_form"],
        "occurred_at": updated_at.isoformat(),
        "restaurant_id": row["restaurant_id"],
    }


def _post(reco_url: str, api_key: str, payload: dict[str, Any]) -> str:
    request = urllib.request.Request(
        f"{reco_url.rstrip('/')}/dishes/upsert",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["result"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core-database-url", required=True, help="angi_backend connection URL")
    parser.add_argument("--reco-url", default="http://localhost:8000")
    args = parser.parse_args()
    api_key = get_settings().reco_api_key.get_secret_value()

    with psycopg.connect(args.core_database_url, row_factory=dict_row) as connection:
        rows = connection.execute(_QUERY).fetchall()

    results: Counter[str] = Counter()
    for row in rows:
        try:
            results[_post(args.reco_url, api_key, to_payload(row))] += 1
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            results["error"] += 1
            print(f"dish {row['id']}: {exc}", file=sys.stderr)

    print(f"{len(rows)} active dishes: {dict(results)}")
    return 1 if results["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
