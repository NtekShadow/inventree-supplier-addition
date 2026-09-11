# Supplier Addition

Modular supplier addition and integration plugin for InvenTree.

Author: NtekShadow

## Features

- Modular architecture for integrating external suppliers into InvenTree
- Provider abstraction for searching parts and fetching product data
- Integrated with InvenTree `SupplierMixin` and `SettingsMixin`

## Installation

### InvenTree Plugin Manager

In the InvenTree web interface:
1. Navigate to **System Settings > Plugin Settings**
2. Install plugin via Git URL:
   ```text
   git+https://github.com/NtekShadow/inventree-supplier-addition.git
   ```
3. Enable the **Supplier Addition** plugin.

### Command Line

```bash
pip install git+https://github.com/NtekShadow/inventree-supplier-addition.git
```

## Configuration

Configurable via **Plugin Settings** in the InvenTree Admin Center:
- `DOWNLOAD_IMAGES`: Enable downloading of part images during import (default: `False`).

## Development

```bash
pip install -e .
ruff check
pytest
```