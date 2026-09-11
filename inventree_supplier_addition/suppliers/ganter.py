"""Ganter Norm supplier provider implementation."""

import logging
import re
from collections import Counter
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..models import SupplierProduct

logger = logging.getLogger("inventree")


class GanterProvider:
    """Provider for searching and importing standard parts from Ganter Norm (ganternorm.com)."""

    slug = "ganter"
    name = "Ganter Norm"

    def __init__(
        self,
        base_url: str = "https://www.ganternorm.com",
        api_base_url: str = "https://live-katalog.ganternorm.com",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_base_url = api_base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "relounge-location-country": "de",
        })
        self._cache: dict[str, SupplierProduct] = {}

    def _clean_sku(self, sku: str) -> str:
        """Strip whitespace and normalize SKU."""
        return " ".join(sku.strip().split())

    def _strip_owner(self, sku: str) -> str:
        """Strip leading standard owner prefix (GN, DIN, ISO) for API queries."""
        return re.sub(r"^(?:GN|DIN|ISO)\s*", "", self._clean_sku(sku), flags=re.IGNORECASE)

    def _extract_image_url(self, soup: BeautifulSoup, sku: str) -> str:
        """Extract best matching image URL for the given SKU or variant."""
        imgs: list[str] = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src and "catalog-images" in src:
                imgs.append(src)

        # Check if SKU has color/finish code (e.g. -SW, -OS, -RS, -CR, -SZ, -NI, -RH, -SR)
        color_match = re.search(r"-([A-Z0-9]{2,3})(?:-[A-Z0-9]+)?$", sku)
        if color_match:
            code = color_match.group(1).upper()
            for img_src in imgs:
                if f"-{code}-" in img_src or f"-{code}." in img_src or f"-{code}_" in img_src:
                    clean_url = img_src.split("?")[0].replace("-thumbnail.jpg", ".jpg")
                    return clean_url if clean_url.startswith("http") else urljoin(self.base_url, clean_url)

        # Fallback to itemprop="image"
        item_img = soup.find(attrs={"itemprop": "image"})
        if item_img:
            src = item_img.get("src") or item_img.get("data-src", "")
            if src:
                clean_url = src.split("?")[0].replace("-thumbnail.jpg", ".jpg")
                return clean_url if clean_url.startswith("http") else urljoin(self.base_url, clean_url)

        # Fallback to first catalog image
        if imgs:
            clean_url = imgs[0].split("?")[0].replace("-thumbnail.jpg", ".jpg")
            return clean_url if clean_url.startswith("http") else urljoin(self.base_url, clean_url)

        return ""

    def _fetch_price_and_params(self, sku: str) -> tuple[float, str, dict[str, str]]:
        """Fetch exact net price and technical parameters via artikelpreisinfo API."""
        sku_no_owner = self._strip_owner(sku)
        price_val = 0.0
        currency = "EUR"
        parameters: dict[str, str] = {}

        params = {
            "artikelNrOhneEigentuemer": sku_no_owner,
            "identityCulture": "de",
            "deliveryCountry": "de",
            "menge": 1,
            "waehrungId": 0,
            "salesLocationId": 1,
            "lagerbestandAusblenden": False,
        }

        try:
            r = self.session.get(
                f"{self.api_base_url}/de/api/artikelpreisinfo",
                params=params,
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                p_html = data.get("preisInfo") or ""
                if p_html:
                    p_soup = BeautifulSoup(p_html, "html.parser")
                    net_tag = p_soup.find(id="net-price-id")
                    if net_tag:
                        raw = (
                            net_tag.get_text(strip=True)
                            .replace("€", "")
                            .strip()
                            .replace(".", "")
                            .replace(",", ".")
                        )
                        price_val = float(raw)

                z_html = data.get("zusatzInfo") or ""
                if z_html:
                    z_soup = BeautifulSoup(z_html, "html.parser")
                    for d in z_soup.find_all("details"):
                        summary = d.find("summary")
                        if not summary:
                            continue
                        stext = summary.get_text(strip=True)
                        if "Gewicht:" in stext:
                            parameters["Gewicht"] = stext.replace("Gewicht:", "").strip()
                        elif "RoHS:" in stext:
                            parameters["RoHS"] = stext.replace("RoHS:", "").strip()
                        elif "Zolltarifnummer" in stext:
                            unit = d.find(class_="toggle__unit")
                            if unit:
                                parameters["Zolltarifnummer"] = unit.get_text(strip=True)

                l_html = data.get("lagerverfuegbarkeitInfo") or ""
                if l_html:
                    l_soup = BeautifulSoup(l_html, "html.parser")
                    avail = [
                        li.get_text(strip=True)
                        for li in l_soup.find_all("li")
                        if li.get_text(strip=True)
                    ]
                    if avail:
                        parameters["Verfügbarkeit"] = "; ".join(avail)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to fetch Ganter price info for %s: %s", sku, exc)

        return price_val, currency, parameters

    def _fetch_product_from_page(self, url: str, sku: str) -> SupplierProduct:
        """Fetch and parse a product detail page from Ganter Norm."""
        clean_sku = self._clean_sku(sku)
        full_url = url if url.startswith("http") else urljoin(self.base_url, url)

        # Separate URL path and fragment (e.g. #l1=c(30)...)
        request_url = full_url.split("#")[0]
        response = self.session.get(request_url, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Name
        title_el = soup.find("h1", itemprop="name") or soup.find("h1")
        name = title_el.get_text(" ", strip=True) if title_el else clean_sku

        # Description
        desc_el = soup.find(itemprop="description")
        description = desc_el.get_text(" ", strip=True) if desc_el else ""

        # Image
        image_url = self._extract_image_url(soup, clean_sku)

        # Fallback price from microdata
        price_val = 0.0
        currency = "EUR"
        p_meta = soup.find(attrs={"itemprop": "price"})
        if p_meta and p_meta.get("content"):
            try:
                price_val = float(p_meta["content"])
            except ValueError:
                pass

        c_meta = soup.find(attrs={"itemprop": "priceCurrency"})
        if c_meta and c_meta.get("content"):
            currency = c_meta["content"]

        parameters: dict[str, str] = {}

        # If clean_sku is an article code, extract exact price and params
        exact_price, exact_cur, api_params = self._fetch_price_and_params(clean_sku)
        if exact_price > 0:
            price_val = exact_price
            currency = exact_cur
        parameters.update(api_params)

        # Detect norm family code
        norm_match = re.match(r"^((?:GN|DIN|ISO)\s*[\w.]+)", clean_sku, flags=re.IGNORECASE)
        if norm_match:
            parameters.setdefault("Norm", norm_match.group(1))

        price_dict: dict[int, tuple[float, str]] = {}
        if price_val > 0:
            price_dict[1] = (price_val, currency)

        product = SupplierProduct(
            sku=clean_sku,
            name=name,
            description=description,
            price=price_dict,
            link=full_url,
            image_url=image_url,
            brand="Ganter Norm",
            parameters=parameters,
            supplier_name=self.name,
            supplier_slug=self.slug,
        )

        self._cache[clean_sku] = product
        return product

    def search(self, term: str) -> list[SupplierProduct]:
        """Search products on Ganter Norm via Quickfinder API or schnell-suche."""
        clean_term = self._clean_sku(term)
        if not clean_term:
            return []

        # Return cached result if exact match is already known
        if clean_term in self._cache:
            return [self._cache[clean_term]]

        # 1. Check if term is an exact SKU via schnell-suche redirect
        try:
            r = self.session.get(
                f"{self.base_url}/de/produkte/schnell-suche",
                params={"q": clean_term},
                allow_redirects=False,
                timeout=10,
            )
            if r.status_code in (301, 302, 303, 307, 308):
                redirect_loc = r.headers.get("Location")
                if redirect_loc:
                    product = self._fetch_product_from_page(redirect_loc, sku=clean_term)
                    self._cache[clean_term] = product
                    return [product]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ganter schnell-suche redirect check failed: %s", exc)

        # 2. Query Quickfinder API
        hits: list[dict[str, Any]] = []
        try:
            r_qf = self.session.get(
                f"{self.api_base_url}/de/api/quickfinder",
                params={"q": clean_term},
                timeout=8,
            )
            if r_qf.status_code == 200:
                hits = r_qf.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ganter Quickfinder query failed: %s", exc)

        if hits:
            # Check how often each norm code appears to disambiguate identical codes
            norm_codes: list[str] = []
            parsed_items: list[tuple[str, str, dict[str, Any]]] = []
            for item in hits:
                norm_text = item.get("norm", "").strip()
                m = re.match(r"^((?:GN|DIN|ISO)\s*[\w.]+)\s*(.*)$", norm_text, flags=re.IGNORECASE)
                if m:
                    code, desc = m.group(1), m.group(2)
                else:
                    code, desc = norm_text, norm_text
                norm_codes.append(code)
                parsed_items.append((code, desc, item))

            counts = Counter(norm_codes)
            products: list[SupplierProduct] = []

            for code, desc, item in parsed_items[:30]:
                # Disambiguate SKU if multiple hits share the same norm (e.g. Innengewinde vs Außengewinde)
                if counts[code] > 1 and desc:
                    parts = [p.strip() for p in desc.split(",") if p.strip()]
                    feature = parts[-1] if parts else desc
                    feature = feature.rstrip(".")
                    item_sku = f"{code} ({feature})"
                else:
                    item_sku = code

                # Ensure item_sku is unique within results
                base_candidate = item_sku
                counter_idx = 1
                while any(p.sku == item_sku for p in products):
                    item_sku = f"{base_candidate} #{counter_idx}"
                    counter_idx += 1

                url_path = item.get("url", "")
                link = urljoin(self.base_url, url_path) if url_path else ""
                thumb = item.get("urlHauptbildThumbnail", "")
                image_url = thumb.split("?")[0].replace("-thumbnail.jpg", ".jpg") if thumb else ""

                prod = SupplierProduct(
                    sku=item_sku,
                    name=item.get("norm", item_sku),
                    description=desc,
                    price={},
                    link=link,
                    image_url=image_url,
                    brand="Ganter Norm",
                    parameters={"Norm": code},
                    supplier_name=self.name,
                    supplier_slug=self.slug,
                )
                self._cache[item_sku] = prod
                self._cache.setdefault(code, prod)
                products.append(prod)

            return products

        # 3. Handle partial variant search (e.g. "GN 300-30" or "DIN 508-14")
        norm_split = re.match(r"^((?:GN|DIN|ISO)\s*[\w.]+)[-\s]+(.*)$", clean_term, flags=re.IGNORECASE)
        if norm_split:
            base_norm = norm_split.group(1)
            try:
                r_base = self.session.get(
                    f"{self.api_base_url}/de/api/quickfinder",
                    params={"q": base_norm},
                    timeout=8,
                )
                if r_base.status_code == 200:
                    base_hits = r_base.json()
                    if base_hits:
                        first_page_url = base_hits[0].get("url")
                        if first_page_url:
                            resp = self.session.get(
                                urljoin(self.base_url, first_page_url), timeout=10
                            )
                            if resp.status_code == 200:
                                soup = BeautifulSoup(resp.text, "html.parser")
                                spans = soup.find_all(
                                    "span", style=lambda s: s and "display:none" in s
                                )
                                norm_clean_query = clean_term.replace(" ", "").lower()
                                variant_products: list[SupplierProduct] = []

                                title_el = soup.find("h1", itemprop="name") or soup.find("h1")
                                title = title_el.get_text(" ", strip=True) if title_el else base_norm
                                desc_el = soup.find(itemprop="description")
                                desc = desc_el.get_text(" ", strip=True) if desc_el else ""

                                for span in spans:
                                    var_sku = span.get_text(strip=True)
                                    if norm_clean_query in var_sku.replace(" ", "").lower():
                                        v_prod = SupplierProduct(
                                            sku=var_sku,
                                            name=f"{var_sku} {title}",
                                            description=desc,
                                            price={},
                                            link=f"{urljoin(self.base_url, first_page_url)}#{var_sku}",
                                            image_url=self._extract_image_url(soup, var_sku),
                                            brand="Ganter Norm",
                                            parameters={"Norm": base_norm},
                                            supplier_name=self.name,
                                            supplier_slug=self.slug,
                                        )
                                        self._cache[var_sku] = v_prod
                                        variant_products.append(v_prod)
                                        if len(variant_products) >= 25:
                                            break

                                if variant_products:
                                    return variant_products
            except Exception as exc:  # noqa: BLE001
                logger.debug("Ganter variant search failed for %s: %s", clean_term, exc)

        return []

    def get_product(self, sku: str) -> SupplierProduct:
        """Fetch a specific product by its SKU or norm identifier."""
        clean_sku = self._clean_sku(sku)
        if not clean_sku:
            raise LookupError(sku)

        # 1. Check cache for complete product
        if clean_sku in self._cache:
            prod = self._cache[clean_sku]
            if prod.price and any(p[0] > 0 for p in prod.price.values()) and prod.parameters.get("Gewicht"):
                return prod
            # If cached product has a link, fetch full details from its page
            if prod.link:
                try:
                    full_prod = self._fetch_product_from_page(prod.link, sku=prod.sku)
                    self._cache[clean_sku] = full_prod
                    return full_prod
                except Exception:  # noqa: BLE001
                    return prod

        # 2. Try schnell-suche redirect
        try:
            r = self.session.get(
                f"{self.base_url}/de/produkte/schnell-suche",
                params={"q": clean_sku},
                allow_redirects=False,
                timeout=10,
            )
            if r.status_code in (301, 302, 303, 307, 308):
                redirect_loc = r.headers.get("Location")
                if redirect_loc:
                    return self._fetch_product_from_page(redirect_loc, sku=clean_sku)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ganter get_product schnell-suche redirect check failed: %s", exc)

        # 3. Try Quickfinder lookup
        try:
            r_qf = self.session.get(
                f"{self.api_base_url}/de/api/quickfinder",
                params={"q": clean_sku},
                timeout=8,
            )
            if r_qf.status_code == 200:
                hits = r_qf.json()
                if hits and hits[0].get("url"):
                    return self._fetch_product_from_page(hits[0]["url"], sku=clean_sku)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ganter get_product Quickfinder lookup failed: %s", exc)

        # 4. Search and return matching item
        search_results = self.search(clean_sku)
        for prod in search_results:
            if prod.sku.lower() == clean_sku.lower():
                # Enrich if page link exists
                if prod.link:
                    try:
                        return self._fetch_product_from_page(prod.link, sku=prod.sku)
                    except Exception:  # noqa: BLE001
                        return prod
                return prod

        if search_results:
            first = search_results[0]
            if first.link:
                try:
                    return self._fetch_product_from_page(first.link, sku=first.sku)
                except Exception:  # noqa: BLE001
                    return first
            return first

        raise LookupError(sku)
