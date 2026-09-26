# Crawler KA Gaming

Crawler HTTP del catálogo público de KA Gaming.

## Estado

Validado contra el catálogo live el 26-09-2026.

- Endpoint de catálogo: `https://rmpdemo.kaga88.com/kaga/publicGameList`
- Cliente HTTP: `curl_cffi` con fingerprint de navegador, necesario por el 403 observado con clientes HTTP genéricos.
- Targets live validados: **1.030**.
- `targets.txt` usa `loc=es` y se genera directamente desde el catálogo actual.
- GitHub Actions vuelve a generar el catálogo live y exige que coincida exactamente con el `targets.txt` versionado.

## Uso rápido

Sólo targets:

```bash
python crawl_ka_gaming.py --targets-only --lang es --min-games 1000
```

Catálogo completo con nombres y miniaturas:

```bash
python crawl_ka_gaming.py --lang es --min-games 1000
```

Salida completa:

```text
data/providers/ka_gaming/catalog.json
data/providers/ka_gaming/<juego>/thumbnail.png
targets.txt
```

El crawler valida `numGames`, rechaza IDs duplicados, comprueba la estructura de cada target y no considera completo un catálogo si falta una miniatura.
