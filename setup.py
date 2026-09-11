"""Setup configuration for InvenTree Supplier Addition Plugin."""

import os
from pathlib import Path
from setuptools import find_packages, setup


def detect_package_name():
    """Dynamically match the package name expected by pip or plugins.txt."""
    # 1. Check InvenTree plugins.txt file if present
    for path in [
        "/home/inventree/data/plugins.txt",
        "/data/plugins.txt",
        "/var/lib/inventree/plugins.txt",
        os.environ.get("INVENTREE_PLUGIN_FILE", ""),
    ]:
        if path and os.path.exists(path):
            try:
                active_lines = []
                for line in Path(path).read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        active_lines.append(line)

                has_integration = any("inventree-supplier-integration" in l for l in active_lines)
                has_addition = any("inventree-supplier-addition" in l for l in active_lines)

                if has_integration and not has_addition:
                    return "inventree-supplier-integration"
                if has_addition and not has_integration:
                    return "inventree-supplier-addition"
                if has_integration and has_addition:
                    curr_dir = Path(__file__).resolve().parent.name
                    if "inventree-supplier-addition" in curr_dir:
                        return "inventree-supplier-addition"
                    return "inventree-supplier-integration"
            except Exception:
                pass

    # 2. Check current directory name (pip clones git repos to <pkg_name>_<hash>)
    curr_dir = Path(__file__).resolve().parent.name
    if "inventree-supplier-integration" in curr_dir:
        return "inventree-supplier-integration"
    if "inventree-supplier-addition" in curr_dir:
        return "inventree-supplier-addition"

    # 3. Inspect caller/parent process command line arguments
    pid = os.getppid()
    for _ in range(8):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", errors="ignore")
                if "inventree-supplier-integration" in cmd:
                    return "inventree-supplier-integration"
                if "inventree-supplier-addition" in cmd:
                    return "inventree-supplier-addition"
            with open(f"/proc/{pid}/status", "r") as f:
                for line in f:
                    if line.startswith("PPid:"):
                        pid = int(line.split()[1])
                        break
        except Exception:
            break

    return "inventree-supplier-addition"


readme = ""
readme_path = Path(__file__).parent / "README.md"
if readme_path.exists():
    readme = readme_path.read_text(encoding="utf-8")

py_modules = []
for mod in ["plugin", "supplier_models"]:
    if (Path(__file__).parent / f"{mod}.py").exists():
        py_modules.append(mod)

setup(
    name=detect_package_name(),
    version="0.2.0",
    description="Modular supplier addition and integration plugin for InvenTree",
    long_description=readme,
    long_description_content_type="text/markdown",
    author="NtekShadow",
    url="https://github.com/NtekShadow/inventree-supplier-addition",
    license="MIT",
    packages=find_packages(exclude=["tests*"]),
    py_modules=py_modules,
    install_requires=["requests"],
    python_requires=">=3.9",
    entry_points={
        "inventree_plugins": [
            "SupplierIntegrationPlugin = inventree_supplier_addition.core:SupplierIntegrationPlugin",
            "SupplierAdditionPlugin = inventree_supplier_addition.core:SupplierAdditionPlugin",
            "SupplierIntegration = inventree_supplier_addition.core:SupplierIntegrationPlugin",
            "SupplierAddition = inventree_supplier_addition.core:SupplierAdditionPlugin",
        ]
    },
)