"""Unit tests for Ganter Norm provider."""

from unittest.mock import MagicMock, patch

import pytest

from inventree_supplier_addition.suppliers.ganter import GanterProvider


def test_ganter_provider_metadata():
    provider = GanterProvider()
    assert provider.slug == "ganter"
    assert provider.name == "Ganter Norm"
    assert "ganternorm.com" in provider.base_url
    assert "live-katalog.ganternorm.com" in provider.api_base_url


def test_clean_sku_and_strip_owner():
    provider = GanterProvider()
    assert provider._clean_sku("  GN   300-30-M3-SW  ") == "GN 300-30-M3-SW"
    assert provider._strip_owner("GN 300-30-M3-SW") == "300-30-M3-SW"
    assert provider._strip_owner("DIN 508-14-M12-8") == "508-14-M12-8"
    assert provider._strip_owner("ISO 4017-M8x20") == "4017-M8x20"


def test_fetch_price_and_params():
    provider = GanterProvider()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "preisInfo": """
            <div class="product-purchase__price__amount">
                <div class="product-purchase__net-price" id="net-price-id">
                    3,88 <span class="product-purchase__currency">€</span>
                </div>
            </div>
        """,
        "zusatzInfo": """
            <details>
                <summary>Gewicht: 0,026 kg</summary>
            </details>
            <details>
                <summary>RoHS: Ja</summary>
            </details>
            <details>
                <summary>Zolltarifnummer</summary>
                <div class="toggle__unit">84879090</div>
            </details>
        """,
        "lagerverfuegbarkeitInfo": """
            <ul>
                <li>200 Stück in 1-2 Tagen lieferbar</li>
            </ul>
        """,
    }

    with patch.object(provider.session, "get", return_value=mock_response):
        price, cur, params = provider._fetch_price_and_params("GN 300-30-M3-SW")
        assert price == 3.88
        assert cur == "EUR"
        assert params["Gewicht"] == "0,026 kg"
        assert params["RoHS"] == "Ja"
        assert params["Zolltarifnummer"] == "84879090"
        assert "200 Stück" in params["Verfügbarkeit"]


def test_search_quickfinder():
    provider = GanterProvider()

    # Mock schnell-suche (no redirect)
    mock_suche_res = MagicMock()
    mock_suche_res.status_code = 200

    # Mock quickfinder
    mock_qf_res = MagicMock()
    mock_qf_res.status_code = 200
    mock_qf_res.json.return_value = [
        {
            "norm": "GN 300 Verstellbare Klemmhebel, Zink-Druckguss, Einsatz Stahl brüniert, mit Innengewinde / Passbohrung",
            "url": "/de/produkte/gn300-ig",
            "guid": "guid-1",
            "urlHauptbildThumbnail": "https://live-katalog.ganternorm.com/img1-thumbnail.jpg?scaling=1",
        },
        {
            "norm": "GN 300 Verstellbare Klemmhebel, Zink-Druckguss, Einsatz Stahl brüniert, mit Außengewinde",
            "url": "/de/produkte/gn300-ag",
            "guid": "guid-2",
            "urlHauptbildThumbnail": "https://live-katalog.ganternorm.com/img2-thumbnail.jpg?scaling=1",
        },
        {
            "norm": "GN 300.1 Verstellbare Klemmhebel, Edelstahl",
            "url": "/de/produkte/gn3001",
            "guid": "guid-3",
            "urlHauptbildThumbnail": "https://live-katalog.ganternorm.com/img3-thumbnail.jpg?scaling=1",
        },
    ]

    def mock_get(url, **kwargs):
        if "schnell-suche" in url:
            return mock_suche_res
        if "quickfinder" in url:
            return mock_qf_res
        raise ValueError(f"Unexpected URL: {url}")

    with patch.object(provider.session, "get", side_effect=mock_get):
        results = provider.search("GN 300")
        assert len(results) == 3
        # First two share "GN 300" so they are disambiguated by short feature
        assert "GN 300" in results[0].sku
        assert "GN 300" in results[1].sku
        assert results[0].sku != results[1].sku
        # Third one is unique
        assert results[2].sku == "GN 300.1"
        assert results[0].supplier_name == "Ganter Norm"
        assert results[0].supplier_slug == "ganter"
        assert results[0].image_url == "https://live-katalog.ganternorm.com/img1.jpg"


