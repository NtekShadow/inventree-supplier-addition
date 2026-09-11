"""Unit tests for SupplierAdditionPlugin."""

from unittest.mock import MagicMock

import pytest

from inventree_supplier_addition.core import (
    SupplierAddition,
    SupplierAdditionPlugin,
    SupplierIntegrationPlugin,
)
from inventree_supplier_addition.models import SupplierProduct


def test_plugin_metadata():
    plugin = SupplierAdditionPlugin()
    assert plugin.NAME == "Supplier Addition"
    assert plugin.SLUG == "supplier-addition"
    assert plugin.TITLE == "Supplier Addition"
    assert plugin.AUTHOR == "NtekShadow"
    assert plugin.LICENSE == "MIT"
    assert "DOWNLOAD_IMAGES" in plugin.SETTINGS
    assert plugin.SETTINGS["DOWNLOAD_IMAGES"]["default"] is False
    assert "SUPPLIER_LANDEFELD" in plugin.SETTINGS
    assert plugin.SETTINGS["SUPPLIER_LANDEFELD"]["model"] == "company.company"
    assert "SUPPLIER_GANTER" in plugin.SETTINGS
    assert plugin.SETTINGS["SUPPLIER_GANTER"]["model"] == "company.company"
    assert "SUPPLIER" in plugin.SETTINGS
    assert plugin.SETTINGS["SUPPLIER"]["required"] is False
    # Ensure instance settings are populated
    assert "DOWNLOAD_IMAGES" in plugin.settings
    assert "SUPPLIER_LANDEFELD" in plugin.settings
    assert "SUPPLIER_GANTER" in plugin.settings
    assert "SUPPLIER" in plugin.settings


def test_plugin_aliases():
    assert SupplierAddition is SupplierAdditionPlugin
    assert issubclass(SupplierIntegrationPlugin, SupplierAdditionPlugin)

    integration_plugin = SupplierIntegrationPlugin()
    assert integration_plugin.SLUG == "supplierintegration"
    assert integration_plugin.NAME == "Supplier Integration"
    assert "DOWNLOAD_IMAGES" in integration_plugin.SETTINGS
    assert "SUPPLIER_LANDEFELD" in integration_plugin.SETTINGS
    assert "SUPPLIER_GANTER" in integration_plugin.SETTINGS
    assert "SUPPLIER" in integration_plugin.SETTINGS



def test_plugin_providers():
    plugin = SupplierAdditionPlugin()
    suppliers = plugin.get_suppliers()
    slugs = [s.slug for s in suppliers]
    assert "landefeld" in slugs
    assert "ganter" in slugs

    provider_landefeld = plugin._get_provider("landefeld")
    assert provider_landefeld.name == "Landefeld"

    provider_ganter = plugin._get_provider("ganter")
    assert provider_ganter.name == "Ganter Norm"

    # Test slug aliases for Ganter
    assert plugin._get_provider("ganternorm").name == "Ganter Norm"
    assert plugin._get_provider("ganter-norm").name == "Ganter Norm"

    with pytest.raises(ValueError, match="Unknown supplier: nonexistent"):
        plugin._get_provider("nonexistent")


def test_register_custom_provider():
    class CustomProvider:
        slug = "custom"
        name = "Custom Supplier"

        def search(self, term: str):
            return []

        def get_product(self, sku: str):
            raise LookupError(sku)

    plugin = SupplierAdditionPlugin()
    plugin.register_provider(CustomProvider())

    assert "custom" in [s.slug for s in plugin.get_suppliers()]
    assert plugin._get_provider("custom").name == "Custom Supplier"


def test_format_price():
    plugin = SupplierAdditionPlugin()

    p1 = SupplierProduct(
        sku="1", name="Test", description="", price={1: (15.50, "EUR")}
    )
    assert plugin._format_price(p1) == "15.50 EUR"

    p2 = SupplierProduct(
        sku="2", name="Test", description="", price={1: (0.0, "EUR")}
    )
    assert plugin._format_price(p2) == "Preis auf Anfrage"

    p3 = SupplierProduct(sku="3", name="Test", description="", price={})
    assert plugin._format_price(p3) == "Preis auf Anfrage"


