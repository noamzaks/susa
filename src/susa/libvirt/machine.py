import libvirt as lv

from susa.libvirt.entity import Entity


class Machine(Entity[lv.virDomain]):
    def create(self) -> None:
        self.value = self.conn.createXML(self.xml)

    def destroy(self) -> None:
        assert self.value is not None
        self.value.destroy()
