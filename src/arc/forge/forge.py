from __future__ import annotations

import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any
from venv import logger

import yaml

from arc.forge.lock_manager import LockFile
from arc.forge.runtime import RuntimeBootstrap, VirtualEnvManager
from arc.forge.types import SERVICE_REGISTRY, ResolvedSource, ServiceSpec
from arc.foundation.constants import (
    ARC_SERVICE_RUNTIME_CONFIG,
    ARC_SERVICE_RUNTIME_DIR,
    ARC_SERVICE_RUNTIME_LOCK,
)


class ForgeError(RuntimeError):
    """Base exception for Forge errors."""


class Forge:
    def __init__(
        self,
        runtime: VirtualEnvManager,
        lock: LockFile,
        services_config: Path,
    ) -> None:
        self.runtime: VirtualEnvManager = runtime
        self.lock: LockFile = lock
        self.services_config: Path = services_config

        self.bootstrap: RuntimeBootstrap = RuntimeBootstrap(runtime)

    @classmethod
    def from_env(cls):
        _runtime = VirtualEnvManager(ARC_SERVICE_RUNTIME_DIR)
        _lock = LockFile(ARC_SERVICE_RUNTIME_LOCK)
        return cls(_runtime, _lock, ARC_SERVICE_RUNTIME_CONFIG)

    # -------------------------------------------------------------------------
    # Source handling
    # -------------------------------------------------------------------------

    @staticmethod
    def _resolve_source(source: str | Path) -> ResolvedSource:
        value = str(source)
        path = Path(value).expanduser()

        if path.exists():
            if not path.is_dir():
                raise ForgeError(f"Local source exists but is not a directory: {path}")

            return ResolvedSource(
                kind="local",
                location=str(path.resolve()),
                path=path.resolve(),
            )

        if value.startswith(("https://", "http://", "git@")):
            return ResolvedSource(
                kind="git",
                location=value,
            )

        return ResolvedSource(
            kind="registry",
            location=value,
        )

    @staticmethod
    def _checkout_git(url: str) -> Path:
        if shutil.which("git") is None:
            raise ForgeError(
                "Git is required to install Git sources but was not found."
            )

        tmp = Path(
            tempfile.mkdtemp(
                prefix="arc-forge-",
            )
        )

        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--",
                    url,
                    str(tmp),
                ],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise ForgeError(f"Failed to clone repository: {url}") from exc
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

        return tmp

    def _resolve_project(
        self,
        source: ResolvedSource,
    ) -> ResolvedSource:
        if source.kind == "local":
            assert source.path is not None
            return source

        if source.kind == "registry":
            url = SERVICE_REGISTRY.get(source.location)

            if url is None:
                raise ForgeError(f"Service '{source.location}' is not registered.")

            source = source.model_copy(
                update={
                    "kind": "git",
                    "location": url,
                }
            )

        if source.kind == "git":
            source.path = self._checkout_git(source.location)
            return source

        raise ForgeError(f"Unsupported source type: {source.kind}")

    # -------------------------------------------------------------------------
    # Metadata
    # -------------------------------------------------------------------------

    @staticmethod
    def _read_service_spec(
        project_dir: Path,
    ) -> ServiceSpec:
        pyproject = project_dir / "pyproject.toml"

        if not pyproject.is_file():
            raise ForgeError(f"Missing pyproject.toml: {pyproject}")

        try:
            with pyproject.open("rb") as file:
                data = tomllib.load(file)
        except tomllib.TOMLDecodeError as exc:
            raise ForgeError(f"Invalid pyproject.toml: {pyproject}") from exc
        except OSError as exc:
            raise ForgeError(f"Could not read {pyproject}: {exc}") from exc

        project = data.get("project")

        if not isinstance(project, dict):
            raise ForgeError(f"Missing [project] section in {pyproject}")

        arc = data.get("tool", {}).get("arc", {}).get("service")

        if not isinstance(arc, dict):
            raise ForgeError(f"Missing [tool.arc.service] in {pyproject}")

        try:
            return ServiceSpec(
                id=arc["id"],
                name=arc.get(
                    "name",
                    project["name"],
                ),
                version=project["version"],
                package=project["name"],
                description=arc.get(
                    "description",
                    project.get("description", ""),
                ),
                module=arc["module"],
                restart=arc.get(
                    "restart",
                    "never",
                ),
                health=arc.get(
                    "health",
                    "ignore",
                ),
                depends=arc.get(
                    "depends",
                    [],
                ),
            )
        except KeyError as exc:
            raise ForgeError(
                f"Missing required service metadata field: {exc.args[0]}"
            ) from exc

    def _resolve_spec(
        self,
        source: ResolvedSource,
    ) -> tuple[ResolvedSource, ServiceSpec]:
        resolved = self._resolve_project(source)

        if resolved.path is None:
            raise ForgeError("Source could not be resolved to a project directory.")

        spec = self._read_service_spec(resolved.path)

        self._validate_spec(spec)

        return resolved, spec

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    @staticmethod
    def _validate_spec(
        spec: ServiceSpec,
    ) -> None:
        if not spec.id.strip():
            raise ForgeError("Service ID cannot be empty.")

        if spec.id in spec.depends:
            raise ForgeError(f"Service '{spec.id}' cannot depend on itself.")

        if len(set(spec.depends)) != len(spec.depends):
            raise ForgeError(f"Service '{spec.id}' contains duplicate dependencies.")

        if spec.restart not in {
            "always",
            "on-failure",
            "never",
        }:
            raise ForgeError(f"Invalid restart policy for '{spec.id}': {spec.restart}")

        if spec.health not in {
            "ignore",
            "restart",
            "stop",
        }:
            raise ForgeError(f"Invalid health policy for '{spec.id}': {spec.health}")

    # -------------------------------------------------------------------------
    # Installation target
    # -------------------------------------------------------------------------

    @staticmethod
    def _install_target(
        source: ResolvedSource,
    ) -> str:
        if source.path is None:
            raise ForgeError("No local project path available for installation.")

        return str(source.path)

    # -------------------------------------------------------------------------
    # Service configuration
    # -------------------------------------------------------------------------

    def _load_services_config(self) -> dict[str, dict[Any, Any]] | dict[Any, Any]:
        if not self.services_config.exists():
            logger.warning(
                f"Expected 'services.arc.yaml' file at: {self.services_config}, but it doese not exist"
            )
            return {"services": {}}

        try:
            with self.services_config.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            raise ForgeError(
                f"Invalid services configuration: {self.services_config}"
            ) from exc
        except OSError as exc:
            raise ForgeError(f"Could not read services configuration: {exc}") from exc

        # File empty
        if data is None:
            return {"services": {}}

        _is_dict_instance = isinstance(data, dict)

        if data.get("services") is None and "services" in data:
            return {"services": {}}

        if not _is_dict_instance:
            raise ForgeError("services.arc.yaml must contain a mapping.")

        if "services" not in data:
            data["services"] = {}

        if not isinstance(data["services"], dict):
            raise ForgeError("'services' must be a mapping.")

        return data

    def _register_service(
        self,
        spec: ServiceSpec,
    ) -> None:
        data = self._load_services_config()

        services = data["services"]

        existing = services.get(spec.id)

        if existing is not None:
            raise ForgeError(f"Service '{spec.id}' is already registered.")

        services[spec.id] = {
            "module": spec.module,
            "restart": spec.restart,
            "health": spec.health,
            "depends": spec.depends,
        }

        self.services_config.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = self.services_config.with_suffix(".yaml.tmp")

        try:
            with temporary.open(
                "w",
                encoding="utf-8",
            ) as file:
                yaml.safe_dump(
                    data,
                    file,
                    sort_keys=False,
                )

            temporary.replace(self.services_config)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ForgeError(f"Could not write service configuration: {exc}") from exc

    def _remove_service_config(
        self,
        service_id: str,
    ) -> None:
        data = self._load_services_config()
        services = data["services"]

        if service_id not in services:
            return

        del services[service_id]

        self.services_config.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = self.services_config.with_suffix(".yaml.tmp")

        try:
            with temporary.open(
                "w",
                encoding="utf-8",
            ) as file:
                yaml.safe_dump(
                    data,
                    file,
                    sort_keys=False,
                )

            temporary.replace(self.services_config)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise ForgeError(f"Could not update service configuration: {exc}") from exc

    # -------------------------------------------------------------------------
    # Lock
    # -------------------------------------------------------------------------

    @staticmethod
    def _lock_record(
        spec: ServiceSpec,
        source: ResolvedSource,
        *,
        editable: bool,
    ) -> dict:
        if source.kind == "local":
            source_data = {
                "type": "path",
                "path": source.location,
                "editable": editable,
            }
        else:
            source_data = {
                "type": source.kind,
                "url": source.location,
            }

        return {
            "name": spec.package,
            "version": spec.version,
            "source": source_data,
            "service": {
                "id": spec.id,
                "module": spec.module,
                "restart": spec.restart,
                "health": spec.health,
                "depends": spec.depends,
            },
        }

    def _find_locked_service(
        self,
        service_id: str,
    ) -> dict | None:
        data = self.lock.load()

        for package in data.get("package", []):
            service = package.get("service")

            if isinstance(service, dict) and service.get("id") == service_id:
                return package

        return None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def install(
        self,
        source: str | Path,
        *,
        editable: bool = False,
    ) -> ServiceSpec:
        self.bootstrap.ensure()

        resolved_source = self._resolve_source(source)

        resolved_source, spec = self._resolve_spec(resolved_source)

        install_target = self._install_target(resolved_source)

        if resolved_source.kind == "git" or resolved_source.kind == "registry":
            self.runtime.install_git(install_target, editable=editable)

        else:
            self.runtime.install(
                install_target,
                editable=editable,
            )

        try:
            self._register_service(spec)

            self.lock.upsert(
                self._lock_record(
                    spec,
                    resolved_source,
                    editable=editable,
                )
            )
        except Exception:
            # The package is already installed at this point.
            # Do not silently pretend installation failed completely.
            raise

        return spec

    def remove(
        self,
        service_id: str,
    ) -> None:
        record = self._find_locked_service(service_id)

        if record is None:
            raise KeyError(f"Unknown ARC service: {service_id}")

        package_name = record.get("name")

        if not package_name:
            raise ForgeError(f"Invalid lock record for service '{service_id}'.")

        self.runtime.remove(package_name)

        self._remove_service_config(service_id)

        self.lock.remove(package_name)
