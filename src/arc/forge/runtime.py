from __future__ import annotations

import json
import logging
import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path

from arc.forge.types import SERVICE_REGISTRY
from arc.foundation.constants import SERVICE_RUNTIME_DIR

logger = logging.getLogger(__name__)


class VirtualEnvError(RuntimeError):
    pass


class VirtualEnvManager:
    def __init__(
        self,
        venv_dir: str | Path = SERVICE_RUNTIME_DIR,
    ) -> None:
        self.venv_dir = Path(venv_dir).expanduser().resolve()

    @property
    def python(self) -> Path:
        return self.venv_dir / "bin" / "python"

    def _require_uv(self) -> None:
        if shutil.which("uv") is None:
            raise VirtualEnvError("uv is not installed or not available in PATH")

    def _require_runtime(self) -> None:
        if not self.python.is_file():
            raise VirtualEnvError(f"Invalid ARC runtime: {self.venv_dir}")

    def _run(
        self,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                check=True,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            raise VirtualEnvError(f"Executable not found: {args[0]}") from exc
        except subprocess.CalledProcessError as exc:
            raise VirtualEnvError(
                f"Command failed ({exc.returncode}): "
                f"{' '.join(args)}\n"
                f"{exc.stderr.strip()}"
            ) from exc

    def create(self) -> None:
        if self.python.is_file():
            return

        self._require_uv()

        self.venv_dir.parent.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        if self.venv_dir.exists() and not self.venv_dir.is_dir():
            raise VirtualEnvError(f"Runtime path is not a directory: {self.venv_dir}")

        logger.warning(
            "Creating new venv in: %s",
            self.venv_dir,
        )

        self._run(
            [
                "uv",
                "venv",
                str(self.venv_dir),
            ]
        )

        self._require_runtime()

    def is_installed(self, package: str) -> bool:
        """Return whether a package is installed in the runtime venv."""
        self._require_runtime()

        result = subprocess.run(
            [
                str(self.python),
                "-c",
                (
                    "from importlib.metadata import version, "
                    "PackageNotFoundError; "
                    f"\ntry: print(version({package!r}))\n"
                    "except PackageNotFoundError: raise SystemExit(1)"
                ),
            ],
            text=True,
            capture_output=True,
        )

        return result.returncode == 0

    def installed_version(self, package: str) -> str | None:
        """Return the installed package version, or None."""
        self._require_runtime()

        result = subprocess.run(
            [
                str(self.python),
                "-c",
                (
                    "from importlib.metadata import version, "
                    "PackageNotFoundError; "
                    f"\ntry: print(version({package!r}))\n"
                    "except PackageNotFoundError: raise SystemExit(1)"
                ),
            ],
            text=True,
            capture_output=True,
        )

        if result.returncode != 0:
            return None

        return result.stdout.strip()

    def list_installed(self) -> dict[str, str]:
        """Return installed packages as {name: version}."""
        self._require_runtime()

        result = self._run(
            [
                "uv",
                "pip",
                "list",
                "--python",
                str(self.python),
                "--format",
                "json",
            ]
        )

        packages = json.loads(result.stdout)

        return {package["name"]: package["version"] for package in packages}

    def is_up_to_date(
        self,
        package: str,
        required_version: str | None = None,
    ) -> bool:
        """
        Return whether the installed version satisfies the requested version.

        When required_version is None, only checks whether the package exists.
        """
        installed = self.installed_version(package)

        if installed is None:
            return False

        if required_version is None:
            return True

        from packaging.specifiers import SpecifierSet
        from packaging.version import Version

        return Version(installed) in SpecifierSet(required_version)

    def install_git(
        self,
        url: str,
        *,
        ref: str | None = None,
        editable: bool = False,
    ) -> None:
        self.create()

        source = f"git+{url}"

        if ref:
            source = f"{source}@{ref}"

        args = [
            "uv",
            "pip",
            "install",
            "--python",
            str(self.python),
        ]

        if editable:
            args.append("--editable")

        args.append(source)

        self._run(args)

    def install(
        self,
        package: str,
        *,
        editable: bool = False,
    ) -> None:
        self.create()

        args = [
            "uv",
            "pip",
            "install",
            "--python",
            str(self.python),
        ]

        if editable:
            args.append("--editable")

        args.append(package)

        self._run(args)

    def update(self, package: str) -> None:
        self._require_uv()
        self._require_runtime()

        self._run(
            [
                "uv",
                "pip",
                "install",
                "--upgrade",
                "--python",
                str(self.python),
                package,
            ]
        )

    def remove(self, package: str) -> None:
        self._require_uv()
        self._require_runtime()

        self._run(
            [
                "uv",
                "pip",
                "uninstall",
                "--python",
                str(self.python),
                package,
            ]
        )


SERVICE_RUNNER_PACKAGE = "arc-v2-service-runner"


class RuntimeBootstrap:
    def __init__(
        self,
        runtime: VirtualEnvManager,
    ) -> None:
        self.runtime = runtime

    def ensure(self) -> None:
        self.runtime.create()

        framework_version = version(SERVICE_RUNNER_PACKAGE)

        source = SERVICE_REGISTRY.get(SERVICE_RUNNER_PACKAGE)

        if source is None:
            raise RuntimeError(f"No source registered for {SERVICE_RUNNER_PACKAGE!r}")

        if self.runtime.is_up_to_date(
            SERVICE_RUNNER_PACKAGE,
            f"=={framework_version}",
        ):
            return

        self.runtime.install_git(
            source,
            ref=f"v{framework_version}",
        )
