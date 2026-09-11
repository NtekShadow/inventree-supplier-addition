"""Landefeld supplier provider implementation."""

import json
from typing import Any

import requests

from ..models import SupplierProduct


class LandefeldProvider:
    """Provider for searching and importing products from Landefeld."""

    slug = "landefeld"
    name = "Landefeld"

    def __init__(self, base_url: str = "https://www.landefeld.de"):
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _parse_server_object(data_string: Any) -> Any:
        if not isinstance(data_string, str):
            return data_string

        start_index = data_string.find("{")
        end_index = data_string.rfind("}")
        if start_index == -1 or end_index == -1:
            return data_string

        try:
            return json.loads(data_string[start_index : end_index + 1])
        except json.JSONDecodeError:
            return data_string

    def search(self, term: str) -> list[SupplierProduct]:
        """Search products on Landefeld via AJAX endpoint."""
        response = requests.post(
            f"{self.base_url}/cgi/main.cgi/ajax",
            headers={
                "accept": "*/*",
                "accept-language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "user-agent": "Mozilla/5.0",
                "content-type": "application/x-www-form-urlencoded",
                "origin": self.base_url,
                "referer": (
                    f"{self.base_url}/cgi/main.cgi?DISPLAY=suche&"
                    f"filter_suche_suchstring={term.replace('/', '%2F')}"
                ),
            },
            data={
                "DISPLAY": "artikelnummernsuche",
                "param_1": "0",
                "filter_suche_suchstring": term,
                "filter_suche_artikelmenge": "",
            },
            timeout=10,
        )
        response.raise_for_status()

        article_list = response.json().get("payload", {}).get("artikelliste", [])
        products = []
        for item in article_list:
            article = self._parse_server_object(item.get("anzeigeartikel", ""))
            pricing = self._parse_server_object(item.get("preismodul", ""))
            if not isinstance(article, dict):
                continue

            price = 0.0
            displayed_price = pricing.get("Anzeigepreis") if isinstance(pricing, dict) else None
            displayed_price = self._parse_server_object(displayed_price)
            if isinstance(displayed_price, dict):
                price = float(displayed_price.get("Nettopreis", 0.0))

            sku = article.get("ArtikelnummerAngezeigt", "Unbekannt")
            link_path = article.get("SEO_URL_Artikel", "")
            image_path = article.get("HauptbildArtikel", "")
            is_original = article.get("ist_Originalteil") == 1
            products.append(
                SupplierProduct(
                    sku=sku,
                    name=article.get("Bezeichnung", sku),
                    description=article.get("Bezeichnung", "Keine Beschreibung verfügbar."),
                    price={1: (price, "EUR")},
                    link=f"{self.base_url}{link_path}" if link_path else "",
                    image_url=f"{self.base_url}{image_path}" if image_path else "",
                    brand="Festo/Originalteil" if is_original else "Landefeld",
                    parameters={
                        "Verpackungseinheit": str(article.get("VPE", "1.00")),
                        "Einheit": str(article.get("Einheit", "STK")),
                        "Vorteil": str(article.get("Vorteil", "")),
                    },
                    supplier_name=self.name,
                    supplier_slug=self.slug,
                )
            )
        return products

    def get_product(self, sku: str) -> SupplierProduct:
        """Fetch a specific product by SKU."""
        for product in self.search(sku):
            if product.sku == sku:
                return product
        raise LookupError(sku)
