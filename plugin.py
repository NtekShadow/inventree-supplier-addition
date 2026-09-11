from django.conf import settings

from company.models import Company, ManufacturerPart, SupplierPart, SupplierPriceBreak
from part.models import Part
from plugin.base.supplier import helpers as supplier
from plugin.base.supplier.mixins import SupplierMixin
from plugin.plugin import InvenTreePlugin

from supplier_models import SupplierProvider
from suppliers import LandefeldProvider


class SupplierIntegrationPlugin(SupplierMixin, InvenTreePlugin):
    """InvenTree adapter for supplier providers."""

    NAME = 'Supplier Integration'
    # Keep the original slug so InvenTree updates the existing installation.
    SLUG = 'landefeldsupplier'
    TITLE = 'Supplier Integration'
    VERSION = '0.1.0'

    SETTINGS = {
        'DOWNLOAD_IMAGES': {
            'name': 'Download part images',
            'description': 'Enable downloading of part images during import',
            'validator': bool,
            'default': False,
        }
    }

    def __init__(self):
        super().__init__()
        self.providers: dict[str, SupplierProvider] = {
            'landefeld': LandefeldProvider(),
        }

    def _get_provider(self, supplier_slug: str) -> SupplierProvider:
        try:
            return self.providers[supplier_slug]
        except KeyError as error:
            raise ValueError(f'Unknown supplier: {supplier_slug}') from error

    def get_suppliers(self) -> list[supplier.Supplier]:
        return [
            supplier.Supplier(slug=provider.slug, name=provider.name)
            for provider in self.providers.values()
        ]

    def get_search_results(self, supplier_slug: str, term: str) -> list[supplier.SearchResult]:
        provider = self._get_provider(supplier_slug)
        return [
            supplier.SearchResult(
                sku=product.sku,
                name=product.name,
                description=product.description,
                exact=product.sku.lower() == term.lower(),
                price=self._format_price(product),
                link=product.link,
                image_url=product.image_url,
                existing_part=getattr(
                    SupplierPart.objects.filter(SKU=product.sku).first(), 'part', None
                ),
            )
            for product in provider.search(term)
        ]

    @staticmethod
    def _format_price(product) -> str:
        price = product.price[1][0]
        return f'{price:.2f} EUR' if price > 0 else 'Preis auf Anfrage'

    def get_import_data(self, supplier_slug: str, part_id: str):
        try:
            return self._get_provider(supplier_slug).get_product(part_id)
        except LookupError as error:
            raise supplier.PartNotFoundError() from error

    def get_pricing_data(self, data) -> dict[int, tuple[float, str]]:
        return data.price

    def get_parameters(self, data) -> list[supplier.ImportParameter]:
        return [
            supplier.ImportParameter(name=name, value=value)
            for name, value in data.parameters.items()
            if value
        ]

    def import_part(self, data, **kwargs) -> Part:
        part, created = Part.objects.get_or_create(
            name__iexact=data.sku,
            purchaseable=True,
            defaults={
                'name': data.sku,
                'description': data.description,
                'link': data.link,
                **kwargs,
            },
        )
        if created and data.image_url and not settings.TESTING and self.get_setting('DOWNLOAD_IMAGES'):
            image_file, image_format = self.download_image(data.image_url)
            if image_file:
                part.image.save(f'part_{part.pk}_image.{image_format.lower()}', image_file)
        return part

    def import_manufacturer_part(self, data, **kwargs) -> ManufacturerPart:
        manufacturer, _ = Company.objects.get_or_create(
            name__iexact=data.brand,
            defaults={
                'is_manufacturer': True,
                'is_supplier': False,
                'name': data.brand,
            },
        )
        manufacturer_part, _ = ManufacturerPart.objects.get_or_create(
            MPN=data.sku, manufacturer=manufacturer, **kwargs
        )
        return manufacturer_part

    def import_supplier_part(self, data, **kwargs) -> SupplierPart:
        supplier_part, _ = SupplierPart.objects.get_or_create(
            SKU=data.sku,
            supplier=self.supplier_company,
            **kwargs,
            defaults={'link': data.link},
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