def test_parameters_and_pricing():
    plugin = SupplierAdditionPlugin()
    product = SupplierProduct(
        sku="123",
        name="Product",
        description="",
        price={1: (10.0, "EUR"), 10: (8.0, "EUR")},
        parameters={"Color": "Blue", "Empty": ""},
    )

    pricing = plugin.get_pricing_data(product)
    assert pricing == {1: (10.0, "EUR"), 10: (8.0, "EUR")}

    params = plugin.get_parameters(product)
    assert len(params) == 1
    assert params[0].name == "Color"
    assert params[0].value == "Blue"


def test_search_results_flow():
    plugin = SupplierAdditionPlugin()

    mock_provider = MagicMock()
    mock_provider.slug = "mock"
    mock_provider.name = "Mock"
    mock_provider.search.return_value = [
        SupplierProduct(
            sku="SKU-1",
            name="Name 1",
            description="Desc 1",
            price={1: (5.0, "EUR")},
            link="https://mock.com/1",
            image_url="https://mock.com/1.jpg",
        )
    ]
    plugin.register_provider(mock_provider)

    results = plugin.get_search_results("mock", "sku-1")
    assert len(results) == 1
    res = results[0]
    assert res.sku == "SKU-1"
    assert res.exact is True
    assert res.price == "5.00 EUR"
    assert res.link == "https://mock.com/1"


def test_supplier_company_fallback_mocked():
    from unittest.mock import MagicMock

    from inventree_supplier_addition import core

    plugin = SupplierAdditionPlugin()

    # Mock Company model
    mock_company_class = MagicMock()
    mock_company_class.objects.filter.return_value.first.return_value = None
    mock_landefeld = MagicMock()
    mock_landefeld.name = "Landefeld"
    mock_landefeld.is_supplier = True
    mock_company_class.objects.create.return_value = mock_landefeld

    orig_company = core.Company
    try:
        core.Company = mock_company_class
        # Test fallback when get_setting returns None
        plugin.get_setting = MagicMock(return_value=None)
        company = plugin.supplier_company
        assert company.name == "Landefeld"
        mock_company_class.objects.create.assert_called_once_with(
            name="Landefeld",
            is_supplier=True,
            is_manufacturer=False,
            website="https://www.landefeld.de",
        )

        # Test when get_setting is configured with PK
        mock_configured = MagicMock()
        mock_configured.name = "Configured Supplier"
        mock_company_class.objects.get.return_value = mock_configured
        plugin.get_setting = MagicMock(return_value=42)
        assert plugin.supplier_company.name == "Configured Supplier"
        mock_company_class.objects.get.assert_called_with(pk=42)
    finally:
        core.Company = orig_company


