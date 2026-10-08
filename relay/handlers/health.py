"""GET /health: the relay is up. Returns the stage, nothing else."""

import json
import os
from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"status": "ok", "stage": os.environ.get("STAGE", "unknown")}),
    }
