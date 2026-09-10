from __future__ import annotations

import tempfile
import tomllib
from pathlib import Path

import tomli_w

from arc.foundation.constants import SERVICE_LOCK


class LockFile:
    def __init__(
        self,
        path: str | Path = SERVICE_LOCK,
    ) -> None:
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return {
                "version": 1,
                "revision": 0,
                "package": [],
            }

        with self.path.open("rb") as file:
            return tomllib.load(file)

    def upsert(
        self,
        package,
    ) -> None:
        data = self.load()

        packages = data.setdefault(
            "package",
            [],
        )

        packages[:] = [item for item in packages if item["name"] != package["name"]]

        packages.append(package)

        data["revision"] = int(data.get("revision", 0)) + 1

        self._write(data)

    def remove(
        self,
        package_name: str,
    ) -> None:
        data = self.load()

        data["package"] = [
            item for item in data.get("package", []) if item["name"] != package_name
        ]

        data["revision"] = int(data.get("revision", 0)) + 1

        self._write(data)

    def _write(
        self,
        data,
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        ) as file:
            temporary = Path(file.name)

            file.write(tomli_w.dumps(data).encode("utf-8"))

        temporary.replace(self.path)
