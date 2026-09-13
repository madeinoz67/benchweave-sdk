"""Bundle canonical contracts and the pure validator in self-contained SDK builds."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

CONTRACT_SETS = ("otdp-v0.3.0", "registry-v1.0.0", "plugin-ui-v0.1.0")


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        package = root / "src/benchweave_sdk"
        contracts = package / "contracts"
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
