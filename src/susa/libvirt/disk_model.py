from pathlib import Path
from typing import Any, Self, cast

import pydantic_libvirt.domain as lvdomain

from susa.libvirt.model import Model


class DiskModel(Model[lvdomain.disk]):
    xml_model_type = lvdomain.disk

    def __init__(self, xml_model: lvdomain.disk | None = None) -> None:
        self.xml_model = xml_model or lvdomain.disk(
            type="file",
            device="disk",
            # Overridden when added to a `MachineModel`.
            target=lvdomain.disk_target(dev="sda"),
        )

    def source(self, p: str | Path, format: str = "qcow2") -> Self:
        self.xml_model.driver = lvdomain.disk_driver(
            name="qemu", type=cast(Any, format)
        )
        self.xml_model.source = lvdomain.devices_disk_source(
            file=str(Path(p).resolve())
        )

        return self
