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

TaskGroup silver: una tarea por entidad (pipeline/transforms/silver_entities.py),
con las dependencias entre entidades, y lineage al final. Sin reintentos: si una
transformación falla, es un bug (reglas/03). Cada tarea declara como inlets el Bronze
de las fuentes de su contrato y como outlet su entidad de Silver.

dq_gate: los checks bloqueantes de los contratos y los cruces con PokeAPI y Wikidata,
más los informativos y la cobertura de las fuentes, en
publish/<run_id>/quality_report.json. Si falla un bloqueante, la tarea falla y no hay
Gold. Sin reintentos.

TaskGroup gold (después del gate): copy_silver pasa a Gold el Silver aprobado, una
tarea por tabla derivada (pipeline/transforms/gold_entities.py), views recrea
data/gold/atlas.duckdb con las vistas gold.v_day_XX y lineage cierra. Sin reintentos.

La publicación se suma en la Fase 3.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, dag, get_current_context, task, task_group

from pipeline.quality.contracts import load_contracts
from pipeline.sources.registry import REGISTRY_PATH, load_registry
from pipeline.transforms.gold_entities import DERIVED
from pipeline.transforms.silver_entities import DEPENDENCIES

DATA_URI = "file:///opt/airflow/data"
REGISTRY_ASSET = Asset(name="registry", uri=f"file://{REGISTRY_PATH.as_posix()}")
OVERPASS_POOL = "overpass"
DUCKDB_POOL = "duckdb"
BRONZE_ASSETS = {
    source_id: Asset(name=f"bronze.{source_id}", uri=f"{DATA_URI}/bronze/{source_id}")
    for source_id in load_registry().ids
}
SILVER_ASSETS = {
    entity: Asset(name=f"silver.{entity}", uri=f"{DATA_URI}/silver/{entity}.parquet")
    for entity in DEPENDENCIES
}
CONTRACTS = load_contracts()
QUALITY_ASSET = Asset(name="quality_report", uri="file:///opt/airflow/publish/quality_report")
GOLD_ASSETS = {
    table: Asset(name=f"gold.{table}", uri=f"{DATA_URI}/gold/{table}.parquet")
    for table in (*DEPENDENCIES, *DERIVED)
}
ATLAS_ASSET = Asset(name="gold.atlas", uri=f"{DATA_URI}/gold/atlas.duckdb")


@dag(
    dag_id="atlas_run",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["bronze", "silver", "dq", "gold"],
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

        # Más reintentos y más espaciados que ingest: si Overpass se cae, cada intento
        # falla enseguida (OverpassUnavailable) y la espera entre intentos llega a
        # 30 min, para aguantar una caída de entre 1 y 1,5 h.
        @task(
            pool=OVERPASS_POOL,
            retries=6,
            retry_delay=timedelta(minutes=1),
            retry_exponential_backoff=True,
            max_retry_delay=timedelta(minutes=30),
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

        @task(outlets=list(BRONZE_ASSETS.values()))
        def report(atlas_run_id: str, summaries: list[dict], overpass: list[dict]) -> dict:
            from pipeline.sources.base import write_run_report

            return write_run_report(atlas_run_id, [*summaries, *overpass])

        summaries = ingest.partial(atlas_run_id=atlas_run_id).expand(source_id=source_ids())
        fetched = fetch_query.partial(atlas_run_id=atlas_run_id).expand(item=overpass_queries())
        report(atlas_run_id, summaries, finish_overpass(atlas_run_id, fetched))

    @task_group(group_id="silver")
    def silver(atlas_run_id: str):
        def silver_task(entity: str):
            @task(
                task_id=entity,
                retries=0,
                pool=DUCKDB_POOL,
                inlets=[BRONZE_ASSETS[s] for s in CONTRACTS[entity].sources],
                outlets=[SILVER_ASSETS[entity]],
            )
            def build(atlas_run_id: str) -> dict:
                from pipeline.transforms.silver_entities import build_entity

                return build_entity(entity, atlas_run_id)

            return build

        built = {entity: silver_task(entity)(atlas_run_id) for entity in DEPENDENCIES}
        for entity, upstream in DEPENDENCIES.items():
            for dependency in upstream:
                built[dependency] >> built[entity]

        @task(retries=0)
        def lineage(atlas_run_id: str, summaries: list[dict]) -> dict:
            from pipeline.transforms.base import write_run_lineage

            return write_run_lineage(atlas_run_id, summaries)

        lineage(atlas_run_id, list(built.values()))

    @task(retries=0, pool=DUCKDB_POOL, inlets=list(SILVER_ASSETS.values()), outlets=[QUALITY_ASSET])
    def dq_gate(atlas_run_id: str) -> dict:
        from pipeline.quality.gate import run_gate

        return run_gate(atlas_run_id)

    @task_group(group_id="gold")
    def gold(atlas_run_id: str):
        @task(
            retries=0,
            inlets=[QUALITY_ASSET, *SILVER_ASSETS.values()],
            outlets=[GOLD_ASSETS[e] for e in DEPENDENCIES],
        )
        def copy_silver(atlas_run_id: str) -> list[dict]:
            from pipeline.transforms.gold_entities import copy_silver as copy

            return copy(atlas_run_id)

        def derived_task(table: str):
            @task(task_id=table, retries=0, pool=DUCKDB_POOL, outlets=[GOLD_ASSETS[table]])
            def build(atlas_run_id: str) -> dict:
                from pipeline.transforms.gold_entities import build_derived

                return build_derived(table, atlas_run_id)

            return build

        copied = copy_silver(atlas_run_id)
        built = {table: derived_task(table)(atlas_run_id) for table in DERIVED}
        for table, upstream in DERIVED.items():
            copied >> built[table]
            for dependency in upstream:
                built[dependency] >> built[table]

        @task(retries=0, outlets=[ATLAS_ASSET])
        def views(atlas_run_id: str) -> dict:
            from pipeline.transforms.gold.views import write_views

            return write_views(atlas_run_id)

        @task(retries=0)
        def lineage(atlas_run_id: str, copies: list[dict], tables: list[dict], atlas: dict) -> dict:
            from pipeline.transforms.base import write_run_lineage

            report = write_run_lineage(atlas_run_id, [*copies, *tables], layer="gold")
            return {**report, "views": atlas["views"]}

        atlas = views(atlas_run_id)
        for task_ in built.values():
            task_ >> atlas
        lineage(atlas_run_id, copied, list(built.values()), atlas)

    run_id = start_run()
    bronze(run_id) >> silver(run_id) >> dq_gate(run_id) >> gold(run_id)


atlas_run()
