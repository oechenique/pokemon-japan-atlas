import json

import pytest

from pipeline.sources import _overpass
from pipeline.sources._overpass import OverpassError, build_query
from pipeline.sources.base import BronzeRun, IngestError

RUN_1 = "20261007T100000Z"
RUN_2 = "20261007T110000Z"

HEADER = (
    '{\n  "version": 0.6,\n  "generator": "Overpass API 0.7.62",\n  "osm3s": {\n'
    '    "timestamp_osm_base": "{ts}",\n'
    '    "copyright": "The data included in this document is from www.openstreetmap.org."\n'
    "  },\n"
)
BODY = (
    '  "elements": [\n{\n  "type": "node",\n  "id": 1,\n  "lat": 35.7,\n  "lon": 139.7\n}\n  ]\n}\n'
)
REMARK = (
    '  "elements": [\n\n  ],\n'
    '  "remark": "runtime error: Query timed out in \\"query\\" at line 1 after 181 seconds."\n}\n'
)


class FakeResponse:
    def __init__(self, body: str, status: int = 200, chunk: int = 7):
        self.status_code = status
        self._body = body.encode("utf-8")
        self._chunk = chunk
        self.text = body

    def iter_content(self, _size):
        for i in range(0, len(self._body), self._chunk):
            yield self._body[i : i + self._chunk]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def post(self, url, data, **_kwargs):
        self.queries.append(data["data"])
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch, tmp_path):
    monkeypatch.setattr(_overpass.time, "sleep", lambda _s: None)
    monkeypatch.setattr(_overpass, "LOCK_PATH", tmp_path / "overpass.lock")


def _run(registry, make_source, run_id, root, responses):
    run = BronzeRun(registry, make_source("osm_overpass"), run_id, root)
    run.session = FakeSession(responses)
    return run


def test_build_query_with_bbox_and_snapshot():
    query = build_query(
        ['nwr["brand"="ポケモンセンター"]', 'nwr["brand:wikidata"="Q89673816"]'],
        "center",
        timeout_s=180,
        bbox=[34.2, 136.4, 37.9, 141.1],
        snapshot_date="2026-10-31T00:00:00Z",
    )
    assert query == (
        '[out:json][timeout:180][bbox:34.2,136.4,37.9,141.1][date:"2026-10-31T00:00:00Z"];'
        '(nwr["brand"="ポケモンセンター"];nwr["brand:wikidata"="Q89673816"];);out center;'
    )
    assert "area" not in query


def test_build_query_around():
    query = build_query(['way["building"]'], "geom", timeout_s=60, around=(500, 35.7289, 139.7192))
    assert (
        query == '[out:json][timeout:60];(way["building"](around:500,35.7289,139.7192););out geom;'
    )


def test_build_query_needs_exactly_one_area():
    with pytest.raises(ValueError):
        build_query(['node["a"="b"]'], "center", timeout_s=1)


def test_fetch_strips_timestamp_and_keeps_valid_json(registry, make_source, tmp_path):
    run = _run(
        registry,
        make_source,
        RUN_1,
        tmp_path,
        [FakeResponse(HEADER.replace("{ts}", "2026-10-07T10:00:00Z") + BODY)],
    )
    record = _overpass.fetch(run, "pokemon_center/kanto_chubu.json", "q")
    data = json.loads((run.dir / record.path).read_text(encoding="utf-8"))
    assert "timestamp_osm_base" not in data["osm3s"]
    assert data["elements"][0]["id"] == 1
    assert record.extra == {"query": "q", "timestamp_osm_base": "2026-10-07T10:00:00Z"}


def test_same_data_at_another_minute_has_the_same_checksum(registry, make_source, tmp_path):
    first = _run(
        registry,
        make_source,
        RUN_1,
        tmp_path,
        [FakeResponse(HEADER.replace("{ts}", "2026-10-07T10:00:00Z") + BODY)],
    )
    a = _overpass.fetch(first, "x.json", "q")
    second = _run(
        registry,
        make_source,
        RUN_2,
        tmp_path,
        [FakeResponse(HEADER.replace("{ts}", "2026-10-07T11:00:00Z") + BODY)],
    )
    b = _overpass.fetch(second, "x.json", "q")
    assert a.sha256 == b.sha256


