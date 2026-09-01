from aion.adapters.observation import RSSAdapter
from aion.core.decision import DecisionOutput, _to_decision, render_context
from tests.fakes import make_observation

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test feed</title>
  <item>
    <title>Major geopolitical event in region X</title>
    <link>https://example.com/a</link>
    <guid>https://example.com/a</guid>
    <description>Reported escalation near a shipping corridor.</description>
    <pubDate>Mon, 01 Sep 2026 00:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


def test_rss_adapter_normalizes_entries(tmp_path):
    path = tmp_path / "feed.xml"
    path.write_text(FEED, encoding="utf-8")

    observations = RSSAdapter(str(path), name="test").poll()

    assert len(observations) == 1
    obs = observations[0]
    assert obs.source == "test"
    assert "Major geopolitical event" in obs.content
    assert "shipping corridor" in obs.content
    assert obs.metadata["link"] == "https://example.com/a"
    assert obs.observed_at.year == 2026


def test_rss_ids_are_stable_across_polls(tmp_path):
    path = tmp_path / "feed.xml"
    path.write_text(FEED, encoding="utf-8")
    adapter = RSSAdapter(str(path), name="test")

    assert [o.id for o in adapter.poll()] == [o.id for o in adapter.poll()]


def test_create_work_without_objective_falls_back_to_no_action():
    parsed = DecisionOutput(action="create_work", reason="vague", objective=None)
    assert _to_decision(parsed).action == "no_action"


def test_render_context_includes_observations_and_state():
    text = render_context([make_observation()], [])
    assert "Major geopolitical event" in text
    assert "(empty)" in text


def test_unreadable_source_warns_instead_of_looking_quiet(tmp_path, caplog):
    """取得失敗を「変化なし」と誤認しないこと。"""
    adapter = RSSAdapter(str(tmp_path / "missing.xml"), name="broken")

    with caplog.at_level("WARNING", logger="aion.observation"):
        assert adapter.poll() == []

    assert "unreadable" in caplog.text
