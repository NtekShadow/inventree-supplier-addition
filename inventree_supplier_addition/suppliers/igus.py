"""igus supplier provider implementation (igus.de webshop)."""

import logging
import re
from typing import Any
from urllib.parse import quote

import requests

from ..models import SupplierProduct

logger = logging.getLogger("inventree")

# Unit identifiers used by the igus catalog service mapped to display symbols
UNIT_SYMBOLS = {
    "MILLIMETER": "mm",
    "CENTIMETER": "cm",
    "METER": "m",
    "INCH": "in",
    "GRAM": "g",
    "KILOGRAM": "kg",
    "NEWTON": "N",
    "KILONEWTON": "kN",
    "NEWTON_METER": "Nm",
    "MEGAPASCAL": "MPa",
    "VOLT": "V",
    "AMPERE": "A",
    "WATT": "W",
    "CELSIUS": "°C",
    "DEGREE": "°",
    "PERCENT": "%",
    "METER_PER_SECOND": "m/s",
    "METER_PER_SQUARE_SECOND": "m/s²",
    "KILOGRAM_PER_KILOMETER": "kg/km",
    "KILOGRAM_PER_METER": "kg/m",
    "BEND_FACTOR": "x d",
}


class IgusProvider:
    """Provider for searching and importing products from the igus webshop (igus.de)."""

    slug = "igus"
    name = "igus"

    def __init__(
        self,
        base_url: str = "https://www.igus.de",
        search_api_url: str = "https://api.igus.com/search",
        locale: str = "de-DE",
        country: str = "DE",
        currency: str = "EUR",
    ):
        self.base_url = base_url.rstrip("/")
        self.search_api_url = search_api_url.rstrip("/")
        self.locale = locale
        self.country = country
        self.currency = currency
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, */*",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
        })

    def _product_link(self, sku: str) -> str:
        """Return the canonical igus article link, which redirects to the product page."""
        return f"{self.base_url}/articlerouter/{quote(sku, safe='.-_')}"

    @staticmethod
    def _image_url(uri: str, size: int = 600) -> str:
        """Normalize protocol-relative widen.net URIs and request a larger rendition."""
        if not uri:
            return ""
        url = f"https:{uri}" if uri.startswith("//") else uri
        url = re.sub(r"([?&])w=\d+", rf"\g<1>w={size}", url)
        return re.sub(r"([?&])h=\d+", rf"\g<1>h={size}", url)

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags and collapse whitespace."""
        text = re.sub(r"<sup>(.*?)</sup>", r"^\1", str(text))
        text = re.sub(r"<[^>]+>", " ", text).replace("&nbsp;", " ")
        return " ".join(text.split()).strip()

    @staticmethod
    def _attr_value(attributes: dict[str, Any], key: str) -> Any:
        """Return the raw value of a catalog attribute (attributes are {label, value} dicts)."""
        attr = attributes.get(key)
        if isinstance(attr, dict):
            return attr.get("value")
        return attr

    @staticmethod
    def _parse_price_text(text: str) -> float | None:
        """Parse a localized price text like '8,62 EUR/Stk.' into a float."""
        m = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)", str(text))
        if not m:
            return None
        try:
            return float(m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            return None

    def _format_value(self, value: Any) -> str:
        """Format a technical attribute value for InvenTree parameters."""
        if isinstance(value, dict) and "amount" in value:
            amount = value.get("amount")
            if amount is None:
                return ""
            if isinstance(amount, float) and amount.is_integer():
                amount = int(amount)
            unit_key = str(value.get("unit") or "")
            unit = UNIT_SYMBOLS.get(unit_key, unit_key.lower().replace("_", " "))
            return f"{amount} {unit}".strip()
        if isinstance(value, list):
            return ", ".join(self._format_value(v) for v in value if v not in (None, ""))
        if isinstance(value, bool):
            return ""
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            text = self._strip_html(value)
            # Skip unresolved enum keys like 'nominal_volt_11'
            if re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)+", text):
                return ""
            return text
        return ""

    def _fetch_list_prices(self, skus: list[str]) -> dict[str, float]:
        """Fetch the single-unit price for multiple SKUs in one request (used for search results)."""
        if not skus:
            return {}
        try:
            response = self.session.post(
                f"{self.base_url}/search/api/session/prices",
                params={"locale": self.locale},
                json={"skus": skus},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("igus price lookup failed: %s", exc)
            return {}

        prices: dict[str, float] = {}
        if not isinstance(data, dict):
            return prices
        for sku, info in data.items():
            for scale in (info or {}).get("priceScales") or []:
                price = self._parse_price_text(scale.get("priceText", ""))
                if price is not None and price > 0:
                    prices[sku] = price
                    break
        return prices

    def search(self, term: str) -> list[SupplierProduct]:
        """Search articles on igus.de via the unified search API."""
        term = term.strip()
        if not term:
            return []

        response = self.session.get(
            f"{self.search_api_url}/unified-search/{self.locale}/{quote(term, safe='')}",
            params={
                "shopFrom": 0,
                "shopSize": 25,
                "infoFrom": 0,
                "infoSize": 0,
                "mediaFrom": 0,
                "mediaSize": 0,
                "includeCategoryTeasers": "false",
            },
            timeout=15,
        )
        response.raise_for_status()

        articles = (response.json().get("articles") or {}).get("data") or []
        articles = [a for a in articles if a.get("sku") and not a.get("isArticleDiscontinued")]

        # Prefer an exact SKU match at the top of the list
        norm_term = re.sub(r"[\s.\-_]", "", term).lower()
        articles.sort(key=lambda a: re.sub(r"[\s.\-_]", "", a["sku"]).lower() != norm_term)

        prices = self._fetch_list_prices([a["sku"] for a in articles])

        products = []
        for article in articles:
            sku = article["sku"]
            price = prices.get(sku, 0.0)
            title = self._strip_html(article.get("title") or sku)
            products.append(
                SupplierProduct(
                    sku=sku,
                    name=title,
                    description=f"{title} - {sku}",
                    price={1: (price, self.currency)} if price > 0 else {},
                    link=self._product_link(sku),
                    image_url=article.get("imageUrl") or "",
                    brand="igus",
                    supplier_name=self.name,
                    supplier_slug=self.slug,
                )
            )
        return products

    def _fetch_current_product(self, sku: str) -> dict[str, Any]:
        """Fetch full product data (prices, attributes, assets) from the igus catalog service."""
        response = self.session.post(
            f"{self.base_url}/_catalog/api/current-product",
            json={
                "productId": sku,
                "country": self.country,
                "currency": self.currency,
                "deliveryTimeLocale": self.locale,
                "locale": self.locale,
            },
            timeout=15,
        )
        if response.status_code in (404, 500):
            raise LookupError(sku)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get("id") != sku:
            raise LookupError(sku)
        return data

    def _fetch_technical_parameters(self, sku: str, reference_id: str) -> dict[str, str]:
        """Fetch the curated technical data of a product (chemical resistances are skipped)."""
        if not reference_id:
            return {}
        try:
            response = self.session.post(
                f"{self.base_url}/_catalog/api/product-technical-data",
                json={
                    "productId": sku,
                    "technicalDataReferenceEntityId": reference_id,
                    "withTechnicalDrawings": False,
                    "locale": self.locale,
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("igus technical data lookup failed for %s: %s", sku, exc)
            return {}

        chemical = set(data.get("chemicalAttributeNames") or [])
        params: dict[str, str] = {}
        for key, attr in (data.get("technicalProductAttributes") or {}).items():
            if key in chemical or not isinstance(attr, dict):
                continue
            label = self._strip_html(attr.get("label") or key)
            value = self._format_value(attr.get("value"))
            if label and value and label not in params:
                params[label] = value[:250]
        return params

    def _parse_price_breaks(self, prices: list[dict[str, Any]]) -> dict[int, tuple[float, str]]:
        """Convert igus price scales into InvenTree price breaks (prices < 0 mean 'on request')."""
        breaks: dict[int, tuple[float, str]] = {}
        for entry in prices or []:
            try:
                price = float(entry.get("price", -1))
                quantity = max(1, int(entry.get("discount_threshold") or 1))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            multiplier = entry.get("unit_multiplier") or 1
            try:
                price = price / float(multiplier)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            currency = entry.get("currency_code") or self.currency
            if quantity not in breaks or price < breaks[quantity][0]:
                breaks[quantity] = (round(price, 4), currency)

        # Drop breaks that do not lower the price compared to a smaller quantity
        result: dict[int, tuple[float, str]] = {}
        for quantity, value in sorted(breaks.items()):
            if result and value[0] >= list(result.values())[-1][0]:
                continue
            result[quantity] = value
        return result

    def get_product(self, sku: str) -> SupplierProduct:
        """Fetch a specific product by its igus article number."""
        sku = sku.strip()
        data = self._fetch_current_product(sku)
        attributes = data.get("attributes") or {}

        series = self._strip_html(self._attr_value(attributes, "series_description") or "")
        article_desc = self._strip_html(
            self._attr_value(attributes, "article_description_text_area") or ""
        )
        name = series or article_desc or sku
        if not article_desc or article_desc.lower() in series.lower():
            description = name
        elif not series or series.lower() in article_desc.lower():
            description = article_desc
        else:
            description = f"{series}, {article_desc}"

        image_uri = ""
        assets = {a.get("key"): a for a in data.get("assets") or [] if isinstance(a, dict)}
        for key in ("attr_image_01", "product_teaser_image"):
            sources = (assets.get(key) or {}).get("sources") or []
            if sources and sources[0].get("uri"):
                image_uri = sources[0]["uri"]
                break

        reference_id = self._attr_value(attributes, "webshop_technical_data_attributes") or ""
        parameters: dict[str, str] = {}
        if series:
            parameters["Serie"] = series
        parameters.update(self._fetch_technical_parameters(sku, str(reference_id)))

        sales_unit = self._attr_value(attributes, "sales_unit")
        if sales_unit:
            parameters["Verkaufseinheit"] = str(sales_unit)
        weight = self._attr_value(attributes, "shipping_weight")
        if weight:
            parameters["Versandgewicht"] = f"{weight} kg"
        delivery = [d.get("label") for d in data.get("delivery_times") or [] if d.get("label")]
        if delivery:
            parameters["Lieferzeit"] = delivery[0]

        return SupplierProduct(
            sku=sku,
            name=name,
            description=description,
            price=self._parse_price_breaks(data.get("prices") or []),
            link=self._product_link(sku),
            image_url=self._image_url(image_uri),
            brand="igus",
            parameters=parameters,
            supplier_name=self.name,
            supplier_slug=self.slug,
        )