def test_remark_with_http_200_is_a_failure(registry, make_source, tmp_path):
    run = _run(
        registry, make_source, RUN_1, tmp_path, [FakeResponse(HEADER.replace("{ts}", "t") + REMARK)]
    )
    with pytest.raises(OverpassError, match="timed out"):
        _overpass.fetch(run, "x.json", "q")
    assert not (run.dir / "x.json").exists()
    assert not list(run.dir.rglob("*.part"))


def test_http_error_is_a_failure(registry, make_source, tmp_path):
    run = _run(registry, make_source, RUN_1, tmp_path, [FakeResponse("rate limited", status=429)])
    with pytest.raises(OverpassError, match="429"):
        _overpass.fetch(run, "x.json", "q")


def test_truncated_response_is_a_failure(registry, make_source, tmp_path):
    body = (HEADER.replace("{ts}", "t") + BODY)[:-20]
    run = _run(registry, make_source, RUN_1, tmp_path, [FakeResponse(body)])
    with pytest.raises(OverpassError, match="truncada"):
        _overpass.fetch(run, "x.json", "q")


def test_osm_overpass_queries_every_category_and_bbox_once(registry, make_source, tmp_path):
    from pipeline.sources import osm_overpass

    categories = registry.get("osm_overpass").params["categories"]
    expected = sum(
        len(registry.japan_bboxes) if c["bboxes"] == "all" else len(c["bboxes"]) for c in categories
    )
    body = HEADER.replace("{ts}", "t") + BODY
    run = _run(
        registry, make_source, RUN_1, tmp_path, [FakeResponse(body) for _ in range(expected)]
    )
    osm_overpass.ingest(run)
    assert len(run.session.queries) == expected
    assert all("[bbox:" in q and "area" not in q for q in run.session.queries)
    assert (run.dir / "rail_kanto" / "kanto_chubu.json").is_file()

    # Un reintento de la tarea no repite ninguna consulta.
    retry = _run(registry, make_source, RUN_1, tmp_path, [])
    osm_overpass.ingest(retry)
    assert retry.session.queries == []


# OVERPASS_MODE ---------------------------------------------------------------


def _first_run(registry, make_source, root):
    body = HEADER.replace("{ts}", "t") + BODY
    run = _run(registry, make_source, RUN_1, root, [FakeResponse(body)])
    _overpass.fetch(run, "x.json", "q")
    _overpass.finalize(run)
    run.finish()


def test_reuse_mode_copies_previous_bronze_without_querying(
    registry, make_source, tmp_path, monkeypatch
):
    _first_run(registry, make_source, tmp_path)
    monkeypatch.setenv("OVERPASS_MODE", "reuse")
    second = _run(registry, make_source, RUN_2, tmp_path, [])
    record = _overpass.fetch(second, "x.json", "q")
    _overpass.finalize(second)
    metadata_summary = second.finish()

    assert second.session.queries == []
    assert record.reused_from == RUN_1
    assert record.extra["query"] == "q"
    metadata = second.metadata()
    assert metadata["extra"]["overpass_mode"] == "reuse"
    assert any("OVERPASS_MODE=reuse" in w for w in metadata["warnings"])
    assert metadata_summary["unchanged_vs_previous"] is True


def test_reuse_mode_fails_when_the_query_changed(registry, make_source, tmp_path, monkeypatch):
    _first_run(registry, make_source, tmp_path)
    monkeypatch.setenv("OVERPASS_MODE", "reuse")
    second = _run(registry, make_source, RUN_2, tmp_path, [])
    with pytest.raises(IngestError, match="cambió"):
        _overpass.fetch(second, "x.json", "otra consulta")
    assert second.session.queries == []


