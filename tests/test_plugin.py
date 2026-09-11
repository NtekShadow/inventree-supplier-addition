"""Unit tests for SupplierAdditionPlugin."""

from unittest.mock import MagicMock
import pytest

from inventree_supplier_addition.core import (
    SupplierAddition,
    SupplierAdditionPlugin,
    SupplierIntegrationPlugin,
)
from inventree_supplier_addition.models import SupplierProduct, SupplierProvider


def test_plugin_metadata():
    plugin = SupplierAdditionPlugin()
    assert plugin.NAME == "Supplier Addition"
    assert plugin.SLUG == "supplier-addition"
    assert plugin.TITLE == "Supplier Addition"
    assert plugin.AUTHOR == "NtekShadow"
    assert plugin.LICENSE == "MIT"
    assert "DOWNLOAD_IMAGES" in plugin.SETTINGS
    assert plugin.SETTINGS["DOWNLOAD_IMAGES"]["default"] is False


def test_plugin_aliases():
    assert SupplierAddition is SupplierAdditionPlugin
    assert SupplierIntegrationPlugin is SupplierAdditionPlugin


def test_plugin_providers():
    plugin = SupplierAdditionPlugin()
    suppliers = plugin.get_suppliers()
    slugs = [s.slug for s in suppliers]
    assert "landefeld" in slugs

    provider = plugin._get_provider("landefeld")
    assert provider.name == "Landefeld"

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
    import inventree_supplier_addition.core as core

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
