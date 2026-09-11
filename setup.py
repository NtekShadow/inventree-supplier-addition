from pathlib import Path

from setuptools import find_packages, setup


readme = Path(__file__).with_name('README.md').read_text(encoding='utf-8')

setup(
    name='inventree-supplier-integration',
    version='0.1.0',
    description='Modular supplier integration plugin for InvenTree',
    long_description=readme,
    long_description_content_type='text/markdown',
    py_modules=['plugin', 'supplier_models'],
    packages=find_packages(),
    install_requires=['requests'],
)