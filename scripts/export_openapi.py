"""Export the FastAPI OpenAPI document without touching a database or provider."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def export_openapi(output: Path) -> None:
    repository = _repository_root()
    api_src = repository / "apps" / "api" / "src"
    sys.path.insert(0, str(api_src))
    from memoryos.main import app

    output.parent.mkdir(parents=True, exist_ok=True)
    document = app.openapi()
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("contracts/openapi.json"),
        help="Path for the generated OpenAPI JSON document.",
    )
    args = parser.parse_args()
    export_openapi(args.output)


if __name__ == "__main__":
    main()
