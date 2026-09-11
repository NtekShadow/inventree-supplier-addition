"""Supplier Addition Plugin for InvenTree."""

try:
    from django.conf import settings
except ImportError:
    settings = None

try:
    from company.models import Company, ManufacturerPart, SupplierPart, SupplierPriceBreak
except ImportError:
    Company = None
    ManufacturerPart = None
    SupplierPart = None
    SupplierPriceBreak = None

try:
    from part.models import Part
except ImportError:
    Part = None

try:
    from plugin.base.supplier import helpers as supplier
except ImportError:
    try:
        from plugin.mixins import supplier
    except ImportError:
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

try:
    from plugin.base.supplier.mixins import SupplierMixin
except ImportError:
    try:
        from plugin.mixins import SupplierMixin
    except ImportError:
        class SupplierMixin:  # type: ignore
            pass

try:
    from plugin.mixins import SettingsMixin
except ImportError:
    class SettingsMixin:  # type: ignore
        pass

try:
    from plugin.plugin import InvenTreePlugin
except ImportError:
    class InvenTreePlugin:  # type: ignore
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
        "DOWNLOAD_IMAGES": {
            "name": "Download part images",
            "description": "Enable downloading of part images during import",
            "validator": bool,
            "default": False,
        },
        "SUPPLIER_LANDEFELD": {
            "name": "Supplier (Landefeld)",
            "description": "InvenTree supplier company for Landefeld parts",
            "model": "company.company",
            "model_filters": {"is_supplier": True},
            "required": False,
        },
        "SUPPLIER": {
            "name": "Default Supplier (Fallback)",
            "description": "Fallback InvenTree supplier company if a supplier-specific setting is not set",
            "model": "company.company",
            "model_filters": {"is_supplier": True},
            "required": False,
        },
    }

    def __init__(self):
        super().__init__()
        self._active_supplier_slug: str = ""
        self.providers: dict[str, SupplierProvider] = {}

        # Ensure instance self.settings dict is populated and contains class settings
        if not hasattr(self, "settings") or not isinstance(self.settings, dict):
            self.settings = dict(getattr(self, "SETTINGS", {}))
        else:
            for k, v in getattr(self, "SETTINGS", {}).items():
                self.settings.setdefault(k, v)

        # Register default providers (this also registers provider-specific settings)
        self.register_provider(LandefeldProvider())

        # If SupplierMixin.__init__ forced SUPPLIER to required: True, relax it
        if "SUPPLIER" in self.settings:
            self.settings["SUPPLIER"]["required"] = False
            self.settings["SUPPLIER"]["name"] = "Default Supplier (Fallback)"
            self.settings["SUPPLIER"]["description"] = (
                "Fallback InvenTree supplier company if a supplier-specific setting is not set"
            )
        if hasattr(self, "SETTINGS") and "SUPPLIER" in self.SETTINGS:
            self.SETTINGS["SUPPLIER"]["required"] = False

    def register_provider(self, provider: SupplierProvider) -> None:
        """Register a new supplier provider and ensure its configuration setting is registered."""
        self.providers[provider.slug] = provider

        setting_key = f"SUPPLIER_{provider.slug.upper()}"
        setting_def = {
            "name": f"Supplier ({provider.name})",
            "description": f"InvenTree supplier company for {provider.name} parts",
            "model": "company.company",
            "model_filters": {"is_supplier": True},
            "required": False,
        }

        if hasattr(self, "settings") and isinstance(self.settings, dict):
            self.settings.setdefault(setting_key, setting_def)
        if hasattr(self, "SETTINGS") and isinstance(self.SETTINGS, dict):
            self.SETTINGS.setdefault(setting_key, setting_def)

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

    def _resolve_supplier_company(
        self,
        supplier_slug: str = "",
        supplier_name: str = "",
        website: str = "",
    ):
        """Resolve InvenTree Company model for a given supplier."""
        if not supplier_slug and self._active_supplier_slug:
            supplier_slug = self._active_supplier_slug
        if not supplier_slug and self.providers:
            supplier_slug = next(iter(self.providers.keys()))

        provider = self.providers.get(supplier_slug) if supplier_slug else None

        if not supplier_name and provider:
            supplier_name = provider.name
        if not supplier_name:
            supplier_name = "Landefeld"

        if not website and provider:
            website = (
                getattr(provider, "base_url", "")
                or getattr(provider, "website", "")
            )
        if not website and supplier_name.lower() == "landefeld":
            website = "https://www.landefeld.de"

        get_setting_func = getattr(self, "get_setting", None)

        # 1. Check provider-specific setting (e.g. SUPPLIER_LANDEFELD)
        if callable(get_setting_func) and supplier_slug:
            setting_key = f"SUPPLIER_{supplier_slug.upper()}"
            try:
                pk = get_setting_func(setting_key, cache=True)
                if pk and Company is not None:
                    return Company.objects.get(pk=pk)
            except (AttributeError, KeyError, ValueError):
                pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to retrieve configured %s: %s", setting_key, exc)

        # 2. Check general fallback SUPPLIER setting
        if callable(get_setting_func):
            try:
                pk = get_setting_func("SUPPLIER", cache=True)
                if pk and Company is not None:
                    return Company.objects.get(pk=pk)
            except (AttributeError, KeyError, ValueError):
                pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to retrieve configured SUPPLIER company: %s", exc)

        # 3. Lookup existing company by name
        if Company is not None:
            try:
                company_obj = Company.objects.filter(name__iexact=supplier_name).first()
                if company_obj:
                    if not company_obj.is_supplier:
                        company_obj.is_supplier = True
                        company_obj.save()
                    return company_obj
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to query company by name %s: %s", supplier_name, exc)

        # 4. Safely auto-create company
        try:
            company_obj = self._get_or_create_company(
                name=supplier_name,
                is_supplier=True,
                website=website,
            )
            if company_obj is not None:
                return company_obj
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not auto-create company %s: %s", supplier_name, exc)

        # 5. If everything fails, raise PartImportError with clear actionable instruction
        setting_key = f"SUPPLIER_{supplier_slug.upper()}" if supplier_slug else "SUPPLIER"
        raise supplier.PartImportError(
            f"Supplier setting is missing for '{supplier_name}'. "
            f"Please configure '{setting_key}' in InvenTree Plugin Settings."
        )

    @property
    def supplier_company(self):
        """Return the supplier company object."""
        return self._resolve_supplier_company(supplier_slug=self._active_supplier_slug)

    def get_supplier_company_for_product(self, data: SupplierProduct):
        """Get or create the supplier company for a specific product dynamically."""
        supplier_slug = getattr(data, "supplier_slug", "")
        supplier_name = getattr(data, "supplier_name", "")
        brand = getattr(data, "brand", "")

        if not supplier_slug and self._active_supplier_slug:
            supplier_slug = self._active_supplier_slug

        if not supplier_slug and brand:
            for p in self.providers.values():
                if brand.lower() in (p.name.lower(), p.slug.lower()):
                    supplier_slug = p.slug
                    if not supplier_name:
                        supplier_name = p.name
                    break

        return self._resolve_supplier_company(
            supplier_slug=supplier_slug,
            supplier_name=supplier_name,
        )

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
        download_setting = getattr(self, "get_setting", lambda _: False)("DOWNLOAD_IMAGES")
        if isinstance(download_setting, str):
            download_images = download_setting.strip().lower() in ("true", "1", "yes", "t")
        else:
            download_images = bool(download_setting)

        if (
            created
            and data.image_url
            and settings
            and not getattr(settings, "TESTING", False)
            and download_images
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


class SupplierIntegrationPlugin(SupplierAdditionPlugin):
    """Backward-compatible plugin identity for existing InvenTree installations."""

    TITLE = "Supplier Integration"
    NAME = "Supplier Integration"
    SLUG = "supplierintegration"
    DESCRIPTION = "Modular supplier addition and integration plugin for InvenTree"
    VERSION = PLUGIN_VERSION


# Compatibility aliases
SupplierAddition = SupplierAdditionPlugin
SupplierIntegration = SupplierIntegrationPlugin

