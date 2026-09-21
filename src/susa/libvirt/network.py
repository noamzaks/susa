import libvirt as lv

from susa.libvirt.entity import Entity


class Network(Entity[lv.virNetwork]):
    def create(self) -> None:
        self.value = self.conn.networkCreateXML(self.xml)

    def destroy(self) -> None:
        assert self.value is not None
        self.value.destroy()
