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
        self._soup_cache: dict[str, BeautifulSoup] = {}

    def _clean_sku(self, sku: str) -> str:
        """Strip whitespace and normalize SKU."""
        return " ".join(sku.strip().split())

    def _strip_owner(self, sku: str) -> str:
        """Strip leading standard owner prefix (GN, DIN, ISO) for API queries."""
        return re.sub(r"^(?:GN|DIN|ISO)\s*", "", self._clean_sku(sku), flags=re.IGNORECASE)

    def _normalize_token(self, val: str) -> str:
        """Normalize token for case- and whitespace-insensitive comparison."""
        return re.sub(r"[\s,\.]+", "", val).lower()

    def _clean_dim_title(self, title: str) -> str:
        """Clean dimension title by stripping variable symbols and parenthesized notes."""
        t = re.sub(r"\s+", " ", title).strip()
        t_clean = re.sub(r"\s+[a-z]\s*\d*(?:\s*\([^)]*\))?$", "", t, flags=re.IGNORECASE).strip()
        t_clean = re.sub(r"\s*\([^)]*\)$", "", t_clean).strip()
        return t_clean if t_clean else t

    def _parse_config_dimensions(self, soup: BeautifulSoup) -> dict[str, list[str]]:
        """Extract configuration dimensions and their selectable options from the page."""
        dims = soup.find(id="product-dimensions")
        fieldsets = dims.find_all("fieldset") if dims else soup.find_all("fieldset")
        dim_options: dict[str, list[str]] = {}

        for f in fieldsets:
            legend = f.find("legend")
            if not legend:
                continue
            title = self._clean_dim_title(legend.get_text(" ", strip=True))
            if "ausführung" in title.lower():
                continue

            labels: list[str] = []
            for lab in f.find_all("label"):
                txt = re.sub(r"\s+", " ", lab.get_text(" ", strip=True)).strip()
                if txt and txt not in labels:
                    labels.append(txt)

            if labels:
                if title in dim_options:
                    for lab in labels:
                        if lab not in dim_options[title]:
                            dim_options[title].append(lab)
                else:
                    dim_options[title] = labels

        return dim_options

    def _split_sku_tokens(self, rest: str) -> list[str]:
        """Split SKU variant part into individual dimensional tokens."""
        raw_tokens = [t.strip() for t in rest.split("-") if t.strip()]
        tokens: list[str] = []
        for t in raw_tokens:
            mx = re.match(r"^(\d+)(M\d+.*)$", t, flags=re.IGNORECASE)
            if mx:
                tokens.append(mx.group(1))
                tokens.append(mx.group(2))
            else:
                tokens.append(t)
        return tokens

    def _map_sku_to_parameters(self, sku: str, dim_options: dict[str, list[str]]) -> dict[str, str]:
        """Map SKU tokens to technical configuration parameters."""
        m = re.match(r"^((?:GN|DIN|ISO)\s*[\w.]+)[-\s]+(.*)$", sku, flags=re.IGNORECASE)
        if not m:
            return {}
        base_norm = m.group(1)
        rest = m.group(2)
        tokens = self._split_sku_tokens(rest)

        assigned: dict[str, str] = {"Norm": base_norm}
        remaining_tokens = list(tokens)
        numeric_dims = (
            "länge", "breite", "höhe", "durchmesser", "hub",
            "abstand", "nutbreite", "stärk", "dicke", "tiefe", "maß", "mass"
        )

        for dim_name, options in dim_options.items():
            matched_tok = None
            matched_label = None
            for tok in remaining_tokens:
                norm_tok = self._normalize_token(tok)
                for opt in options:
                    opt_code = opt.split(" - ")[0].strip()
                    if (
                        self._normalize_token(opt) == norm_tok
                        or self._normalize_token(opt_code) == norm_tok
                    ):
                        matched_tok = tok
                        matched_label = opt
                        break
                if matched_tok:
                    break

            if matched_tok and matched_label:
                val = matched_label
                if any(dim in dim_name.lower() for dim in numeric_dims):
                    clean_num = val.replace(",", ".").strip()
                    try:
                        float(clean_num)
                        val = f"{val} mm"
                    except ValueError:
                        pass
                assigned[dim_name] = val
                remaining_tokens.remove(matched_tok)

        return assigned

    def _parse_search_query(self, term: str) -> tuple[str, list[str]]:
        """Parse user query into base norm and configuration tokens."""
        clean = self._clean_sku(term)
        m = re.match(r"^((?:GN|DIN|ISO)\s*[\w.]+)(?:[\s\-]+(.*))?$", clean, flags=re.IGNORECASE)
        if m:
            base_norm = m.group(1)
            rest = m.group(2) or ""
        else:
            m_num = re.match(r"^(\d{3,4}[\w.]*)(?:[\s\-]+(.*))?$", clean, flags=re.IGNORECASE)
            if m_num:
                base_norm = m_num.group(1)
                rest = m_num.group(2) or ""
            else:
                return clean, []

        raw_tokens = [t.strip().lower() for t in re.split(r"[\s\-]+", rest) if t.strip()]
        tokens: list[str] = []
        i = 0
        while i < len(raw_tokens):
            if raw_tokens[i] == "m" and i + 1 < len(raw_tokens) and raw_tokens[i + 1].isdigit():
                tokens.append(f"m{raw_tokens[i + 1]}")
                i += 2
            elif raw_tokens[i] == "x":
                i += 1
            else:
                mx = re.match(r"^(m\d+)[xX]([\d,.]+)$", raw_tokens[i])
                if mx:
                    tokens.append(mx.group(1))
                    tokens.append(mx.group(2))
                else:
                    tokens.append(raw_tokens[i])
                i += 1

        return base_norm, tokens

    def _fetch_soup(self, url: str) -> tuple[BeautifulSoup, str]:
        """Fetch and cache BeautifulSoup instance for a product page."""
        clean_url = url.split("#")[0]
        full_url = clean_url if clean_url.startswith("http") else urljoin(self.base_url, clean_url)
        if full_url in self._soup_cache:
            return self._soup_cache[full_url], full_url

        resp = self.session.get(full_url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        self._soup_cache[full_url] = soup
        return soup, full_url

    def _extract_image_url(self, soup: BeautifulSoup, sku: str) -> str:
        """Extract best matching image URL for the given SKU or variant."""
        imgs: list[str] = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src and "catalog-images" in src:
                imgs.append(src)

        color_match = re.search(r"-([A-Z0-9]{2,3})(?:-[A-Z0-9]+)?$", sku)
        if color_match:
            code = color_match.group(1).upper()
            for img_src in imgs:
                if f"-{code}-" in img_src or f"-{code}." in img_src or f"-{code}_" in img_src:
                    clean_url = img_src.split("?")[0].replace("-thumbnail.jpg", ".jpg")
                    return clean_url if clean_url.startswith("http") else urljoin(self.base_url, clean_url)

        item_img = soup.find(attrs={"itemprop": "image"})
        if item_img:
            src = item_img.get("src") or item_img.get("data-src", "")
            if src:
                clean_url = src.split("?")[0].replace("-thumbnail.jpg", ".jpg")
                return clean_url if clean_url.startswith("http") else urljoin(self.base_url, clean_url)

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
        soup, full_url = self._fetch_soup(url)

        # Check if canonical SKU casing exists in page spans
        for span in soup.find_all("span", style=lambda s: s and "display:none" in s):
            s_txt = span.get_text(strip=True)
            if s_txt.lower().replace(" ", "") == clean_sku.lower().replace(" ", ""):
                clean_sku = s_txt
                break

        # Name & Description
        title_el = soup.find("h1", itemprop="name") or soup.find("h1")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        desc_el = soup.find(itemprop="description")
        description = desc_el.get_text(" ", strip=True) if desc_el else ""

        norm_match = re.match(r"^((?:GN|DIN|ISO)\s*[\w.]+)", clean_sku, flags=re.IGNORECASE)
        base_norm = norm_match.group(1) if norm_match else ""

        # Construct informative product name
        if clean_sku.lower() in title.lower():
            name = title
        elif base_norm and title.lower().startswith(base_norm.lower()):
            name = f"{clean_sku}{title[len(base_norm):]}"
        elif title:
            name = f"{clean_sku} {title}"
        else:
            name = clean_sku

        # Extract configuration dimensions and map SKU tokens
        dim_options = self._parse_config_dimensions(soup)
        parameters = self._map_sku_to_parameters(clean_sku, dim_options)

        # Fallback norm detection if not already mapped
        if norm_match:
            parameters.setdefault("Norm", base_norm)

        # Image
        image_url = self._extract_image_url(soup, clean_sku)

        # Microdata price fallback
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

        # If clean_sku is a configured article code, fetch exact price and tech data
        exact_price, exact_cur, api_params = self._fetch_price_and_params(clean_sku)
        if exact_price > 0:
            price_val = exact_price
            currency = exact_cur
        parameters.update(api_params)

        price_dict: dict[int, tuple[float, str]] = {}
        if price_val > 0:
            price_dict[1] = (price_val, currency)

        product = SupplierProduct(
            sku=clean_sku,
            name=name,
            description=description,
            price=price_dict,
            link=f"{full_url}#{clean_sku}",
            image_url=image_url,
            brand="Ganter Norm",
            parameters=parameters,
            supplier_name=self.name,
            supplier_slug=self.slug,
        )

        self._cache[clean_sku] = product
        return product

    def _query_quickfinder(self, term: str) -> list[dict[str, Any]]:
        """Query Quickfinder API for term."""
        try:
            r = self.session.get(
                f"{self.api_base_url}/de/api/quickfinder",
                params={"q": term},
                timeout=8,
            )
            if r.status_code == 200:
                return r.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ganter Quickfinder query failed for %s: %s", term, exc)
        return []

    def _search_variants_by_tokens(
        self, base_norm: str, tokens: list[str], clean_term: str
    ) -> list[SupplierProduct]:
        """Search and filter configured variants using norm and configuration dimension tokens."""
        hits = self._query_quickfinder(base_norm)
        norm_clean = self._normalize_token(base_norm)
        matching_hits = [
            h for h in hits if self._normalize_token(h.get("norm", "")).startswith(norm_clean)
        ]
        if not matching_hits:
            matching_hits = hits[:3]

        matched_variants: list[SupplierProduct] = []

        for hit in matching_hits[:3]:
            url = hit.get("url")
            if not url:
                continue
            try:
                soup, page_url = self._fetch_soup(url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to fetch Ganter series page %s: %s", url, exc)
                continue

            dim_options = self._parse_config_dimensions(soup)
            title_el = soup.find("h1", itemprop="name") or soup.find("h1")
            title = title_el.get_text(" ", strip=True) if title_el else base_norm
            desc_el = soup.find(itemprop="description")
            desc = desc_el.get_text(" ", strip=True) if desc_el else ""

            spans = soup.find_all("span", style=lambda s: s and "display:none" in s)
            for s in spans:
                var_sku = s.get_text(strip=True)
                if not self._normalize_token(var_sku).startswith(norm_clean):
                    continue

                sku_parts = [self._normalize_token(p) for p in re.split(r"[\s\-]+", var_sku) if p.strip()]

                all_matched = True
                for tok in tokens:
                    norm_tok = self._normalize_token(tok)
                    if not any(norm_tok == part or norm_tok in part for part in sku_parts):
                        all_matched = False
                        break

                if not all_matched:
                    continue

                params = self._map_sku_to_parameters(var_sku, dim_options)
                image_url = self._extract_image_url(soup, var_sku)
                v_prod = SupplierProduct(
                    sku=var_sku,
                    name=f"{var_sku} {title}",
                    description=desc,
                    price={},
                    link=f"{page_url}#{var_sku}",
                    image_url=image_url,
                    brand="Ganter Norm",
                    parameters=params,
                    supplier_name=self.name,
                    supplier_slug=self.slug,
                )
                self._cache[var_sku] = v_prod
                matched_variants.append(v_prod)

        # Sort: exact segment length match first, then longer variants
        target_token_count = len(tokens) + 1
        matched_variants.sort(
            key=lambda p: abs(len(p.sku.split("-")) - target_token_count)
        )

        # If very few results, fetch live price and availability immediately
        if len(matched_variants) <= 2:
            for p in matched_variants:
                p_val, p_cur, p_params = self._fetch_price_and_params(p.sku)
                if p_val > 0:
                    p.price = {1: (p_val, p_cur)}
                p.parameters.update(p_params)

        return matched_variants[:30]

    def _extract_representative_variants(
        self, parsed_items: list[tuple[str, str, dict[str, Any]]], base_norm: str
    ) -> list[SupplierProduct]:
        """Extract representative configured variants (different thread/size steps) from series pages."""
        rep_variants: list[SupplierProduct] = []
        seen_keys: set[str] = set()

        for _code, _desc, item in parsed_items:
            url = item.get("url")
            if not url:
                continue
            try:
                soup, page_url = self._fetch_soup(url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to fetch representative variants for %s: %s", url, exc)
                continue

            dim_options = self._parse_config_dimensions(soup)
            title_el = soup.find("h1", itemprop="name") or soup.find("h1")
            title = title_el.get_text(" ", strip=True) if title_el else base_norm
            desc_el = soup.find(itemprop="description")
            desc = desc_el.get_text(" ", strip=True) if desc_el else ""

            spans = soup.find_all("span", style=lambda s: s and "display:none" in s)
            for s in spans:
                var_sku = s.get_text(strip=True)
                parts = var_sku.split("-")
                # Group by primary size/thread key to get diverse options
                group_key = parts[2] if len(parts) >= 3 else (parts[1] if len(parts) >= 2 else var_sku)
                if group_key in seen_keys:
                    continue
                seen_keys.add(group_key)

                params = self._map_sku_to_parameters(var_sku, dim_options)
                v_prod = SupplierProduct(
                    sku=var_sku,
                    name=f"{var_sku} {title}",
                    description=desc,
                    price={},
                    link=f"{page_url}#{var_sku}",
                    image_url=self._extract_image_url(soup, var_sku),
                    brand="Ganter Norm",
                    parameters=params,
                    supplier_name=self.name,
                    supplier_slug=self.slug,
                )
                self._cache[var_sku] = v_prod
                rep_variants.append(v_prod)
                if len(rep_variants) >= 12:
                    break

            if len(rep_variants) >= 12:
                break

        return rep_variants

    def search(self, term: str) -> list[SupplierProduct]:
        """Search products on Ganter Norm via Quickfinder API or schnell-suche."""
        clean_term = self._clean_sku(term)
        if not clean_term:
            return []

        # Return cached result if exact match is already known
        if clean_term in self._cache:
            return [self._cache[clean_term]]

        base_norm, tokens = self._parse_search_query(clean_term)

        # 1. Check if term is an exact SKU via schnell-suche redirect
        hyphen_candidate = f"{base_norm}-{'-'.join(tokens).upper()}" if tokens else ""
        for candidate in (clean_term, hyphen_candidate):
            if not candidate:
                continue
            try:
                r = self.session.get(
                    f"{self.base_url}/de/produkte/schnell-suche",
                    params={"q": candidate},
                    allow_redirects=False,
                    timeout=10,
                )
                if r.status_code in (301, 302, 303, 307, 308):
                    redirect_loc = r.headers.get("Location")
                    if redirect_loc:
                        product = self._fetch_product_from_page(redirect_loc, sku=candidate)
                        self._cache[clean_term] = product
                        return [product]
            except Exception as exc:  # noqa: BLE001
                logger.debug("Ganter schnell-suche redirect check failed for %s: %s", candidate, exc)

        # 2. Multi-token configuration search (e.g. "GN 300 M8", "DIN 508 14 M12")
        if tokens:
            variant_products = self._search_variants_by_tokens(base_norm, tokens, clean_term)
            if variant_products:
                return variant_products

        # 3. Query Quickfinder API for series
        hits = self._query_quickfinder(clean_term)
        if not hits and base_norm != clean_term:
            hits = self._query_quickfinder(base_norm)

        if hits:
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

            for code, desc, item in parsed_items[:20]:
                if counts[code] > 1 and desc:
                    parts = [p.strip() for p in desc.split(",") if p.strip()]
                    feature = parts[-1] if parts else desc
                    feature = feature.rstrip(".")
                    item_sku = f"{code} ({feature})"
                else:
                    item_sku = code

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

            # For base norm searches, also attach representative configured variants
            if parsed_items and parsed_items[0][0].lower() == base_norm.lower():
                rep_variants = self._extract_representative_variants(parsed_items[:2], base_norm)
                products.extend(rep_variants)

            return products

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
            # If cached product has a page link, fetch full details from its page
            if prod.link:
                try:
                    full_prod = self._fetch_product_from_page(prod.link, sku=prod.sku)
                    self._cache[clean_sku] = full_prod
                    return full_prod
                except Exception:  # noqa: BLE001
                    return prod

        # 2. Try schnell-suche redirect
        base_norm, tokens = self._parse_search_query(clean_sku)
        hyphen_candidate = f"{base_norm}-{'-'.join(tokens).upper()}" if tokens else ""
        for candidate in (clean_sku, hyphen_candidate):
            if not candidate:
                continue
            try:
                r = self.session.get(
                    f"{self.base_url}/de/produkte/schnell-suche",
                    params={"q": candidate},
                    allow_redirects=False,
                    timeout=10,
                )
                if r.status_code in (301, 302, 303, 307, 308):
                    redirect_loc = r.headers.get("Location")
                    if redirect_loc:
                        return self._fetch_product_from_page(redirect_loc, sku=candidate)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Ganter get_product schnell-suche redirect check failed for %s: %s", candidate, exc)

        # 3. Try Quickfinder lookup
        try:
            r_qf = self.session.get(
                f"{self.api_base_url}/de/api/quickfinder",
                params={"q": base_norm or clean_sku},
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