def test_search_exact_redirect():
    provider = GanterProvider()

    mock_redirect_res = MagicMock()
    mock_redirect_res.status_code = 301
    mock_redirect_res.headers = {
        "Location": "/de/produkte/gn300-detail#l1=c(30);Farbe=SW"
    }

    mock_page_res = MagicMock()
    mock_page_res.status_code = 200
    mock_page_res.text = """
        <html>
            <h1 itemprop="name">GN 300 Verstellbare Klemmhebel</h1>
            <div itemprop="description">Hochwertige verstellbare Klemmhebel.</div>
            <img itemprop="image" src="https://live-katalog.ganternorm.com/catalog-images/ganter/gn300-SW-schwarz-thumbnail.jpg" />
            <meta itemprop="price" content="3.50" />
            <meta itemprop="priceCurrency" content="EUR" />
        </html>
    """

    mock_price_res = MagicMock()
    mock_price_res.status_code = 200
    mock_price_res.json.return_value = {
        "preisInfo": '<div id="net-price-id">3,88 €</div>',
        "zusatzInfo": "<details><summary>Gewicht: 0,026 kg</summary></details>",
    }

    def mock_get(url, **kwargs):
        if "schnell-suche" in url:
            return mock_redirect_res
        if "gn300-detail" in url:
            return mock_page_res
        if "artikelpreisinfo" in url:
            return mock_price_res
        raise ValueError(f"Unexpected URL: {url}")

    with patch.object(provider.session, "get", side_effect=mock_get):
        results = provider.search("GN 300-30-M3-SW")
        assert len(results) == 1
        prod = results[0]
        assert prod.sku == "GN 300-30-M3-SW"
        assert prod.name == "GN 300-30-M3-SW Verstellbare Klemmhebel"
        assert prod.price[1] == (3.88, "EUR")
        assert prod.price[52] == (3.49, "EUR")
        assert prod.price[78] == (3.10, "EUR")
        assert prod.price[104] == (2.72, "EUR")
        assert prod.parameters["Gewicht"] == "0,026 kg"
        assert prod.parameters["Norm"] == "GN 300"
        assert "Rabattstaffel" in prod.parameters
        assert "gn300-SW-schwarz.jpg" in prod.image_url


def test_get_product_from_cache_or_lookup():
    provider = GanterProvider()

    # Seed cache
    from inventree_supplier_addition.models import SupplierProduct
    cached_prod = SupplierProduct(
        sku="GN 505-10-M6",
        name="Hammerkopfmutter",
        description="Aluprofil Befestigung",
        price={1: (1.20, "EUR")},
        link="https://www.ganternorm.com/de/produkte/gn505",
        parameters={"Gewicht": "0,01 kg"},
    )
    provider._cache["GN 505-10-M6"] = cached_prod

    # Should return cached product directly
    p = provider.get_product("GN 505-10-M6")
    assert p.sku == "GN 505-10-M6"
    assert p.price == {1: (1.20, "EUR")}

    # Nonexistent product should raise LookupError
    with (
        patch.object(provider.session, "get", return_value=MagicMock(status_code=404, text="")),
        pytest.raises(LookupError),
    ):
        provider.get_product("NONEXISTENT-999")


