"""Supplier Addition Plugin for InvenTree."""

try:
    from django.conf import settings
    from company.models import Company, ManufacturerPart, SupplierPart, SupplierPriceBreak
    from part.models import Part
    from plugin.base.supplier import helpers as supplier
    from plugin.base.supplier.mixins import SupplierMixin
    from plugin.mixins import SettingsMixin
    from plugin.plugin import InvenTreePlugin
except ImportError:
    # Fallback definitions when running outside a full InvenTree Django environment
    settings = None
    Company = None
    ManufacturerPart = None
    SupplierPart = None
    SupplierPriceBreak = None
    Part = None

    class _MockSupplier:
        class Supplier:
            def __init__(self, slug: str, name: str):
                self.slug = slug
                self.name = name

        class SearchResult:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class ImportParameter:
            def __init__(self, name: str, value: str):
                self.name = name
                self.value = value

        class PartNotFoundError(Exception):
            pass

    supplier = _MockSupplier()  # type: ignore

    class InvenTreePlugin:  # type: ignore
        pass

    class SupplierMixin:  # type: ignore
        pass

    class SettingsMixin:  # type: ignore
        pass

from . import PLUGIN_VERSION
from .models import SupplierProduct, SupplierProvider
from .suppliers import LandefeldProvider


class SupplierAdditionPlugin(SupplierMixin, SettingsMixin, InvenTreePlugin):
    """Modular supplier addition and integration plugin for InvenTree."""

    # Plugin metadata
    TITLE = "Supplier Addition"
    NAME = "Supplier Addition"
    SLUG = "supplier-addition"
    DESCRIPTION = "Modular supplier addition and integration plugin for InvenTree"
    VERSION = PLUGIN_VERSION

    # Additional project information
    AUTHOR = "NtekShadow"
    WEBSITE = "https://github.com/NtekShadow/inventree-supplier-addition"
    LICENSE = "MIT"

    SETTINGS = {
        "DOWNLOAD_IMAGES": {
            "name": "Download part images",
            "description": "Enable downloading of part images during import",
            "validator": bool,
            "default": False,
        }
    }

    def __init__(self):
        super().__init__()
        self.providers: dict[str, SupplierProvider] = {
            "landefeld": LandefeldProvider(),
        }

    def register_provider(self, provider: SupplierProvider) -> None:
        """Register a new supplier provider."""
        self.providers[provider.slug] = provider

    def _get_provider(self, supplier_slug: str) -> SupplierProvider:
        try:
            return self.providers[supplier_slug]
        except KeyError as error:
            raise ValueError(f"Unknown supplier: {supplier_slug}") from error

    def get_suppliers(self) -> list[supplier.Supplier]:
        """Return a list of available suppliers."""
        return [
            supplier.Supplier(slug=provider.slug, name=provider.name)
            for provider in self.providers.values()
        ]

    def get_search_results(self, supplier_slug: str, term: str) -> list[supplier.SearchResult]:
        """Search products across the specified supplier."""
        provider = self._get_provider(supplier_slug)
        results = []
        for product in provider.search(term):
            existing_part = None
            if SupplierPart is not None:
                part_match = SupplierPart.objects.filter(SKU=product.sku).first()
                existing_part = getattr(part_match, "part", None)

            results.append(
                supplier.SearchResult(
                    sku=product.sku,
                    name=product.name,
                    description=product.description,
                    exact=product.sku.lower() == term.lower(),
                    price=self._format_price(product),
                    link=product.link,
                    image_url=product.image_url,
                    existing_part=existing_part,
                )
            )
        return results

    @staticmethod
    def _format_price(product: SupplierProduct) -> str:
        """Format product pricing for display."""
        if isinstance(product.price, dict) and 1 in product.price:
            price = product.price[1][0]
            if price > 0:
                currency = product.price[1][1] or "EUR"
                return f"{price:.2f} {currency}"
        return "Preis auf Anfrage"

    def get_import_data(self, supplier_slug: str, part_id: str):
        """Fetch product data for part import."""
        try:
            return self._get_provider(supplier_slug).get_product(part_id)
        except LookupError as error:
            raise supplier.PartNotFoundError() from error

    def get_pricing_data(self, data: SupplierProduct) -> dict[int, tuple[float, str]]:
        """Extract pricing breaks from product data."""
        return data.price

    def get_parameters(self, data: SupplierProduct) -> list[supplier.ImportParameter]:
        """Extract import parameters from product data."""
        return [
            supplier.ImportParameter(name=name, value=value)
            for name, value in data.parameters.items()
            if value
        ]

    def import_part(self, data: SupplierProduct, **kwargs):
        """Import or update part model in InvenTree."""
        part, created = Part.objects.get_or_create(
            name__iexact=data.sku,
            purchaseable=True,
            defaults={
                "name": data.sku,
                "description": data.description,
                "link": data.link,
                **kwargs,
            },
        )
        if (
            created
            and data.image_url
            and settings
            and not getattr(settings, "TESTING", False)
            and getattr(self, "get_setting", lambda _: False)("DOWNLOAD_IMAGES")
        ):
            image_file, image_format = self.download_image(data.image_url)
            if image_file:
                part.image.save(f"part_{part.pk}_image.{image_format.lower()}", image_file)
        return part

    def import_manufacturer_part(self, data: SupplierProduct, **kwargs):
        """Import or update manufacturer part model in InvenTree."""
        manufacturer, _ = Company.objects.get_or_create(
            name__iexact=data.brand,
            defaults={
                "is_manufacturer": True,
                "is_supplier": False,
                "name": data.brand,
            },
        )
        manufacturer_part, _ = ManufacturerPart.objects.get_or_create(
            MPN=data.sku, manufacturer=manufacturer, **kwargs
        )
        return manufacturer_part

    def import_supplier_part(self, data: SupplierProduct, **kwargs):
        """Import or update supplier part and pricing breaks in InvenTree."""
        supplier_part, _ = SupplierPart.objects.get_or_create(
            SKU=data.sku,
            supplier=self.supplier_company,
            **kwargs,
            defaults={"link": data.link},
        )
        SupplierPriceBreak.objects.filter(part=supplier_part).delete()
        SupplierPriceBreak.objects.bulk_create([
            SupplierPriceBreak(
                part=supplier_part,
                quantity=quantity,
                price=price,
                price_currency=currency,
            )
            for quantity, (price, currency) in data.price.items()
        ])
        return supplier_part


# Compatibility aliases
SupplierAddition = SupplierAdditionPlugin
SupplierIntegrationPlugin = SupplierAdditionPlugin
