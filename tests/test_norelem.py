"""Unit tests for norelem provider."""

from unittest.mock import MagicMock

import pytest

from inventree_supplier_addition.suppliers.norelem import NorelemProvider

BASE = "https://www.norelem.de/de"
IMAGE = "/medias/Zoom-Default-03080.png?context=" + "x" * 230


def _response(text="", payload=None, status_code=200, url=""):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.url = url
    response.json.return_value = payload
    response.headers = {}
    return response


PRODUCT_PAGE = f"""
<html><body>
<product-image-gallery :gallery-image-count=2>
  <template #slider-main>
    <div class="swiper-slide"><img loading="lazy" src="{IMAGE}" alt=""></div>
  </template>
  <template #slider-thumbs>
    <div class="swiper-slide"><img src="/medias/Thumbnail-Default-03080.png?context=abc"></div>
  </template>
</product-image-gallery>
<product-details family-number="03080" product-number="03080-10" product-code="000000000000105686">
  <template #product-name>
    <h1 class="product-details__name">
        Exzenteranschlag
    </h1>
    <div class="product-details__features">Vergütungsstahl</div>
  </template>
  <template #scale-prices>
    <div class="scale-prices__wrapper">
      <scale-price-button amount="1" price="14,92&nbsp;€" active></scale-price-button>
      <scale-price-button amount="10" price="13,50&nbsp;€"></scale-price-button>
    </div>
  </template>
</product-details>
<div class="details-tab__wrapper">
  <category-texts>
    <div class="category-texts__table">
      <div class="category-texts__cell -product">
        <div class="category-texts__cell-headline"><span>Benennung</span></div>
        <div class="category-texts__cell-text">Exzenteranschlag</div>
      </div>
      <div class="category-texts__cell -product">
        <div class="category-texts__cell-headline"><span>Material
Grundkörper</span></div>
        <div class="category-texts__cell-text">Vergütungsstahl</div>
      </div>
      <div class="category-texts__cell -product">
        <div class="category-texts__cell-headline"><span>D=Durchmesser</span></div>
        <div class="category-texts__cell-text">32</div>
      </div>
      <div class="category-texts__cell -product">
        <div class="category-texts__cell-headline"><span>H=Höhe</span></div>
        <div class="category-texts__cell-text">20</div>
      </div>
      <div class="category-texts__cell -product">
        <div class="category-texts__cell-headline"><span>~ RoHS conformity</span></div>
        <div class="category-texts__cell-text">yes, without exemption</div>
      </div>
    </div>
  </category-texts>
  <div class="product-details__info-wrapper">
    <div class="nlm-category-texts category-texts__table">
      <div class="category-texts__cell">
        <div class="category-texts__cell-headline"><span>Werkstoff</span></div>
        <div class="category-texts__cell-text">Vergütungsstahl.</div>
      </div>
    </div>
  </div>
</div>
</body></html>
"""

GROUP_PAGE = """
<html><body>
<product-family-details family-number="03080" product-name="Exzenteranschläge"></product-family-details>
<product-variants product-code="agid.2502"></product-variants>
</body></html>
"""

VARIANTS_PAYLOAD = {
    "product": {"numberOfProducts": 2},
    "facets": [
        {"code": "5", "name": "D=Durchmesser"},
        {"code": "15", "name": "H=Höhe"},
    ],
    "products": [
        {
            "code": "03080-05",
            "name": "\r\nEXZENTERANSCHLAG D=16 H=10\r\nVERGÜTUNGSSTAHL",
            "familyNumber": "03080",
            "attr_5": "16",
            "attr_15": "10",
            "enquiryOnly": False,
            "scalePrices": [],
            "price": {"currencyIso": "EUR", "value": 9.18},
            "imageUrl": "/medias/Grid-Default-03080.png?context=abc",
        },
        {
            "code": "03080-10",
            "name": "EXZENTERANSCHLAG D=32 H=20 VERGÜTUNGSSTAHL",
            "familyNumber": "03080",
            "attr_5": "32",
            "attr_15": "20",
            "enquiryOnly": True,
            "scalePrices": [],
            "price": {"currencyIso": "EUR", "value": 14.92},
        },
    ],
}

SEARCH_LIST_PAGE = """
<html><body>
<product-tile product-name="Rändelmuttern" family-number="06070"
    product-url="/de/Produktuebersicht/Raendelmuttern/p/agid.3001" product-count="1"></product-tile>
<product-tile product-name="Kugelknöpfe" family-number="06247"
    product-url="/de/Produktuebersicht/Kugelknoepfe/p/agid.3467" product-count="1"></product-tile>
</body></html>
"""

PRICE_PAYLOAD = {
    "success": True,
    "data": {
        "enquiryOnly": False,
        "scalePrices": [
            {"minQuantity": 1, "netPrice": {"price": {"value": 0.42}}},
            {"minQuantity": 50, "netPrice": {"price": {"value": 0.38}}},
        ],
        "price": {"netPrice": {"price": {"value": 0.42}}},
    },
}


def test_norelem_provider_metadata():
    provider = NorelemProvider()
    assert provider.slug == "norelem"
    assert provider.name == "norelem"
    assert provider.base_url == "https://www.norelem.de"
    assert provider._product_link("03080-10") == f"{BASE}/p/03080-10"
    # Bot protection workaround: HTTPS requests use the reduced cipher adapter
    assert type(provider.session.get_adapter("https://www.norelem.de")).__name__ == "_ModernTLSAdapter"


