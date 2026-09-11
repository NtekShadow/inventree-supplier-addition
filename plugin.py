"""Backward-compatibility root module for InvenTree plugin discovery."""

from inventree_supplier_addition.core import (
    SupplierAddition,
    SupplierAdditionPlugin,
    SupplierIntegration,
    SupplierIntegrationPlugin,
)

__all__ = [
    "SupplierAddition",
    "SupplierAdditionPlugin",
    "SupplierIntegration",
    "SupplierIntegrationPlugin",
]

