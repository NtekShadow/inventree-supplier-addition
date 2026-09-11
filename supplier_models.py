from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SupplierProduct:
    sku: str
    name: str
    description: str
    price: dict[int, tuple[float, str]]
    link: str = ''
    image_url: str = ''
    brand: str = ''
    parameters: dict[str, str] = field(default_factory=dict)


class SupplierProvider(Protocol):
    slug: str
    name: str

    def search(self, term: str) -> list[SupplierProduct]:
        ...

    def get_product(self, sku: str) -> SupplierProduct:
        ...