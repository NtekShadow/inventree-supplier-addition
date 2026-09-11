"""Unit tests for Landefeld provider and models."""

from unittest.mock import MagicMock, patch

import pytest

from inventree_supplier_addition.models import SupplierProduct
from inventree_supplier_addition.suppliers.landefeld import LandefeldProvider


def test_supplier_product_creation():
    product = SupplierProduct(
        sku="TEST-SKU-123",
        name="Test Item",
        description="A test item description",
        price={1: (12.50, "EUR")},
        link="https://www.example.com/test",
        image_url="https://www.example.com/test.jpg",
        brand="Festo/Originalteil",
        parameters={"VPE": "10"},
    )
    assert product.sku == "TEST-SKU-123"
    assert product.price[1] == (12.50, "EUR")
    assert product.brand == "Festo/Originalteil"
    assert product.parameters["VPE"] == "10"


def test_parse_server_object():
    provider = LandefeldProvider()

    # Valid JSON string
    assert provider._parse_server_object('{"key": "value"}') == {"key": "value"}

    # JSON with prefix and suffix
    assert provider._parse_server_object('callback({"key": 42});') == {"key": 42}

    # Non-string object
    assert provider._parse_server_object(123) == 123
    assert provider._parse_server_object({"already": "dict"}) == {"already": "dict"}

    # Invalid JSON
    assert provider._parse_server_object("no-json-here") == "no-json-here"
    assert provider._parse_server_object("{unclosed-json") == "{unclosed-json"


@patch("inventree_supplier_addition.suppliers.landefeld.requests.post")
def test_search_and_get_product(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "payload": {
            "artikelliste": [
                {
                    "anzeigeartikel": '{"ArtikelnummerAngezeigt": "H300.001", "Bezeichnung": "Schlauchverbinder", "SEO_URL_Artikel": "/art/h300001", "HauptbildArtikel": "/img/h300001.jpg", "ist_Originalteil": 0, "VPE": "5.00", "Einheit": "STK", "Vorteil": "robust"}',
                    "preismodul": '{"Anzeigepreis": "{\\"Nettopreis\\": 3.45}"}',
                }
            ]
        }
    }
    mock_post.return_value = mock_response

    provider = LandefeldProvider()
    results = provider.search("H300.001")

    assert len(results) == 1
    product = results[0]
    assert product.sku == "H300.001"
    assert product.name == "Schlauchverbinder"
    assert product.price == {1: (3.45, "EUR")}
    assert product.brand == "Landefeld"
    assert product.link == "https://www.landefeld.de/art/h300001"
    assert product.image_url == "https://www.landefeld.de/img/h300001.jpg"
    assert product.parameters["Verpackungseinheit"] == "5.00"
    assert product.parameters["Einheit"] == "STK"
    assert product.parameters["Vorteil"] == "robust"

    # Test get_product success
    found = provider.get_product("H300.001")
    assert found.sku == "H300.001"

    # Test get_product not found
    with pytest.raises(LookupError):
        provider.get_product("NONEXISTENT")