def test_reuse_mode_fails_without_a_previous_run(registry, make_source, tmp_path, monkeypatch):
    monkeypatch.setenv("OVERPASS_MODE", "reuse")
    run = _run(registry, make_source, RUN_1, tmp_path, [])
    with pytest.raises(IngestError, match="OVERPASS_MODE=query"):
        _overpass.fetch(run, "x.json", "q")


def test_default_mode_queries_and_records_it(registry, make_source, tmp_path, monkeypatch):
    monkeypatch.delenv("OVERPASS_MODE", raising=False)
    _first_run(registry, make_source, tmp_path)
    run = BronzeRun(registry, make_source("osm_overpass"), RUN_1, tmp_path)
    assert run.metadata()["extra"]["overpass_mode"] == "query"
    assert run.metadata()["warnings"] == []


def test_unknown_mode_is_an_error(monkeypatch):
    monkeypatch.setenv("OVERPASS_MODE", "cache")
    with pytest.raises(IngestError):
        _overpass.mode()


# Overpass partido (atlas_run) ------------------------------------------------


def test_plan_covers_both_overpass_sources(registry):
    plan = _overpass.plan_queries(registry)
    by_source = {}
    for item in plan:
        by_source.setdefault(item["source"], []).append(item["rel"])
    categories = registry.get("osm_overpass").params["categories"]
    expected = sum(
        len(registry.japan_bboxes) if c["bboxes"] == "all" else len(c["bboxes"]) for c in categories
    )
    assert len(by_source["osm_overpass"]) == expected
    assert by_source["osm_buildings"] == ["buildings.json"]
    assert "pokemon_store/kanto_chubu.json" in by_source["osm_overpass"]
    rels = [(i["source"], i["rel"]) for i in plan]
    assert len(rels) == len(set(rels))


def _patch_session(monkeypatch, responses):
    session = FakeSession(responses)
    monkeypatch.setattr(_overpass.BronzeRun, "__init__", _wrap_init(session), raising=True)
    return session


def _wrap_init(session, original=BronzeRun.__init__):
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.session = session

    return init


def test_split_fetch_then_finish_writes_one_metadata(registry, tmp_path, monkeypatch):
    from pipeline.sources.base import finish_source

    plan = [i for i in _overpass.plan_queries(registry) if i["source"] == "osm_buildings"]
    body = HEADER.replace("{ts}", "t") + BODY
    session = _patch_session(monkeypatch, [FakeResponse(body)])
    result = _overpass.fetch_planned(plan[0], RUN_1, registry=registry, root=tmp_path)
    assert result["path"] == "buildings.json" and result["reused_from"] is None
    # Un reintento de la misma tarea no vuelve a consultar.
    _overpass.fetch_planned(plan[0], RUN_1, registry=registry, root=tmp_path)
    assert len(session.queries) == 1

    summary = finish_source("osm_buildings", RUN_1, registry=registry, root=tmp_path)
    assert summary["files"] == 1
    metadata = BronzeRun(registry, registry.get("osm_buildings"), RUN_1, tmp_path).metadata()
    assert metadata["extra"]["overpass_mode"] == "query"
    assert metadata["extra"]["center"]["osm"] == "node/3350332481"
    with pytest.raises(IngestError, match="cerrada"):
        _overpass.fetch_planned(plan[0], RUN_1, registry=registry, root=tmp_path)


def test_finish_fails_when_a_planned_query_is_missing(registry, tmp_path, monkeypatch):
    from pipeline.sources.base import finish_source

    plan = [i for i in _overpass.plan_queries(registry) if i["source"] == "osm_overpass"]
    body = HEADER.replace("{ts}", "t") + BODY
    _patch_session(monkeypatch, [FakeResponse(body)])
    _overpass.fetch_planned(plan[0], RUN_1, registry=registry, root=tmp_path)
    with pytest.raises(IngestError, match="faltan"):
        finish_source("osm_overpass", RUN_1, registry=registry, root=tmp_path)
