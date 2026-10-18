"""norelem supplier provider implementation (norelem.de webshop)."""

import logging
import re
import ssl
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, PreformattedString
from requests.adapters import HTTPAdapter

from ..models import SupplierProduct

logger = logging.getLogger("inventree")

# Product groups ("Artikelgruppen") are addressed as agid.<number>, articles by their order number
GROUP_RE = re.compile(r"/p/(agid\.\d+)")
ARTICLE_RE = re.compile(r"/p/([^/?#]+)$")

# Maximum image size accepted by download_image
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class _ModernTLSAdapter(HTTPAdapter):
    """HTTPS adapter offering only ECDHE cipher suites.

    The norelem CDN (Fastly) rejects the TLS handshake fingerprint of urllib3's default
    cipher list with HTTP 406; a reduced, modern cipher list is accepted.
    """

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


class NorelemProvider:
    """Provider for searching and importing products from the norelem webshop (norelem.de)."""

    slug = "norelem"
    name = "norelem"

    # Number of product groups from a search result list that are expanded into their articles
    MAX_SEARCH_GROUPS = 4
    MAX_SEARCH_RESULTS = 50

    def __init__(
        self,
        base_url: str = "https://www.norelem.de",
        language: str = "de",
        currency: str = "EUR",
    ):
        self.base_url = base_url.rstrip("/")
        self.language = language
        self.currency = currency
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self.session.mount("https://", _ModernTLSAdapter())

    @property
    def shop_url(self) -> str:
        return f"{self.base_url}/{self.language}"

    def _product_link(self, sku: str) -> str:
        """Return the short article link, which redirects to the full product page."""
        return f"{self.shop_url}/p/{quote(sku, safe='-_.')}"

    def _absolute(self, url: str) -> str:
        return urljoin(f"{self.base_url}/", url) if url else ""

    @staticmethod
    def _clean(text: Any) -> str:
        """Collapse whitespace (variant names contain CR/LF line breaks)."""
        return " ".join(str(text or "").split()).strip()

    @classmethod
    def _text(cls, element) -> str:
        """Return the visible text of an element, including text inside <template> tags.

        BeautifulSoup's get_text() skips template contents, but the shop renders its product
        details (name, features, bullet points) as Vue templates.
        """
        if element is None:
            return ""
        return cls._clean(" ".join(
            str(node)
            for node in element.descendants
            if isinstance(node, NavigableString) and not isinstance(node, PreformattedString)
        ))

    def _parse_price_breaks(
        self, scale_prices: list[dict[str, Any]], fallback: Any = None
    ) -> dict[int, tuple[float, str]]:
        """Convert norelem scale prices (or a single price) into InvenTree price breaks."""
        breaks: dict[int, tuple[float, str]] = {}
        for scale in scale_prices or []:
            if not isinstance(scale, dict):
                continue
            price = scale.get("netPrice", scale)
            if isinstance(price, dict) and isinstance(price.get("price"), dict):
                price = price["price"]
            try:
                value = float(price.get("value"))
                quantity = max(1, int(scale.get("minQuantity") or 1))
            except (AttributeError, TypeError, ValueError):
                continue
            if value > 0 and (quantity not in breaks or value < breaks[quantity][0]):
                breaks[quantity] = (round(value, 4), price.get("currencyIso") or self.currency)

        if not breaks and isinstance(fallback, dict):
            try:
                value = float(fallback.get("value"))
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                breaks[1] = (round(value, 4), fallback.get("currencyIso") or self.currency)

        return dict(sorted(breaks.items()))

    @staticmethod
    def _parse_price_text(text: str) -> float | None:
        """Parse a localized price like '1.234,50 €' into a float."""
        m = re.search(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?", str(text or ""))
        if not m:
            return None
        try:
            return float(m.group(0).replace(".", "").replace(",", "."))
        except ValueError:
            return None

    def _parse_page_prices(self, details) -> dict[int, tuple[float, str]]:
        """Read the server-rendered scale prices of an article detail page."""
        breaks: dict[int, tuple[float, str]] = {}
        for button in details.find_all("scale-price-button"):
            price = self._parse_price_text(button.get("price"))
            try:
                quantity = max(1, int(str(button.get("amount") or "1").strip()))
            except ValueError:
                continue
            if price and price > 0:
                breaks[quantity] = (round(price, 4), self.currency)
        return dict(sorted(breaks.items()))

    def _fetch_price_breaks(self, sku: str) -> dict[int, tuple[float, str]]:
        """Fetch the public net price scales of an article."""
        try:
            response = self.session.get(
                f"{self.shop_url}/xhr/price",
                params={"articleCode": sku, "quantity": 1},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("norelem price lookup failed for %s: %s", sku, exc)
            return {}

        data = payload.get("data") if isinstance(payload, dict) else None
        if not payload.get("success") or not isinstance(data, dict) or data.get("enquiryOnly"):
            return {}
        fallback = ((data.get("price") or {}).get("netPrice") or {}).get("price")
        return self._parse_price_breaks(data.get("scalePrices") or [], fallback)

    def _fetch_group_variants(self, group_id: str, group_name: str = "") -> list[SupplierProduct]:
        """Fetch all articles of a product group from the variant table endpoint."""
        try:
            response = self.session.get(
                f"{self.shop_url}/p/{group_id}/facets_and_results",
                params={
                    "sort": "tablePimSort",
                    "page": 0,
                    "reverse": "false",
                    "pageSize": self.MAX_SEARCH_RESULTS,
                    "pagePart": 0,
                    "q": "",
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("norelem variant lookup failed for %s: %s", group_id, exc)
            return []

        # Variant attributes are named attr_<facet code>
        attr_names = {
            f"attr_{facet.get('code')}": self._clean(facet.get("name"))
            for facet in data.get("facets") or []
            if isinstance(facet, dict) and facet.get("code") and facet.get("name")
        }

        products = []
        for item in data.get("products") or []:
            sku = self._clean(item.get("code"))
            if not sku:
                continue
            variant_name = self._clean(item.get("name"))
            parameters = {
                label: self._clean(item[key])[:250]
                for key, label in attr_names.items()
                if self._clean(item.get(key))
            }
            if item.get("familyNumber"):
                parameters["Artikelfamilie"] = str(item["familyNumber"])

            price = {}
            if not item.get("enquiryOnly"):
                price = self._parse_price_breaks(item.get("scalePrices") or [], item.get("price"))

            products.append(
                SupplierProduct(
                    sku=sku,
                    name=(group_name or variant_name or sku)[:100],
                    description=(variant_name or group_name or sku)[:250],
                    price=price,
                    link=self._product_link(sku),
                    image_url=self._absolute(item.get("imageUrl") or ""),
                    brand="norelem",
                    parameters=parameters,
                    supplier_name=self.name,
                    supplier_slug=self.slug,
                )
            )
        return products

    def _group_name(self, soup: BeautifulSoup) -> str:
        family = soup.find("product-family-details")
        if family and family.get("product-name"):
            return self._clean(family.get("product-name"))
        return self._text(soup.select_one("h1"))

    def search(self, term: str) -> list[SupplierProduct]:
        """Search norelem.de; exact article numbers redirect to the article, families to a group."""
        term = term.strip()
        if not term:
            return []

        response = self.session.get(f"{self.shop_url}/search", params={"text": term}, timeout=20)
        if response.status_code == 404:
            return []
        response.raise_for_status()

        path = urlparse(response.url).path
        group_match = GROUP_RE.search(path)
        if group_match:
            soup = BeautifulSoup(response.text, "html.parser")
            return self._fetch_group_variants(group_match.group(1), self._group_name(soup))

        article_match = ARTICLE_RE.search(path)
        if article_match:
            sku = requests.utils.unquote(article_match.group(1))
            try:
                return [self._product_from_page(sku, response.text)]
            except LookupError:
                return []

        # Result list of product groups: expand the best matching groups into their articles
        soup = BeautifulSoup(response.text, "html.parser")
        groups: list[tuple[str, str]] = []
        for tile in soup.find_all("product-tile"):
            match = GROUP_RE.search(tile.get("product-url") or "")
            if match and match.group(1) not in (g for g, _ in groups):
                groups.append((match.group(1), self._clean(tile.get("product-name"))))
            if len(groups) >= self.MAX_SEARCH_GROUPS:
                break
        if not groups:
            return []

        with ThreadPoolExecutor(max_workers=len(groups)) as executor:
            results = executor.map(lambda g: self._fetch_group_variants(*g), groups)
        products = [p for group_products in results for p in group_products]

        # Articles whose number starts with the search term come first
        norm_term = re.sub(r"[\s\-_.]", "", term).lower()
        products.sort(key=lambda p: not re.sub(r"[\s\-_.]", "", p.sku).lower().startswith(norm_term))
        return products[: self.MAX_SEARCH_RESULTS]

    def _parse_texts_table(self, table) -> dict[str, str]:
        """Parse a category-texts table (headline/value cells) into a dict."""
        values: dict[str, str] = {}
        if table is None:
            return values
        for cell in table.select(".category-texts__cell"):
            label_el = cell.select_one(".category-texts__cell-headline")
            value_el = cell.select_one(".category-texts__cell-text")
            if not label_el or not value_el:
                continue
            label = self._text(label_el).lstrip("~ ").strip()
            value = self._text(value_el)
            if label and value and label not in values:
                values[label] = value[:250]
        return values

    def _product_from_page(self, sku: str, html: str) -> SupplierProduct:
        """Build a product from an article detail page."""
        soup = BeautifulSoup(html, "html.parser")
        details = soup.find("product-details")
        page_sku = self._clean(details.get("product-number")) if details else ""
        if not page_sku or page_sku.lower() != sku.lower():
            raise LookupError(sku)
        sku = page_sku

        title_el = details.select_one(".product-details__name")
        features_el = details.select_one(".product-details__features")
        title = self._text(title_el)
        features = self._text(features_el)
        name = " ".join(part for part in (title, features) if part) or sku

        # Article specific values (dimensions, material, compliance) followed by family texts
        tables = soup.select(".details-tab__wrapper .category-texts__table")
        article_table = next((t for t in tables if t.select_one(".category-texts__cell.-product")), None)
        parameters = self._parse_texts_table(article_table)
        for table in tables:
            if table is article_table:
                continue
            for label, value in self._parse_texts_table(table).items():
                parameters.setdefault(label, value)
        parameters.pop("Benennung", None)
        if details.get("family-number"):
            parameters["Artikelfamilie"] = self._clean(details.get("family-number"))

        # Short dimension notation like the shop uses for variant names, e.g. "D=32 H=20"
        dimensions = [
            f"{label.split('=', 1)[0]}={value}"
            for label, value in parameters.items()
            if "=" in label and len(label.split("=", 1)[0]) <= 3
        ]
        description = name
        if dimensions:
            description = f"{name}, {' '.join(dimensions)}"

        image_url = ""
        gallery = soup.find("product-image-gallery")
        image = None
        if gallery:
            slider = gallery.find("template", attrs={"#slider-main": True}) or gallery
            image = slider.find("img")
        if image is None:
            drawing = soup.find("product-drawing")
            image_url = drawing.get("url", "") if drawing else ""
        else:
            image_url = image.get("src") or image.get("data-src") or ""

        # The price service is backed by SAP and occasionally fails, so it is only a fallback
        price = self._parse_page_prices(details) or self._fetch_price_breaks(sku)

        return SupplierProduct(
            sku=sku[:100],
            name=name[:100],
            description=description[:250],
            price=price,
            link=self._product_link(sku),
            image_url=self._absolute(image_url),
            brand="norelem",
            parameters=parameters,
            supplier_name=self.name,
            supplier_slug=self.slug,
        )

    def get_product(self, sku: str) -> SupplierProduct:
        """Fetch a specific product by its norelem article number."""
        sku = sku.strip()
        if not sku or GROUP_RE.search(f"/p/{sku}"):
            raise LookupError(sku)

        response = self.session.get(self._product_link(sku), timeout=20)
        if response.status_code == 404:
            raise LookupError(sku)
        response.raise_for_status()
        return self._product_from_page(sku, response.text)

    def download_image(self, url: str):
        """Download a product image with the provider session (InvenTree's downloader is blocked)."""
        try:
            from django.core.files.base import ContentFile
        except ImportError:  # pragma: no cover - only available inside InvenTree
            return None, ""

        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("norelem image download failed for %s: %s", url, exc)
            return None, ""

        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/") or len(response.content) > MAX_IMAGE_BYTES:
            logger.warning("norelem image download returned no usable image: %s", url)
            return None, ""
        image_format = content_type.split("/", 1)[1].upper().replace("JPG", "JPEG")
        return ContentFile(response.content), image_format
