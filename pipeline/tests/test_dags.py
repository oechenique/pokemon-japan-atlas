from pathlib import Path

from airflow.dag_processing.dagbag import DagBag

DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"


def test_dags_import_without_errors():
    bag = DagBag(dag_folder=str(DAGS_DIR))
    assert bag.import_errors == {}
    assert "atlas_smoke" in bag.dag_ids
