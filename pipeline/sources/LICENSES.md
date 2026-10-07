# Verificación de licencias de fuentes

Registro de la verificación pedida por la regla 03 para las fuentes marcadas con ⚠️ y para las Poké Lids. Cada entrada anota la URL consultada, la fecha, la licencia y las obligaciones que impone. Las citas textuales van en inglés, como en el original.

Fecha de verificación: 2026-10-06.

## `kontur_population` · aprobada

- Dataset: *Japan: Population Density for 400m H3 Hexagons* (HDX, organización Kontur).
- Ficha: https://data.humdata.org/dataset/kontur-population-japan (leída vía la API de CKAN `package_show`).
- Licencia declarada: `cc-by`, "Creative Commons Attribution International (CC BY)".
- Archivo: `kontur_population_JP_20231101.gpkg.gz`, 16.070.678 bytes, con ETag y `Last-Modified` estables en S3 (sirven para la idempotencia).
  URL: https://geodata-eu-central-1-kontur-public.s3.amazonaws.com/kontur_datasets/kontur_population_JP_20231101.gpkg.gz
- Es el recorte de Japón: **no hace falta tocar el archivo global** (2,4 GB).
- Resolución: hexágonos H3 de 400 m (resolución 8).
- Atribución: "Kontur Population: Global Population Density for 400m H3 Hexagons (CC BY 4.0)".
- Nota: Kontur fusiona GHSL, Facebook, Microsoft Buildings, Copernicus Land Cover y OSM, y publica el resultado como CC BY.

## `copernicus_dem` · aprobada (GLO-90)

- Datos: Copernicus DEM GLO-90 en `s3://copernicus-dem-90m` (eu-central-1), accesible sin credenciales (`--no-sign-request`).
  - Ficha: https://registry.opendata.aws/copernicus-dem/
  - El índice de teselas está en `tileList.txt`: 247 teselas de 1° caen en el bbox de Japón. Por ejemplo, la del Fuji (`Copernicus_DSM_COG_30_N35_00_E138_00_DEM`) pesa 5,3 MB.
- Licencia: "Licence for COP-DEM-GLO-90-F Global 90m Full, Free & Open", dentro del documento https://dataspace.copernicus.eu/sites/default/files/media/files/2025-06/copernicus_contributing_mission_data_access_v2_cop_dem_licenses.pdf
- Art. 4, derechos: "(a) reproduction; (b) distribution; (c) communication to the General Public; (d) adaptation, modification and combination with other data and information."
- Art. 6, obligaciones:
  - Aviso para producto modificado: "produced using Copernicus WorldDEM™-90 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved".
  - Exención de responsabilidad que tiene que figurar en la licencia o aviso de lo que se distribuye: "The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM™-90".
  - No sugerir respaldo oficial.
  - Quien reciba lo redistribuido queda obligado por estas mismas condiciones.
- Alcance: **solo GLO-90.** GLO-30 tiene otra licencia en el mismo documento y no se usa.

## `viirs_night` · licencia apta, acceso con cuenta

### Opción original: EOG VNL (Colorado School of Mines)

- Página: https://eogdata.mines.edu/products/vnl/
- Licencia: https://eogdata.mines.edu/files/EOG_products_CC_License.pdf: "VIIRS nighttime lights (VNL)" bajo CC BY 4.0, "users are allowed to copy, modify, and distribute data in any format for any purpose".
- Obligaciones extra:
  - Aviso en los productos derivados: "This product was made utilizing (…) data produced by the Earth Observation Group, Payne Institute for Public Policy, Colorado School of Mines."
  - "Large format graphical renditions (…) shall carry the Earth Observation Group logo." En formato chico alcanza con "Source: EOG, Colorado School of Mines."
  - Citar los papers del Exhibit 2.
- Acceso: **requiere cuenta.** `https://eogdata.mines.edu/nighttime_light/annual/v22/` redirige a un login OpenID Connect (`eogauth.mines.edu`), y según su propia documentación la aprobación de la cuenta tarda de 1 a 2 días.
- Formato: el anual V2 se distribuye como archivo global comprimido con gzip (`.tif.gz`). Un gzip no admite lectura por rangos, así que habría que bajar el global entero. Eso choca con la regla 03.

### Alternativa evaluada: NASA Black Marble VNP46A4 v2

- Producto: "VIIRS/NPP Lunar BRDF-Adjusted Nighttime Lights Yearly L3 Global 15 arc second Linear Lat Lon Grid", DOI 10.5067/VIIRS/VNP46A4.002.
  - Ficha: https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A4/
- Licencia: la política de datos de NASA Earth Science (https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance) indica CC0 para misiones dirigidas por NASA. Se pide citar el dataset y no sugerir respaldo de NASA. No exige logo.
- Formato: teselas HDF5 de 10°×10°. Japón entra en 7 teselas (h30v05, h30v06, h31v04, h31v05, h31v06, h32v04, h32v05), que suman 641 MB para 2024. No es el archivo global. Hay años disponibles hasta 2025.
- Acceso: **requiere cuenta de NASA Earthdata** (gratuita, alta inmediata). El listado es público, pero la descarga sin token devuelve 303.

## Poké Lids (ポケふた) · OSM sirve

- **OSM**: 260 nodos con nombre `ポケふた（…）` y `name:en` "Poké Lids (…)" en todo Japón, de los 25° a los 45° N.
  - Etiquetado típico: `man_made=manhole` y `manhole=yes`; 15 están como `tourism=artwork`.
  - Solo 2 tienen `start_date`.
  - Referencia: el total oficial superaba las 370 tapas en julio de 2025, así que la cobertura de OSM es de alrededor del 70%.
- **Wikidata**: solo existe el concepto (Q109975199, "Pokéfuta"). No hay instancias ni coordenadas.
- **Sitio oficial**: no se consultó, porque OSM alcanza (regla 03: el sitio oficial se pregunta antes de usarlo).
