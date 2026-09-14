"""Bundle canonical contracts, preview assets and the pure validator."""

import hashlib
import json
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

CONTRACT_SETS = ("otdp-v0.3.0", "registry-v1.0.0", "plugin-ui-v0.1.0", "plugin-ui-preview-v1")


def _validate_preview_assets(package: Path) -> None:
    root = package / "preview_assets"
    inventory_path = root / "inventory.json"
    if not inventory_path.is_file():
        raise RuntimeError("Bundled preview inventory missing; run npm run build:preview from ui/")
    try:
        inventory = json.loads(inventory_path.read_bytes())
        assets = inventory["assets"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Bundled preview inventory is invalid") from exc
    if inventory.get("api_version") != 1 or not isinstance(assets, list) or not assets:
        raise RuntimeError("Bundled preview inventory is incompatible or empty")
    for asset in assets:
        relative = Path(asset["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe preview asset path: {relative}")
        content = (root / relative).read_bytes()
        if len(content) != asset["size"] or hashlib.sha256(content).hexdigest() != asset["sha256"]:
            raise RuntimeError(f"Bundled preview asset is stale or corrupt: {relative}")


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        package = root / "src/benchweave_sdk"
        contracts = package / "contracts"
        _validate_preview_assets(package)
        if contracts.is_dir():
            # An SDK sdist already contains the canonical build inputs.
            for name in CONTRACT_SETS:
                if not (contracts / name).is_dir():
                    raise RuntimeError(f"Required contract set missing: {name}")
            if not (package / "_presentation_contract.py").is_file():
                raise RuntimeError("Bundled presentation validator missing")
            return
        checkout = root.parent.parent
        contracts = checkout / "contracts"
        validator = checkout / "src/benchweave/presentation/contracts.py"
        if not contracts.is_dir() or not validator.is_file():
            raise RuntimeError("Canonical sources unavailable; build from checkout or SDK sdist")
        prefix = "benchweave_sdk" if self.target_name == "wheel" else "src/benchweave_sdk"
        for name in CONTRACT_SETS:
            source = contracts / name
            if not source.is_dir():
                raise RuntimeError(f"Required contract set missing: {name}")
            build_data["force_include"][str(source)] = f"{prefix}/contracts/{name}"
        build_data["force_include"][str(validator)] = f"{prefix}/_presentation_contract.py"
