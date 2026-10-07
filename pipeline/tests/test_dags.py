from datetime import timedelta
from pathlib import Path

from airflow.dag_processing.dagbag import DagBag

DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"


def _bag():
    return DagBag(dag_folder=str(DAGS_DIR))


def test_dags_import_without_errors():
    bag = _bag()
    assert bag.import_errors == {}
    assert {"atlas_smoke", "atlas_run"} <= set(bag.dag_ids)


def test_atlas_run_bronze_is_mapped_over_the_registry():
    dag = _bag().dags["atlas_run"]
    ingest = dag.get_task("bronze.ingest")
    assert ingest.retries == 3
    assert ingest.retry_exponential_backoff
    assert ingest.is_mapped
    assert "bronze.source_ids" in ingest.upstream_task_ids
    report = dag.get_task("bronze.report")
    assert {a.name for a in report.outlets} >= {"bronze.viirs_night", "bronze.seeds"}
    assert dag.get_task("start_run").inlets[0].name == "registry"


def test_atlas_run_splits_overpass_into_a_pooled_mapped_task():
    dag = _bag().dags["atlas_run"]
    fetch = dag.get_task("bronze.fetch_query")
    assert fetch.is_mapped
    assert fetch.pool == "overpass"
    assert fetch.retries == 6
    assert fetch.max_retry_delay == timedelta(minutes=30)
    assert "bronze.overpass_queries" in fetch.upstream_task_ids
    assert "bronze.fetch_query" in dag.get_task("bronze.finish_overpass").upstream_task_ids
    assert "bronze.finish_overpass" in dag.get_task("bronze.report").upstream_task_ids


def test_ingest_and_overpass_split_cover_the_registry_once(registry):
    from pipeline.sources._overpass import KINDS

    single = {s.id for s in registry.sources if s.kind not in KINDS}
    split = {s.id for s in registry.sources if s.kind in KINDS}
    assert split == {"osm_overpass", "osm_buildings"}
    assert single | split == set(registry.ids) and not single & split


def test_atlas_run_silver_tasks_follow_dependencies_without_retries():
    from pipeline.transforms.silver_entities import DEPENDENCIES

    dag = _bag().dags["atlas_run"]
    for entity, upstream in DEPENDENCIES.items():
        task = dag.get_task(f"silver.{entity}")
        assert task.retries == 0 and task.pool == "duckdb", entity
        assert {f"silver.{u}" for u in upstream} <= task.upstream_task_ids, entity
        assert {o.name for o in task.outlets} == {f"silver.{entity}"}
    assert "bronze.report" in dag.get_task("silver.prefecture").upstream_task_ids


def test_dq_gate_runs_after_silver_without_retries():
    dag = _bag().dags["atlas_run"]
    gate = dag.get_task("dq_gate")
    assert gate.retries == 0
    assert "silver.lineage" in gate.upstream_task_ids
    assert {o.name for o in gate.outlets} == {"quality_report"}


def test_gold_runs_after_the_gate_and_views_after_every_table():
    from pipeline.transforms.gold_entities import DERIVED

    dag = _bag().dags["atlas_run"]
    assert "dq_gate" in dag.get_task("gold.copy_silver").upstream_task_ids
    for table, upstream in DERIVED.items():
        task = dag.get_task(f"gold.{table}")
        assert task.retries == 0
        assert {"gold.copy_silver", *(f"gold.{u}" for u in upstream)} <= task.upstream_task_ids
        assert f"gold.{table}" in dag.get_task("gold.views").upstream_task_ids
