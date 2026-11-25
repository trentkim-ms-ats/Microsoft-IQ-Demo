"""Run the independent live Track 3 and Track 4 commands in order using the existing demo login."""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from tools import azure_demo_auth as auth


def bind_selected_login():
    home = Path.home()
    cache = Path(os.environ.get("AZURE_CONFIG_DIR") or home / ".azure-iq-demo").expanduser().resolve()
    if cache == (home / ".azure").resolve() or not cache.is_dir():
        raise auth.AzureContextError("Use the existing dedicated Azure demo login cache, not the default Azure CLI profile.")

    os.environ["AZURE_CONFIG_DIR"] = str(cache)
    current = auth.cli_json("account", "show")
    try:
        selected = {
            "IQ_AZURE_TENANT_ID": str(UUID(current["tenantId"])),
            "IQ_AZURE_ACCOUNT": current["user"]["name"].strip().casefold(),
            "AZURE_OPENAI_SUBSCRIPTION": str(UUID(current["id"])),
        }
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise auth.AzureContextError("Azure CLI did not return a selected demo account and subscription.") from error
    if not selected["IQ_AZURE_ACCOUNT"]:
        raise auth.AzureContextError("The selected Azure CLI profile has no demo account.")
    for name, value in selected.items():
        configured = os.environ.get(name, "").strip()
        if configured and configured.casefold() != value:
            raise auth.AzureContextError(f"{name} does not match the selected demo login. No fallback will be used.")
    os.environ.update(selected)
    auth.require_separate_identity()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--track3-provisioned-config",
        type=Path,
        help="Use this provisioned Track 3 target without changing Track 4's target.",
    )
    args = parser.parse_args()
    try:
        bind_selected_login()
    except (auth.AzureContextError, OSError) as error:
        print(f"Track 3 and Track 4 setup blocked: {error}", file=sys.stderr)
        return 1

    track3 = ["tools.run_track3_daily_briefing", "--profile", "all"]
    if args.track3_provisioned_config:
        track3.extend(("--provisioned-config", str(args.track3_provisioned_config)))
    commands = (
        ("Track 3", track3),
        ("Track 4", ("tools.run_track4_demo",)),
    )
    failed = False
    for label, command in commands:
        print(f"Starting {label} with the selected Azure CLI login.", file=sys.stderr, flush=True)
        result = subprocess.run([sys.executable, "-m", *command], check=False)
        if result.returncode:
            print(f"{label} did not pass (exit {result.returncode}).", file=sys.stderr, flush=True)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
