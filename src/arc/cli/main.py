from __future__ import annotations

import cyclopts

from arc.boot.boot import main as boot
from arc.forge.forge import Forge

app = cyclopts.App()


@app.default
async def start(
    *,
    autofix: bool = False,
) -> None:
    await boot(autofix=autofix)


@app.command
async def install(
    source: str,
    *,
    editable: bool = False,
) -> None:
    forge = Forge.from_env()

    spec = forge.install(
        source,
        editable=editable,
    )

    print(f"Installed '{spec.id}' ({spec.version})")


@app.command
async def remove(
    service_id: str,
) -> None:
    forge = Forge.from_env()

    forge.remove(service_id)

    print(f"Removed '{service_id}'")


@app.command
def list() -> None:
    forge = Forge.from_env()

    for spec in forge.list_installed():
        print(f"{spec.id:<20} {spec.version}")


@app.command
def info(
    service_id: str,
) -> None:
    forge = Forge.from_env()

    spec = forge.info(service_id)

    print(f"ID:          {spec.id}")
    print(f"Name:        {spec.name}")
    print(f"Version:     {spec.version}")
    print(f"Package:     {spec.package}")
    print(f"Module:      {spec.module}")
    print(f"Description: {spec.description}")
    print(f"Restart:     {spec.restart}")
    print(f"Health:      {spec.health}")
    print(f"Depends:     {', '.join(spec.depends) or 'none'}")


if __name__ == "__main__":
    app()
