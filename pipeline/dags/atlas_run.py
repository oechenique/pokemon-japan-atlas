"""atlas_run: el DAG principal del atlas (reglas/03).

Genera un run_id único al inicio y lo pasa a todas las tareas como atlas_run_id
(`run_id` es una variable reservada del contexto de Airflow, que es otra cosa).

Por ahora (Fase 1) solo tiene el TaskGroup bronze: una tarea por fuente de
registry.yaml, con mapeo dinámico, y un informe final con lo que guardó cada una.
Silver, DQ gate, Gold y publicación se suman en las fases siguientes.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, dag, get_current_context, task, task_group

from pipeline.sources.registry import REGISTRY_PATH, load_registry

DATA_URI = "file:///opt/airflow/data"
REGISTRY_ASSET = Asset(name="registry", uri=f"file://{REGISTRY_PATH.as_posix()}")
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
    tags=["fase-1", "bronze"],
)
def atlas_run():
    @task(inlets=[REGISTRY_ASSET])
    def start_run() -> str:
        """run_id de la corrida, a partir de cuándo se disparó (estable ante reintentos)."""
        from pipeline.sources.base import make_run_id

        return make_run_id(get_current_context()["dag_run"].run_after)

    @task
    def source_ids() -> list[str]:
        return list(load_registry().ids)

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

        @task(outlets=BRONZE_ASSETS)
        def report(atlas_run_id: str, summaries: list[dict]) -> dict:
            from pipeline.sources.base import write_run_report

            return write_run_report(atlas_run_id, summaries)

        summaries = ingest.partial(atlas_run_id=atlas_run_id).expand(source_id=source_ids())
        report(atlas_run_id, summaries)

    bronze(start_run())


atlas_run()