def test_parse_config_dimensions_and_mapping():
    from bs4 import BeautifulSoup

    provider = GanterProvider()

    html = """
    <div id="product-dimensions">
        <fieldset>
            <legend>Grifflänge l 1</legend>
            <label>22</label>
            <label>30</label>
            <label>63</label>
        </fieldset>
        <fieldset>
            <legend>Anschlussgewinde d 1</legend>
            <label>M 3</label>
            <label>M 6</label>
            <label>M 8</label>
        </fieldset>
        <fieldset>
            <legend>Farbe</legend>
            <label>CR - verchromt</label>
            <label>SW - schwarz, RAL 9005, strukturmatt</label>
        </fieldset>
        <fieldset>
            <legend>Ausführungen</legend>
            <label>GN 300 Verstellbare Klemmhebel</label>
        </fieldset>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    dims = provider._parse_config_dimensions(soup)
    assert "Grifflänge" in dims
    assert "Anschlussgewinde" in dims
    assert "Farbe" in dims
    assert "Ausführungen" not in dims
    assert dims["Grifflänge"] == ["22", "30", "63"]

    params = provider._map_sku_to_parameters("GN 300-63-M8-SW", dims)
    assert params["Norm"] == "GN 300"
    assert params["Grifflänge"] == "63 mm"
    assert params["Anschlussgewinde"] == "M 8"
    assert params["Farbe"] == "SW - schwarz, RAL 9005, strukturmatt"


def test_search_variants_by_tokens():
    provider = GanterProvider()

    mock_qf = MagicMock()
    mock_qf.status_code = 200
    mock_qf.json.return_value = [
        {
            "norm": "GN 300 Verstellbare Klemmhebel, Zink-Druckguss",
            "url": "/de/produkte/gn300",
        }
    ]

    mock_page = MagicMock()
    mock_page.status_code = 200
    mock_page.text = """
    <html>
        <h1>GN 300 Verstellbare Klemmhebel</h1>
        <div id="product-dimensions">
            <fieldset>
                <legend>Grifflänge l 1</legend>
                <label>45</label>
                <label>63</label>
            </fieldset>
            <fieldset>
                <legend>Anschlussgewinde d 1</legend>
                <label>M 6</label>
                <label>M 8</label>
            </fieldset>
            <fieldset>
                <legend>Farbe</legend>
                <label>SW - schwarz</label>
                <label>RS - rot</label>
            </fieldset>
        </div>
        <div>
            <span style="display:none">GN 300-45-M6-SW</span>
            <span style="display:none">GN 300-63-M8-SW</span>
            <span style="display:none">GN 300-63-M8-RS</span>
            <span style="display:none">GN 300-63-M8-20-SW</span>
        </div>
    </html>
    """

    mock_suche = MagicMock()
    mock_suche.status_code = 200  # no redirect

    def mock_get(url, **kwargs):
        if "schnell-suche" in url:
            return mock_suche
        if "quickfinder" in url:
            return mock_qf
        if "gn300" in url:
            return mock_page
        raise ValueError(f"Unexpected URL: {url}")

    with patch.object(provider.session, "get", side_effect=mock_get):
        # Query matching M8 variants
        results = provider.search("GN 300 M8")
        assert len(results) == 3
        skus = [r.sku for r in results]
        assert "GN 300-63-M8-SW" in skus
        assert "GN 300-63-M8-RS" in skus
        assert "GN 300-63-M8-20-SW" in skus
        assert "GN 300-45-M6-SW" not in skus

        # Check parameter mapping on result
        m8_sw = next(r for r in results if r.sku == "GN 300-63-M8-SW")
        assert m8_sw.parameters["Grifflänge"] == "63 mm"
        assert m8_sw.parameters["Anschlussgewinde"] == "M 8"
        assert m8_sw.parameters["Farbe"] == "SW - schwarz"


def test_calculate_price_breaks():
    provider = GanterProvider()

    # Base price 4.58 EUR (like GN 7802-1,5-12-GR)
    breaks = provider._calculate_price_breaks(4.58, "EUR")
    assert breaks[1] == (4.58, "EUR")
    # 200 / 4.58 = 43.66 -> 44 pcs (10% discount: 4.12 EUR)
    assert breaks[44] == (4.12, "EUR")
    # 300 / 4.58 = 65.50 -> 66 pcs (20% discount: 3.66 EUR)
    assert breaks[66] == (3.66, "EUR")
    # 400 / 4.58 = 87.33 -> 88 pcs (30% discount: 3.21 EUR)
    assert breaks[88] == (3.21, "EUR")

    # Zero or negative price returns empty
    assert provider._calculate_price_breaks(0.0) == {}


def test_extract_variants_from_priority_table():
    from bs4 import BeautifulSoup

    provider = GanterProvider()

    html = """
    <html>
        <table class="priority-table">
            <tr>
                <th>Modul</th>
                <th>z Zähnezahl GR</th>
                <th>VDB</th>
                <th>b1 Zahnbreite</th>
            </tr>
            <tr>
                <td>Filter</td>
                <td>Filter</td>
                <td>Filter</td>
                <td>Filter</td>
            </tr>
            <tr>
                <td>1.5</td>
                <td>12</td>
                <td>12</td>
                <td>17</td>
            </tr>
            <tr>
                <td>1.5</td>
                <td>14</td>
                <td>-</td>
                <td>17</td>
            </tr>
            <tr>
                <td>1.5</td>
                <td>15</td>
                <td>15</td>
                <td>17</td>
            </tr>
        </table>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    variants = provider._extract_variants_from_page(soup, "GN 7802")
    assert len(variants) == 5
    assert "GN 7802-1,5-12-GR" in variants
    assert "GN 7802-1,5-12-VDB" in variants
    assert "GN 7802-1,5-14-GR" in variants
    assert "GN 7802-1,5-14-VDB" not in variants
    assert "GN 7802-1,5-15-GR" in variants
    assert "GN 7802-1,5-15-VDB" in variants


def test_clean_sku_and_build_product_link():
    provider = GanterProvider()

    # Overly long SKU or pasted page text extracts clean norm
    long_pasted_text = (
        "VD\nNormblatt GN 7802\nDiese Seite drucken\nAllgemeine Hinweise zu Zahnrädern\n"
        + "Stirnzahnräder GN 7802 aus Kunststoff bringen werkstoffbedingt... " * 10
    )
    cleaned = provider._clean_sku(long_pasted_text)
    assert cleaned == "GN 7802"

    # Standard clean
    assert provider._clean_sku("  GN 7802-1,5-12-GR  ") == "GN 7802-1,5-12-GR"

    # Build product link: keeps anchor if <= 250 chars
    base_url = "https://www.ganternorm.com/de/produkte/gn7802"
    link = provider._build_product_link(base_url, "GN 7802-1,5-12-GR")
    assert link == "https://www.ganternorm.com/de/produkte/gn7802#GN 7802-1,5-12-GR"
    assert len(link) <= 250

    # Build product link: drops anchor if > 250 chars
    sku_val = "GN 7802-1,5-12-GR"
    long_base_url = "https://www.ganternorm.com/de/produkte/" + "x" * 210
    assert len(long_base_url) + len(sku_val) + 1 > 250
    long_link = provider._build_product_link(long_base_url, sku_val)
    assert long_link == long_base_url[:250]
    assert len(long_link) <= 250
    assert "#" not in long_link

    # 9124-char input
    huge_sku = "GN 7802-" + "a" * 9100
    huge_link = provider._build_product_link(base_url, huge_sku)
    assert len(huge_link) <= 250



