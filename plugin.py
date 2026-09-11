"""Backward-compatibility root module for InvenTree plugin discovery."""

from inventree_supplier_addition.core import (
    SupplierAddition,
    SupplierAdditionPlugin,
    SupplierIntegrationPlugin,
)

__all__ = [
    "SupplierAddition",
    "SupplierAdditionPlugin",
    "SupplierIntegrationPlugin",
]
