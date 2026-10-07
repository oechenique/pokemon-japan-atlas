import json

import pytest

from pipeline.sources import base
from pipeline.sources.base import (
    METADATA,
    PROGRESS,
    BronzeRun,
    IngestError,
    aggregate_checksum,
    file_suffix,
    make_run_id,
)

RUN_1 = "20261007T100000Z"
RUN_2 = "20261007T110000Z"


def _run(registry, source, run_id, root):
    return BronzeRun(registry, source, run_id, root)


def test_run_id_is_sortable_utc():
    import pendulum

    when = pendulum.datetime(2026, 10, 7, 9, 5, 3, tz="America/Argentina/Buenos_Aires")
    assert make_run_id(when) == "20261007T120503Z"


def test_rejects_bad_run_id_and_paths(registry, make_source, tmp_path):
    with pytest.raises(ValueError):
        _run(registry, make_source(), "2026-10-07", tmp_path)
    run = _run(registry, make_source(), RUN_1, tmp_path)
    for rel in ("../x", "/etc/passwd", "_progress.jsonl", "a/../../b"):
        with pytest.raises(ValueError):
            run.path(rel)


def test_download_writes_file_and_metadata(registry, make_source, tmp_path, file_server):
    file_server.files["/a.txt"] = b"hola"
    run = _run(registry, make_source(), RUN_1, tmp_path)
    record = run.download("a.txt", file_server.url("/a.txt"))
    summary = run.finish()

    assert (run.dir / "a.txt").read_bytes() == b"hola"
    assert not (run.dir / PROGRESS).exists()
    metadata = json.loads((run.dir / METADATA).read_text(encoding="utf-8"))
    assert metadata["files"][0]["sha256"] == record.sha256
    assert metadata["files"][0]["etag"]
    assert metadata["checksum"] == aggregate_checksum([record])
    assert metadata["license"]["id"] == "public-domain"
    assert metadata["fetched_at"].endswith("Z")
    assert metadata["previous_run_id"] is None
    assert summary["unchanged_vs_previous"] is False
    assert not list(run.dir.rglob("*.part"))


def test_second_run_reuses_unchanged_file_with_304(registry, make_source, tmp_path, file_server):
    file_server.files["/a.txt"] = b"hola"
    first = _run(registry, make_source(), RUN_1, tmp_path)
    first.download("a.txt", file_server.url("/a.txt"))
    first_summary = first.finish()

    second = _run(registry, make_source(), RUN_2, tmp_path)
    record = second.download("a.txt", file_server.url("/a.txt"))
    summary = second.finish()

    assert file_server.requests[-1] == ("/a.txt", 304)
    assert record.reused_from == RUN_1
    assert (second.dir / "a.txt").read_bytes() == b"hola"
    assert summary["checksum"] == first_summary["checksum"]
    assert summary["unchanged_vs_previous"] is True
    assert summary["previous_run_id"] == RUN_1


def test_changed_file_is_downloaded_again(registry, make_source, tmp_path, file_server):
    file_server.files["/a.txt"] = b"hola"
    first = _run(registry, make_source(), RUN_1, tmp_path)
    first.download("a.txt", file_server.url("/a.txt"))
    first.finish()

    file_server.files["/a.txt"] = b"chau"
    second = _run(registry, make_source(), RUN_2, tmp_path)
    record = second.download("a.txt", file_server.url("/a.txt"))
    assert record.reused_from is None
    assert second.finish()["unchanged_vs_previous"] is False


def test_incomplete_run_is_not_a_previous_run(registry, make_source, tmp_path, file_server):
    file_server.files["/a.txt"] = b"hola"
    broken = _run(registry, make_source(), RUN_1, tmp_path)
    broken.download("a.txt", file_server.url("/a.txt"))  # sin finish(): sin metadata.json

    second = _run(registry, make_source(), RUN_2, tmp_path)
    assert second.previous is None


def test_retry_within_a_run_does_not_fetch_again(registry, make_source, tmp_path, file_server):
    file_server.files["/a.txt"] = b"hola"
    run = _run(registry, make_source(), RUN_1, tmp_path)
    run.download("a.txt", file_server.url("/a.txt"))
    # Un reintento de Airflow crea otro BronzeRun sobre el mismo directorio.
    retry = _run(registry, make_source(), RUN_1, tmp_path)
    retry.download("a.txt", file_server.url("/a.txt"))
    assert [r for r in file_server.requests if r[0] == "/a.txt"] == [("/a.txt", 200)]
    assert retry.finish()["files"] == 1


def test_finish_without_files_fails(registry, make_source, tmp_path):
    with pytest.raises(IngestError):
        _run(registry, make_source(), RUN_1, tmp_path).finish()


def test_bad_magic_is_rejected(registry, make_source, tmp_path, file_server):
    file_server.files["/x.zip"] = b"<html>no es un zip</html>"
    run = _run(registry, make_source(), RUN_1, tmp_path)
    with pytest.raises(IngestError):
        run.download("x.zip", file_server.url("/x.zip"))
    assert not (run.dir / "x.zip").exists()


def test_truncated_gzip_is_rejected(registry, make_source, tmp_path, file_server):
    import gzip
    import os

    file_server.files["/p.gpkg.gz"] = gzip.compress(os.urandom(100_000))[:2000]
    source = make_source(
        "kontur_population", params={"files": [{"name": "p", "url": file_server.url("/p.gpkg.gz")}]}
    )
    run = _run(registry, source, RUN_1, tmp_path)
    with pytest.raises(IngestError):
        base.download_files(run)
    assert not (run.dir / "p.gpkg.gz").exists()


def test_reuse_detects_corrupted_previous_file(registry, make_source, tmp_path):
    first = _run(registry, make_source(), RUN_1, tmp_path)
    first.write_bytes("a.bin", b"original")
    first.finish()
    (first.dir / "a.bin").write_bytes(b"cambiado")
    second = _run(registry, make_source(), RUN_2, tmp_path)
    with pytest.raises(IngestError):
        second.reuse("a.bin")
    assert not (second.dir / "a.bin").exists()


def test_ingest_source_is_idempotent_for_a_complete_run(registry, tmp_path, monkeypatch):
    calls = []

    class FakeModule:
        @staticmethod
        def ingest(run):
            calls.append(run.run_id)
            run.write_bytes("x.json", b"{}")

    monkeypatch.setattr(base, "source_module", lambda _id: FakeModule)
    first = base.ingest_source("pokeapi", RUN_1, registry=registry, root=tmp_path)
    again = base.ingest_source("pokeapi", RUN_1, registry=registry, root=tmp_path)
    assert calls == [RUN_1]
    assert again == first


def test_run_report_sums_sources(tmp_path):
    summaries = [
        {"source": "b", "files": 2, "bytes": 10},
        {"source": "a", "files": 1, "bytes": 5},
    ]
    report = base.write_run_report(RUN_1, summaries, root=tmp_path)
    assert report["bytes"] == 15 and report["files"] == 3
    assert [s["source"] for s in report["sources"]] == ["a", "b"]
    assert (tmp_path / "_runs" / f"run_id={RUN_1}.json").is_file()


@pytest.mark.parametrize(
    ("url", "suffix"),
    [
        ("https://x/ne_10m_land.zip", ".zip"),
        ("https://x/kontur_population_JP_20231101.gpkg.gz", ".gpkg.gz"),
        ("https://x/tileList.txt?x=1", ".txt"),
    ],
)
def test_file_suffix(url, suffix):
    assert file_suffix(url) == suffix
