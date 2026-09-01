from aion.core.models import Result, Work
from aion.storage.sqlite import Store
from tests.fakes import make_observation


def test_observations_are_deduplicated(tmp_path):
    with Store(tmp_path / "aion.db") as store:
        obs = [make_observation("a"), make_observation("b")]
        assert len(store.save_observations(obs)) == 2
        # 2回目は「変化していない」ので何も返らない
        assert store.save_observations(obs) == []
        assert store.count_observations() == 2


def test_world_state_upsert(tmp_path):
    with Store(tmp_path / "aion.db") as store:
        store.put_world_state("k", {"n": 1})
        store.put_world_state("k", {"n": 2})
        assert store.get_world_state("k").value == {"n": 2}
        assert len(store.all_world_state()) == 1


def test_work_and_result_roundtrip(tmp_path):
    with Store(tmp_path / "aion.db") as store:
        store.save_work(Work(id="w1", objective="o", context="c", status="running"))
        store.save_work(Work(id="w1", objective="o", context="c", status="done"))
        assert store.get_work("w1").status == "done"

        store.save_result(Result(work_id="w1", success=True, output="out"))
        result = store.get_result("w1")
        assert result.success is True and result.output == "out"
