import argparse
import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

from app.db.database import SessionLocal
from app.jobs.update_daily import run_dca_check, update_daily_navs_and_snapshot


Job = Callable[[], dict[str, object]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run My Financing background jobs locally.")
    parser.add_argument(
        "job",
        choices=("daily-update", "dca-check"),
        help="Job to run.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        jobs: dict[str, Callable[[], dict[str, object]]] = {
            "daily-update": lambda: update_daily_navs_and_snapshot(db),
            "dca-check": lambda: run_dca_check(db),
        }
        result = jobs[args.job]()

    print(json.dumps(_json_safe(result), ensure_ascii=False, sort_keys=True))


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


if __name__ == "__main__":
    main()
