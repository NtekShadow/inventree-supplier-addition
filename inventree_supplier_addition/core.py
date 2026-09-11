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

        class PartImportError(Exception):
            pass

    supplier = _MockSupplier()  # type: ignore

    class InvenTreePlugin:  # type: ignore
        pass

    class SupplierMixin:  # type: ignore
        pass

    class SettingsMixin:  # type: ignore
        pass

import logging

logger = logging.getLogger("inventree")

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
        "SUPPLIER": {
            "name": "Default Supplier",
            "description": "Optional default InvenTree supplier company (auto-created if not set)",
            "model": "company.company",
            "model_filters": {"is_supplier": True},
            "required": False,
        },
        "DOWNLOAD_IMAGES": {
            "name": "Download part images",
            "description": "Enable downloading of part images during import",
            "validator": bool,
            "default": False,
        },
    }

    def __init__(self):
        super().__init__()
        self._active_supplier_slug: str = ""
        self.providers: dict[str, SupplierProvider] = {
            "landefeld": LandefeldProvider(),
        }
        # Mark SUPPLIER as optional in UI because we provide automatic multi-supplier resolution
        if hasattr(self, "SETTINGS") and "SUPPLIER" in self.SETTINGS:
            self.SETTINGS["SUPPLIER"]["required"] = False

    def register_provider(self, provider: SupplierProvider) -> None:
        """Register a new supplier provider."""
        self.providers[provider.slug] = provider

    def _get_provider(self, supplier_slug: str) -> SupplierProvider:
        try:
            return self.providers[supplier_slug]
        except KeyError as error:
            raise ValueError(f"Unknown supplier: {supplier_slug}") from error

    def _get_or_create_company(
        self,
        name: str,
        is_supplier: bool = False,
        is_manufacturer: bool = False,
        website: str = "",
    ):
        """Safely get or create a Company by name in InvenTree."""
        if Company is None:
            return None

        company_obj = Company.objects.filter(name__iexact=name).first()
        if company_obj:
            updated = False
            if is_supplier and not company_obj.is_supplier:
                company_obj.is_supplier = True
                updated = True
            if is_manufacturer and not company_obj.is_manufacturer:
                company_obj.is_manufacturer = True
                updated = True
            if website and not getattr(company_obj, "website", None):
                company_obj.website = website
                updated = True
            if updated:
                company_obj.save()
            return company_obj

        return Company.objects.create(
            name=name,
            is_supplier=is_supplier,
            is_manufacturer=is_manufacturer,
            website=website,
        )

    @property
    def supplier_company(self):
        """Return the supplier company object.

        Automatically finds or creates the matching supplier company in InvenTree
        for the active provider without requiring manual configuration.
        """
        get_setting_func = getattr(self, "get_setting", None)
        if callable(get_setting_func):
            try:
                pk = get_setting_func("SUPPLIER", cache=True)
                if pk and Company is not None:
                    return Company.objects.get(pk=pk)
            except (AttributeError, KeyError, ValueError):
                pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to retrieve configured supplier company: %s", exc)

        # Dynamic fallback based on active provider or first registered provider
        supplier_slug = self._active_supplier_slug
        if not supplier_slug or supplier_slug not in self.providers:
            supplier_slug = next(iter(self.providers.keys())) if self.providers else "landefeld"

        provider = self.providers.get(supplier_slug)
        supplier_name = provider.name if provider else "Landefeld"
        website = (
            getattr(provider, "base_url", "") or getattr(provider, "website", "")
            if provider
            else "https://www.landefeld.de"
        )

        company_obj = self._get_or_create_company(
            name=supplier_name,
            is_supplier=True,
            website=website,
        )
        if company_obj is not None:
            return company_obj

        raise supplier.PartImportError("Supplier setting is missing.")

    def get_supplier_company_for_product(self, data: SupplierProduct):
        """Get or create the supplier company for a specific product dynamically."""
        # 1. If user configured a specific global supplier override in plugin settings, use it
        get_setting_func = getattr(self, "get_setting", None)
        if callable(get_setting_func):
            try:
                pk = get_setting_func("SUPPLIER", cache=True)
                if pk and Company is not None:
                    return Company.objects.get(pk=pk)
            except (AttributeError, KeyError, ValueError):
                pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to retrieve configured supplier company: %s", exc)

        # 2. Determine supplier name and slug from product or active provider
        supplier_name = getattr(data, "supplier_name", "")
        supplier_slug = getattr(data, "supplier_slug", "")

        if not supplier_slug and self._active_supplier_slug:
            supplier_slug = self._active_supplier_slug

        if supplier_slug and supplier_slug in self.providers:
            provider = self.providers[supplier_slug]
            if not supplier_name:
                supplier_name = provider.name

        # 3. Check if product brand matches a known provider
        if not supplier_name and data.brand:
            for p in self.providers.values():
                if data.brand.lower() in (p.name.lower(), p.slug.lower()):
                    supplier_name = p.name
                    supplier_slug = p.slug
                    break

        # 4. Fallback to first registered provider
        if not supplier_name:
            if self.providers:
                first_p = next(iter(self.providers.values()))
                supplier_name = first_p.name
                supplier_slug = first_p.slug
            else:
                supplier_name = "Landefeld"
                supplier_slug = "landefeld"

        # Determine website from provider if available
        website = ""
        if supplier_slug in self.providers:
            provider = self.providers[supplier_slug]
            website = getattr(provider, "base_url", "") or getattr(provider, "website", "")

        company_obj = self._get_or_create_company(
            name=supplier_name,
            is_supplier=True,
            website=website,
        )
        if company_obj is not None:
            return company_obj

        return self.supplier_company

    def get_suppliers(self) -> list[supplier.Supplier]:
        """Return a list of available suppliers."""
        return [
            supplier.Supplier(slug=provider.slug, name=provider.name)
            for provider in self.providers.values()
        ]

    def get_search_results(self, supplier_slug: str, term: str) -> list[supplier.SearchResult]:
        """Search products across the specified supplier."""
        self._active_supplier_slug = supplier_slug
        provider = self._get_provider(supplier_slug)
        results = []
        for product in provider.search(term):
            if not getattr(product, "supplier_slug", None):
                product.supplier_slug = provider.slug
            if not getattr(product, "supplier_name", None):
                product.supplier_name = provider.name

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
        self._active_supplier_slug = supplier_slug
        provider = self._get_provider(supplier_slug)
        try:
            product = provider.get_product(part_id)
        except LookupError as error:
            raise supplier.PartNotFoundError() from error

        if not getattr(product, "supplier_slug", None):
            product.supplier_slug = provider.slug
        if not getattr(product, "supplier_name", None):
            product.supplier_name = provider.name

        return product

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
        brand_name = data.brand or "Landefeld"
        manufacturer = self._get_or_create_company(
            name=brand_name,
            is_manufacturer=True,
        )
        manufacturer_part, _ = ManufacturerPart.objects.get_or_create(
            MPN=data.sku, manufacturer=manufacturer, **kwargs
        )
        return manufacturer_part

    def import_supplier_part(self, data: SupplierProduct, **kwargs):
        """Import or update supplier part and pricing breaks in InvenTree."""
        supplier_comp = self.get_supplier_company_for_product(data)
        supplier_part, _ = SupplierPart.objects.get_or_create(
            SKU=data.sku,
            supplier=supplier_comp,
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
