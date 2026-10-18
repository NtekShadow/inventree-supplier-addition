"""Unit tests for igus provider."""

from unittest.mock import MagicMock

import pytest

from inventree_supplier_addition.suppliers.igus import IgusProvider


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


SEARCH_PAYLOAD = {
    "articles": {
        "data": [
            {
                "sku": "RJUM-01-20",
                "title": "drylin® R Lineargleitbuchse RJUM-01",
                "productUrl": "https://www.igus.de/articlerouter/RJUM-01-20",
                "imageUrl": "https://igus.widen.net/content/abc/jpeg/RJUM-01.jpeg?w=540",
                "isArticleDiscontinued": False,
            },
            {
                "sku": "RJUM-01-10",
                "title": "drylin® R Lineargleitbuchse RJUM-01",
                "productUrl": "https://www.igus.de/articlerouter/RJUM-01-10",
                "imageUrl": "https://igus.widen.net/content/abc/jpeg/RJUM-01.jpeg?w=540",
                "isArticleDiscontinued": False,
            },
            {
                "sku": "RJUM-01-OLD",
                "title": "discontinued",
                "isArticleDiscontinued": True,
            },
        ]
    }
}

PRICES_PAYLOAD = {
    "RJUM-01-10": {
        "priceScales": [
            {"quantityText": "1 Stk.", "priceText": "8,62 EUR/Stk."},
            {"quantityText": "10 Stk.", "priceText": "8,13 EUR/Stk."},
        ]
    },
    "RJUM-01-20": {"priceScales": [{"quantityText": "1 Stk.", "priceText": "Preis auf Anfrage"}]},
}

CURRENT_PRODUCT_PAYLOAD = {
    "id": "RJUM-01-10",
    "assets": [
        {
            "key": "attr_image_01",
            "sources": [
                {"uri": "//igus.widen.net/content/duy5nsoqep/png/drylinR_RJUM-01.png?w=300&h=300&u=x"}
            ],
        }
    ],
    "prices": [
        {"price": -1, "discount_threshold": 5000, "currency_code": "EUR", "unit_multiplier": 1},
        {"price": 6.63, "discount_threshold": 100, "currency_code": "EUR", "unit_multiplier": 1},
        {"price": 8.13, "discount_threshold": 10, "currency_code": "EUR", "unit_multiplier": 1},
        {"price": 8.62, "discount_threshold": 1, "currency_code": "EUR", "unit_multiplier": 1},
        {"price": 8.62, "discount_threshold": 0, "currency_code": "EUR", "unit_multiplier": 1},
    ],
    "attributes": {
        "series_description": {"label": "Serienbezeichnung", "value": "drylin® R Lineargleitbuchse RJUM-01"},
        "article_description_text_area": {"label": "Artikelbezeichnung", "value": "drylin® Adapter, geschlossen"},
        "webshop_technical_data_attributes": "drylin_r_linear_slide_bearings",
        "sales_unit": {"label": "Verkaufseinheit", "value": "Stück"},
        "shipping_weight": {"label": "Versandgewicht", "value": "0.014403"},
    },
    "delivery_times": [{"code": 3, "label": "in 24 Stunden versandfertig"}],
}

TECHNICAL_DATA_PAYLOAD = {
    "chemicalAttributeNames": ["acetone"],
    "technicalProductAttributes": {
        "diameter_d1": {"label": "Ø d1", "value": {"unit": "MILLIMETER", "amount": 10.0}},
        "attr_f_max": {"label": "Fmax.", "value": {"unit": "NEWTON", "amount": 725}},
        "s_tolerance": {"label": "s-Toleranz", "value": "H10"},
        "resistance": {"label": "Widerstand", "value": "> 10<sup>11</sup> Ω"},
        "acetone": {"label": "Aceton", "value": "+ beständig"},
        "detectable": {"label": "Detektierbar", "value": False},
        "nominal_voltage": {"label": "Nennspannung", "value": "nominal_volt_11"},
    },
}


def test_igus_provider_metadata():
    provider = IgusProvider()
    assert provider.slug == "igus"
    assert provider.name == "igus"
    assert provider.base_url == "https://www.igus.de"


def test_helpers():
    provider = IgusProvider()
    assert provider._parse_price_text("8,62 EUR/Stk.") == 8.62
    assert provider._parse_price_text("1.234,50 EUR/m") == 1234.5
    assert provider._parse_price_text("Preis auf Anfrage") is None
    assert provider._image_url("//igus.widen.net/x.png?w=300&h=300") == "https://igus.widen.net/x.png?w=600&h=600"
    assert provider._format_value({"unit": "MILLIMETER", "amount": 17.5}) == "17.5 mm"
    assert provider._format_value({"unit": "CELSIUS", "amount": -40.0}) == "-40 °C"
    assert provider._product_link("CF5.05.07") == "https://www.igus.de/articlerouter/CF5.05.07"


def test_search():
    provider = IgusProvider()
    provider.session = MagicMock()
    provider.session.get.return_value = _response(SEARCH_PAYLOAD)
    provider.session.post.return_value = _response(PRICES_PAYLOAD)

    results = provider.search("RJUM-01-10")

    assert [p.sku for p in results] == ["RJUM-01-10", "RJUM-01-20"]
    assert results[0].price == {1: (8.62, "EUR")}
    assert results[0].link == "https://www.igus.de/articlerouter/RJUM-01-10"
    assert results[0].brand == "igus"
    assert results[1].price == {}

    url = provider.session.get.call_args[0][0]
    assert url == "https://api.igus.com/search/unified-search/de-DE/RJUM-01-10"
    assert provider.session.post.call_args.kwargs["json"] == {"skus": ["RJUM-01-10", "RJUM-01-20"]}


def test_get_product():
    provider = IgusProvider()
    provider.session = MagicMock()
    provider.session.post.side_effect = [
        _response(CURRENT_PRODUCT_PAYLOAD),
        _response(TECHNICAL_DATA_PAYLOAD),
    ]

    product = provider.get_product("RJUM-01-10")

    assert product.sku == "RJUM-01-10"
    assert product.name == "drylin® R Lineargleitbuchse RJUM-01"
    assert product.description == "drylin® R Lineargleitbuchse RJUM-01, drylin® Adapter, geschlossen"
    assert product.price == {
        1: (8.62, "EUR"),
        10: (8.13, "EUR"),
        100: (6.63, "EUR"),
    }
    assert product.image_url.startswith("https://igus.widen.net/content/duy5nsoqep/")
    assert "w=600" in product.image_url
    assert product.parameters["Ø d1"] == "10 mm"
    assert product.parameters["Fmax."] == "725 N"
    assert product.parameters["s-Toleranz"] == "H10"
    assert product.parameters["Widerstand"] == "> 10^11 Ω"
    assert product.parameters["Verkaufseinheit"] == "Stück"
    assert product.parameters["Versandgewicht"] == "0.014403 kg"
    assert product.parameters["Lieferzeit"] == "in 24 Stunden versandfertig"
    assert "Aceton" not in product.parameters
    assert "Detektierbar" not in product.parameters
    assert "Nennspannung" not in product.parameters

    tech_request = provider.session.post.call_args_list[1].kwargs["json"]
    assert tech_request["technicalDataReferenceEntityId"] == "drylin_r_linear_slide_bearings"


def test_get_product_not_found():
    provider = IgusProvider()
    provider.session = MagicMock()
    provider.session.post.return_value = _response({"error": "Internal Server Error"}, status_code=500)

    with pytest.raises(LookupError):
        provider.get_product("NOPE-123")
