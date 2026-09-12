"""Include canonical contracts in both sdist and wheel, without source copies."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        contracts = root / "src/benchweave_sdk/contracts"
        if contracts.is_dir():
            # An SDK sdist already places resources inside the package.
            for name in ("otdp-v0.3.0", "registry-v1.0.0"):
                if not (contracts / name).is_dir():
                    raise RuntimeError(f"Required contract set missing: {name}")
            return
        contracts = root.parent.parent / "contracts"
        if not contracts.is_dir():
            raise RuntimeError("Canonical contracts unavailable; build from checkout or SDK sdist")
        prefix = (
            "benchweave_sdk/contracts"
            if self.target_name == "wheel"
            else "src/benchweave_sdk/contracts"
        )
        for name in ("otdp-v0.3.0", "registry-v1.0.0"):
            source = contracts / name
            if not source.is_dir():
                raise RuntimeError(f"Required contract set missing: {name}")
            build_data["force_include"][str(source)] = f"{prefix}/{name}"
