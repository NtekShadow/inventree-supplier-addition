"""Backward-compatibility root module for supplier models."""

from inventree_supplier_addition.models import SupplierProduct, SupplierProvider

__all__ = [
    "SupplierProduct",
    "SupplierProvider",
]
