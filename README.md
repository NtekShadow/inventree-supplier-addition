# InvenTree Supplier Addition

Modular supplier addition and integration plugin for [InvenTree](https://inventree.org/).

**Author:** NtekShadow  
**License:** MIT

---

## Übersicht / Overview

Dieses Plugin trennt die InvenTree-Anbindung von den APIs einzelner Bauteillieferanten. Es basiert auf dem offiziellen InvenTree Plugin-Template (`inventree-plugin-creator`) und implementiert die InvenTree `SupplierMixin` sowie `SettingsMixin`.

Bereits integrierte Lieferanten:
- **Landefeld** (`LandefeldProvider`)

---

## Installation

### 1. InvenTree Plugin-Verwaltung (Web-UI)

1. Navigiere in InvenTree zu **System-Einstellungen > Plugin-Einstellungen**.
2. Klicke auf **Plugin installieren**.
3. Gib folgende Informationen ein:
   - **Paketname:** `inventree-supplier-addition`
   - **Quell-URL:** `git+https://github.com/NtekShadow/inventree-supplier-addition.git`
4. Aktiviere das Plugin **Supplier Addition** nach der Installation.
5. Starte den InvenTree-Server / Container neu.

### 2. Manuelle Installation via CLI

```bash
pip install git+https://github.com/NtekShadow/inventree-supplier-addition.git
```

Nach der Installation InvenTree neu laden:
```bash
invoke plugins
```

---

## Konfiguration

In den Plugin-Einstellungen im InvenTree Admin Center stehen folgende Optionen zur Verfügung:

| Einstellung | Typ | Standard | Beschreibung |
|---|---|---|---|
| `DOWNLOAD_IMAGES` | Boolean | `False` | Ermöglicht das automatische Herunterladen von Bauteilbildern beim Import |

---

## Architektur & Lieferanten hinzufügen

Das Projekt folgt der modularen Standardstruktur für InvenTree-Plugins:

```text
inventree-supplier-addition/
├── inventree_supplier_addition/
│   ├── __init__.py
│   ├── core.py               # Plugin-Klasse (SupplierMixin, SettingsMixin)
│   ├── models.py             # SupplierProduct Dataclass & SupplierProvider Protocol
│   ├── supplier_models.py    # Kompatibilitäts-Alias
│   └── suppliers/
│       ├── __init__.py
│       └── landefeld.py      # Landefeld Provider-Implementierung
├── tests/
│   ├── test_landefeld.py     # Tests für den Provider
│   └── test_plugin.py        # Tests für das Plugin
├── .github/workflows/
│   ├── ci.yaml               # CI-Pipeline (Ruff, Pytest, Build)
│   └── pypi.yaml             # PyPI Release Pipeline
├── pyproject.toml            # PEP 621 / InvenTree Plugin-Metadaten & Entry Points
├── setup.cfg
├── setup.py
└── README.md
```

### Eigenen Lieferanten implementieren

Ein neuer Lieferant implementiert das `SupplierProvider`-Protokoll aus `inventree_supplier_addition.models`:

```python
from inventree_supplier_addition.models import SupplierProduct, SupplierProvider

class CustomSupplierProvider:
    slug = "mein-lieferant"
    name = "Mein Lieferant"

    def search(self, term: str) -> list[SupplierProduct]:
        # Suche über Lieferanten-API durchführen
        return [...]

    def get_product(self, sku: str) -> SupplierProduct:
        # Einzelnes Produkt per Artikelnummer abrufen
        return SupplierProduct(...)
```

Anschließend wird der Provider in `SupplierAdditionPlugin.__init__` oder per `register_provider` registriert:

```python
plugin = SupplierAdditionPlugin()
plugin.register_provider(CustomSupplierProvider())
```

---

## Entwicklung & Tests

Entwicklungsumgebung vorbereiten:

```bash
git clone https://github.com/NtekShadow/inventree-supplier-addition.git
cd inventree-supplier-addition
pip install -e .
pip install ruff pytest build
```

Tests ausführen:
```bash
pytest
```

Code-Style überprüfen:
```bash
ruff check .
```

Paket bauen:
```bash
python -m build
```