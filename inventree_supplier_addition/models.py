"""Data models and provider protocols for supplier integrations."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SupplierProduct:
    """Represents a product retrieved from an external supplier."""

    sku: str
    name: str
    description: str
    price: dict[int, tuple[float, str]]
    link: str = ""
    image_url: str = ""
    brand: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    supplier_name: str = ""
    supplier_slug: str = ""


class SupplierProvider(Protocol):
    """Protocol defining the interface for supplier providers."""

    slug: str
    name: str

    def search(self, term: str) -> list[SupplierProduct]:
        """Search for products matching the given term."""
        ...

    def get_product(self, sku: str) -> SupplierProduct:
        """Fetch a specific product by its SKU."""
        ...
