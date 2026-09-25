from abc import abstractmethod

from susa.core.interface import Interface
from susa.core.resource import Resource


class Network(Resource):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def interfaces(self) -> list[Interface]:
        """The interfaces (of any machine) that are connected to the network."""
