# Imagen única del pipeline: Airflow (slim + driver de Postgres), DuckDB con las
# extensiones spatial y h3, y rasterio (GDAL embebido) y h5py para los rasters.
ARG AIRFLOW_VERSION=3.3.2
FROM apache/airflow:slim-${AIRFLOW_VERSION}-python3.12

# gdal-bin solo para gdal_viewshed (cuenca visual del Fuji), que se llama por
# subprocess. Es el GDAL de Debian, separado del que trae rasterio.
USER root
RUN apt-get update  && apt-get install -y --no-install-recommends gdal-bin  && rm -rf /var/lib/apt/lists/*
USER airflow

ARG AIRFLOW_VERSION
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir \
      "apache-airflow[postgres]==${AIRFLOW_VERSION}" \
      -r /tmp/requirements.txt \
 && pip check

# Las extensiones se instalan al construir la imagen para que las corridas no
# dependan de bajarlas en caliente.
RUN python -c "import duckdb; c = duckdb.connect(); c.install_extension('spatial'); c.install_extension('h3', repository='community')"