def test_helpers():
    provider = NorelemProvider()
    assert provider._parse_price_text("14,92\xa0€") == 14.92
    assert provider._parse_price_text("1.351,00 €") == 1351.0
    assert provider._parse_price_text("auf Anfrage") is None
    assert provider._absolute("/medias/x.png") == "https://www.norelem.de/medias/x.png"
    assert provider._parse_price_breaks([], {"value": 0}) == {}
    assert provider._parse_price_breaks(PRICE_PAYLOAD["data"]["scalePrices"]) == {
        1: (0.42, "EUR"),
        50: (0.38, "EUR"),
    }


def test_get_product():
    provider = NorelemProvider()
    provider.session = MagicMock()
    provider.session.get.return_value = _response(PRODUCT_PAGE, url=f"{BASE}/x/p/03080-10")

    product = provider.get_product("03080-10")

    assert product.sku == "03080-10"
    assert product.name == "Exzenteranschlag Vergütungsstahl"
    assert product.description == "Exzenteranschlag Vergütungsstahl, D=32 H=20"
    assert product.price == {1: (14.92, "EUR"), 10: (13.5, "EUR")}
    assert product.link == f"{BASE}/p/03080-10"
    assert product.image_url == "https://www.norelem.de" + IMAGE
    assert product.brand == "norelem"
    assert product.parameters["Material Grundkörper"] == "Vergütungsstahl"
    assert product.parameters["D=Durchmesser"] == "32"
    assert product.parameters["RoHS conformity"] == "yes, without exemption"
    assert product.parameters["Werkstoff"] == "Vergütungsstahl."
    assert product.parameters["Artikelfamilie"] == "03080"
    assert "Benennung" not in product.parameters

    # Prices rendered on the page are used, the price service is not called
    assert provider.session.get.call_count == 1


def test_get_product_price_fallback():
    provider = NorelemProvider()
    provider.session = MagicMock()
    page = PRODUCT_PAGE.replace("scale-price-button", "span")
    provider.session.get.side_effect = [_response(page), _response(payload=PRICE_PAYLOAD)]

    product = provider.get_product("03080-10")

    assert product.price == {1: (0.42, "EUR"), 50: (0.38, "EUR")}
    assert provider.session.get.call_args.kwargs["params"] == {"articleCode": "03080-10", "quantity": 1}


def test_get_product_not_found():
    provider = NorelemProvider()
    provider.session = MagicMock()
    provider.session.get.return_value = _response("not found", status_code=404)

    with pytest.raises(LookupError):
        provider.get_product("03080-99")

    # A page of another article (or a group) is not accepted
    provider.session.get.return_value = _response(PRODUCT_PAGE)
    with pytest.raises(LookupError):
        provider.get_product("03080-11")
    with pytest.raises(LookupError):
        provider.get_product("agid.2502")


def test_search_exact_article_redirect():
    provider = NorelemProvider()
    provider.session = MagicMock()
    provider.session.get.return_value = _response(PRODUCT_PAGE, url=f"{BASE}/Produktuebersicht/x/p/03080-10")

    results = provider.search("03080-10")

    assert [p.sku for p in results] == ["03080-10"]
    assert provider.session.get.call_args_list[0].kwargs["params"] == {"text": "03080-10"}


def test_search_group_redirect():
    provider = NorelemProvider()
    provider.session = MagicMock()
    provider.session.get.side_effect = [
        _response(GROUP_PAGE, url=f"{BASE}/Produktuebersicht/x/p/agid.2502"),
        _response(payload=VARIANTS_PAYLOAD),
    ]

    results = provider.search("03080")

    assert [p.sku for p in results] == ["03080-05", "03080-10"]
    first = results[0]
    assert first.name == "Exzenteranschläge"
    assert first.description == "EXZENTERANSCHLAG D=16 H=10 VERGÜTUNGSSTAHL"
    assert first.price == {1: (9.18, "EUR")}
    assert first.parameters == {"D=Durchmesser": "16", "H=Höhe": "10", "Artikelfamilie": "03080"}
    assert first.image_url == "https://www.norelem.de/medias/Grid-Default-03080.png?context=abc"
    assert results[1].price == {}  # enquiry only

    assert provider.session.get.call_args.args[0] == f"{BASE}/p/agid.2502/facets_and_results"


def test_search_result_list_expands_groups():
    provider = NorelemProvider()
    provider.session = MagicMock()

    def fake_get(url, **kwargs):
        if url.endswith("/search"):
            return _response(SEARCH_LIST_PAGE, url=f"{BASE}/search?text=03080")
        return _response(payload=VARIANTS_PAYLOAD if "agid.3467" in url else {"products": []})

    provider.session.get.side_effect = fake_get

    results = provider.search("03080-1")

    # Articles starting with the search term are ranked first
    assert [p.sku for p in results] == ["03080-10", "03080-05"]
    assert results[0].name == "Kugelknöpfe"


def test_search_no_results():
    provider = NorelemProvider()
    provider.session = MagicMock()
    provider.session.get.return_value = _response("<html></html>", url=f"{BASE}/search?text=x")
    assert provider.search("x") == []
    assert provider.search("  ") == []