def test_multi_supplier_automatic_company_resolution():
    from unittest.mock import MagicMock

    from inventree_supplier_addition import core

    class MouserProvider:
        slug = "mouser"
        name = "Mouser Electronics"
        base_url = "https://www.mouser.com"

        def search(self, term: str):
            return [
                SupplierProduct(
                    sku="MOU-1",
                    name="Resistor",
                    description="10k",
                    price={1: (0.10, "USD")},
                    supplier_name=self.name,
                    supplier_slug=self.slug,
                )
            ]

        def get_product(self, sku: str):
            return SupplierProduct(
                sku=sku,
                name="Capacitor",
                description="100nF",
                price={1: (0.05, "USD")},
                supplier_name=self.name,
                supplier_slug=self.slug,
            )

    plugin = SupplierAdditionPlugin()
    plugin.register_provider(MouserProvider())

    # Mock Company table storage
    existing_companies = {}

    def mock_filter(name__iexact):
        res = MagicMock()
        company = existing_companies.get(name__iexact.lower())
        res.first.return_value = company
        return res

    def mock_create(name, is_supplier=False, is_manufacturer=False, website=""):
        mock_c = MagicMock()
        mock_c.name = name
        mock_c.is_supplier = is_supplier
        mock_c.is_manufacturer = is_manufacturer
        mock_c.website = website
        existing_companies[name.lower()] = mock_c
        return mock_c

    mock_company_class = MagicMock()
    mock_company_class.objects.filter.side_effect = mock_filter
    mock_company_class.objects.create.side_effect = mock_create

    orig_company = core.Company
    try:
        core.Company = mock_company_class
        plugin.get_setting = MagicMock(return_value=None)

        # 1. Search and import from Mouser
        mouser_data = plugin.get_import_data("mouser", "MOU-999")
        assert mouser_data.supplier_name == "Mouser Electronics"
        assert mouser_data.supplier_slug == "mouser"

        mouser_company = plugin.get_supplier_company_for_product(mouser_data)
        assert mouser_company.name == "Mouser Electronics"
        assert mouser_company.is_supplier is True
        assert mouser_company.website == "https://www.mouser.com"

        # 2. Search and import from Landefeld
        landefeld_product = SupplierProduct(
            sku="H300",
            name="Fitting",
            description="",
            price={1: (2.0, "EUR")},
            supplier_name="Landefeld",
            supplier_slug="landefeld",
        )
        landefeld_company = plugin.get_supplier_company_for_product(landefeld_product)
        assert landefeld_company.name == "Landefeld"
        assert landefeld_company.is_supplier is True
        assert landefeld_company.website == "https://www.landefeld.de"

        # 3. Ganter Norm resolution
        ganter_product = SupplierProduct(
            sku="GN 300-30-M3-SW",
            name="Klemmhebel",
            description="",
            price={1: (3.88, "EUR")},
            supplier_name="Ganter Norm",
            supplier_slug="ganter",
        )
        ganter_company = plugin.get_supplier_company_for_product(ganter_product)
        assert ganter_company.name == "Ganter Norm"
        assert ganter_company.is_supplier is True
        assert ganter_company.website == "https://www.ganternorm.com"

        # 4. Distinct companies exist in database
        assert "mouser electronics" in existing_companies
        assert "landefeld" in existing_companies
        assert "ganter norm" in existing_companies
    finally:
        core.Company = orig_company


def test_supplier_setting_override_and_extensibility():
    from unittest.mock import MagicMock

    from inventree_supplier_addition import core

    plugin = SupplierAdditionPlugin()

    # Verify that registering a new provider dynamically registers its setting
    class FarnellProvider:
        slug = "farnell"
        name = "Farnell"
        def search(self, term: str): return []
        def get_product(self, sku: str): raise LookupError(sku)

    plugin.register_provider(FarnellProvider())
    assert "SUPPLIER_FARNELL" in plugin.settings
    assert plugin.settings["SUPPLIER_FARNELL"]["name"] == "Supplier (Farnell)"
    assert plugin.settings["SUPPLIER_FARNELL"]["model"] == "company.company"

    # Test that configured SUPPLIER_LANDEFELD overrides global or auto-created company
    mock_company_class = MagicMock()
    mock_landefeld_comp = MagicMock()
    mock_landefeld_comp.name = "Configured Landefeld"
    mock_company_class.objects.get.return_value = mock_landefeld_comp

    orig_company = core.Company
    try:
        core.Company = mock_company_class

        def mock_get_setting(key, **kwargs):
            if key == "SUPPLIER_LANDEFELD":
                return 101
            if key == "SUPPLIER":
                return 999
            return None

        plugin.get_setting = MagicMock(side_effect=mock_get_setting)

        product = SupplierProduct(
            sku="123",
            name="Test",
            description="",
            price={1: (1.0, "EUR")},
            supplier_slug="landefeld",
            supplier_name="Landefeld",
        )
        resolved = plugin.get_supplier_company_for_product(product)
        mock_company_class.objects.get.assert_called_with(pk=101)
        assert resolved.name == "Configured Landefeld"
    finally:
        core.Company = orig_company
