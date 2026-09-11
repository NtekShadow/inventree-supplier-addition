# InvenTree Supplier Integration

Das Plugin trennt die InvenTree-Anbindung von den APIs einzelner Lieferanten.

## Lieferanten hinzufuegen

Ein Lieferant implementiert `SupplierProvider` aus `supplier_models.py` und liefert
`SupplierProduct`-Objekte zurueck. Die Provider-Klasse wird anschliessend in
`SupplierIntegrationPlugin.__init__` registriert:

```python
self.providers = {
	'landefeld': LandefeldProvider(),
	'neuer-lieferant': NewSupplierProvider(),
}
```

Der Provider kennt nur seine eigene API. `supplier_plugin.py` kuemmert sich um
Suche, Import und die InvenTree-Modelle.