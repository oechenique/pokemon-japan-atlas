"""atlas_run: el DAG principal del atlas (reglas/03).

Genera un run_id único al inicio y lo pasa a todas las tareas como atlas_run_id
(`run_id` es una variable reservada del contexto de Airflow, que es otra cosa).

TaskGroup bronze:
- ingest: una tarea por fuente de registry.yaml (mapeo dinámico), salvo las que
  consultan Overpass.
- Overpass va partido: overpass_queries arma el plan (una consulta por categoría ×
  bbox, más la de osm_buildings) y fetch_query se expande sobre él, con su propio
  timeout y reintentos, en el pool `overpass` de 1 slot (lo crea airflow-init): una
  consulta por vez en todo Airflow, más la pausa entre consultas. finish_overpass
  cierra las dos fuentes y falla si falta cualquier archivo del plan.
- report: el informe de la corrida en data/bronze/_runs/.
Silver, DQ gate, Gold y publicación se suman en las fases siguientes.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, dag, get_current_context, task, task_group

from pipeline.sources.registry import REGISTRY_PATH, load_registry

DATA_URI = "file:///opt/airflow/data"
REGISTRY_ASSET = Asset(name="registry", uri=f"file://{REGISTRY_PATH.as_posix()}")
OVERPASS_POOL = "overpass"
BRONZE_ASSETS = [
    Asset(name=f"bronze.{source_id}", uri=f"{DATA_URI}/bronze/{source_id}")
    for source_id in load_registry().ids
]


@dag(
    dag_id="atlas_run",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["bronze"],
)
def atlas_run():
    @task(inlets=[REGISTRY_ASSET])
    def start_run() -> str:
        """run_id de la corrida, a partir de cuándo se disparó (estable ante reintentos)."""
        from pipeline.sources.base import make_run_id

        return make_run_id(get_current_context()["dag_run"].run_after)

    @task
    def source_ids() -> list[str]:
        """Fuentes que se ingestan en una sola tarea (todas menos las de Overpass)."""
        from pipeline.sources._overpass import KINDS

        return [s.id for s in load_registry().sources if s.kind not in KINDS]

    @task
    def overpass_queries() -> list[dict]:
        from pipeline.sources._overpass import plan_queries

        return plan_queries(load_registry())

    @task_group(group_id="bronze")
    def bronze(atlas_run_id: str):
        # Tareas de red: reintentos con backoff (reglas/03).
        @task(
            retries=3,
            retry_delay=timedelta(minutes=1),
            retry_exponential_backoff=True,
            max_retry_delay=timedelta(minutes=10),
            execution_timeout=timedelta(hours=1),
            map_index_template="{{ source_id }}",
        )
        def ingest(source_id: str, atlas_run_id: str) -> dict:
            from pipeline.sources.base import ingest_source

            get_current_context()["source_id"] = source_id
            return ingest_source(source_id, atlas_run_id)

        @task(
            pool=OVERPASS_POOL,
            retries=3,
            retry_delay=timedelta(minutes=1),
            retry_exponential_backoff=True,
            max_retry_delay=timedelta(minutes=10),
            # Cubre el timeout de Overpass (180 s) más la descarga; la espera por el
            # slot del pool no cuenta.
            execution_timeout=timedelta(minutes=10),
            map_index_template="{{ query_label }}",
        )
        def fetch_query(item: dict, atlas_run_id: str) -> dict:
            from pipeline.sources._overpass import fetch_planned

            get_current_context()["query_label"] = f"{item['source']}:{item['rel']}"
            return fetch_planned(item, atlas_run_id)

        @task
        def finish_overpass(atlas_run_id: str, fetched: list[dict]) -> list[dict]:
            from pipeline.sources._overpass import KINDS
            from pipeline.sources.base import finish_source

            registry = load_registry()
            return [
                finish_source(s.id, atlas_run_id, registry=registry)
                for s in registry.sources
                if s.kind in KINDS
            ]

        @task(outlets=BRONZE_ASSETS)
        def report(atlas_run_id: str, summaries: list[dict], overpass: list[dict]) -> dict:
            from pipeline.sources.base import write_run_report

            return write_run_report(atlas_run_id, [*summaries, *overpass])

        summaries = ingest.partial(atlas_run_id=atlas_run_id).expand(source_id=source_ids())
        fetched = fetch_query.partial(atlas_run_id=atlas_run_id).expand(item=overpass_queries())
        report(atlas_run_id, summaries, finish_overpass(atlas_run_id, fetched))

    bronze(start_run())


atlas_run()
