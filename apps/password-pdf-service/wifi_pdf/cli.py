from __future__ import annotations

import argparse
import json

from .config import load_settings
from .logging_utils import configure_logging
from .pipeline import WifiPdfPipeline
from .utils import load_json_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate tenant WiFi PDFs from JSON.")
    parser.add_argument("--input", required=True, help="Path to the input JSON file.")
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to the WiFi PDF config file. Defaults to config/wifi_pdf/brand_settings.json.",
    )
    parser.add_argument("--log-level", default="INFO", help="Python logging level.")
    parser.add_argument(
        "--template-name",
        choices=[
            "Opticable Template Basic 01",
            "Corteck Template Basic 01",
            "Opticable_Basic01",
            "Cotreck_Basic01",
            "Opticable",
            "Corteck",
            "Opticable_Template_01",
        ],
        default=None,
        help="Override the template name from the input payload.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the full batch result as JSON instead of a short summary.",
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    logger = configure_logging(settings.output.root_dir / "logs", args.log_level)
    pipeline = WifiPdfPipeline(settings, logger)

    payload = load_json_file(args.input)
    if args.template_name:
        if isinstance(payload, list):
            payload = {"building_name": "wifi-batch", "template_name": args.template_name, "records": payload}
        else:
            payload["template_name"] = args.template_name
    result = pipeline.process_payload(payload)

    if args.print_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.merged_pdf_path)


if __name__ == "__main__":
    main()
