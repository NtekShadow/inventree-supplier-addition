"""Supplier Addition Plugin for InvenTree."""

from plugin import InvenTreePlugin
from plugin.base.supplier.mixins import SupplierMixin
from plugin.mixins import SettingsMixin

from . import PLUGIN_VERSION


class SupplierAdditionPlugin(SupplierMixin, SettingsMixin, InvenTreePlugin):
    """SupplierAdditionPlugin - modular supplier addition plugin for InvenTree."""

    # Plugin metadata
    TITLE = "Supplier Addition"
    NAME = "Supplier Addition"
    SLUG = "supplier-addition"
    DESCRIPTION = "Modular supplier addition and integration plugin for InvenTree"
    VERSION = PLUGIN_VERSION

    # Additional project information
    AUTHOR = "NtekShadow"
    WEBSITE = "https://github.com/NtekShadow/inventree-supplier-addition"
    LICENSE = "MIT"

    SETTINGS = {
        "DOWNLOAD_IMAGES": {
            "name": "Download part images",
            "description": "Enable downloading of part images during import",
            "validator": bool,
            "default": False,
        }
    }


# Aliases for backward compatibility and alternative references
SupplierAddition = SupplierAdditionPlugin
SupplierIntegrationPlugin = SupplierAdditionPlugin
