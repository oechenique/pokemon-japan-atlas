# Imagen única del pipeline: Airflow (slim + driver de Postgres) y DuckDB con las
# extensiones spatial y h3.
ARG AIRFLOW_VERSION=3.3.2
FROM apache/airflow:slim-${AIRFLOW_VERSION}-python3.12

ARG AIRFLOW_VERSION
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir \
      "apache-airflow[postgres]==${AIRFLOW_VERSION}" \
      -r /tmp/requirements.txt

# Las extensiones se instalan al construir la imagen para que las corridas no
# dependan de bajarlas en caliente.
RUN python -c "import duckdb; c = duckdb.connect(); c.install_extension('spatial'); c.install_extension('h3', repository='community')"
