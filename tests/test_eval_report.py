import asyncio

from botucha.evaluation import judge_results, render_report
from tests.fakes import FakeLLM


def _results():
    return [
        {"name": "leverage", "text": "botucha 3x?", "replies": ["aš tau ne mama, bet nuomos pinigų ten nekišk"],
         "secs": 4.0, "problems": [], "category": "pinigai", "rubric": "", "serious": False},
        {"name": "nuomos", "text": "botucha nuoma į opcionus?", "replies": ["nax bajeris, aš tau ne mama, bet nuomos pinigų"],
         "secs": 3.0, "problems": [], "category": "pinigai", "rubric": "", "serious": False},
    ]


def test_report_flags_caricature_repeats_and_overuse_without_a_judge():
    md = render_report("gemma", _results(), stems=["bajer", "nax"], judge_model=None)
    assert "caricature: nax, bajer" in md
    assert "aš tau ne mama bet" in md and "leverage, nuomos" in md
    assert "judge" not in md.lower().split("## summary")[1]  # no judge line when none ran


def test_judge_results_attach_verdicts_and_report_shows_them():
    llm = FakeLLM([
        '{"atoms": [{"text": "nuomos nekišk", "ok": true, "why": ""}], "score": 4, "feedback": "gerai"}',
        '{"atoms": [{"text": "nax bajeris", "ok": false, "why": "karikatūra"}], "score": 2, "feedback": "per daug žargono"}',
    ])
    rs = asyncio.run(judge_results(llm, "PERSONA", _results()))
    assert [r["verdict"].score for r in rs] == [4, 2]
    md = render_report("gemma", rs, stems=["bajer", "nax"], judge_model="qwen")
    assert "judge: 2/5" in md and "per daug žargono" in md and "nax bajeris" in md and "karikatūra" in md
    assert "3.0/5" in md and "OOC 1/2" in md and "pinigai 3.0" in md


def test_prompt_that_asks_for_jargon_is_not_flagged_as_caricature():
    r = {**_results()[1], "jargon_ok": True}
    md = render_report("gemma", [r], stems=["bajer", "nax"], judge_model=None)
    assert "caricature" not in md


def test_local_prompts_override_by_name_add_new_ones_and_replace_stems(tmp_path):
    from botucha.evaluation import load_spec
    (tmp_path / "prompts.toml").write_text(
        '[[prompt]]\nname = "a"\ntext = "viesas"\n\n[[prompt]]\nname = "b"\ntext = "b"\n\n'
        '[caricature]\nstems = ["x"]\n\n[memory]\nqueries = ["q"]\n')
    (tmp_path / "prompts.local.toml").write_text(
        '[[prompt]]\nname = "a"\ntext = "privatus"\nrubric = "r"\n\n[[prompt]]\nname = "c"\ntext = "c"\n\n'
        '[caricature]\nstems = ["y"]\n')
    spec = load_spec(tmp_path / "prompts.toml")
    assert [(p["name"], p["text"]) for p in spec["prompt"]] == [("a", "privatus"), ("b", "b"), ("c", "c")]
    assert spec["caricature"]["stems"] == ["y"] and spec["memory"]["queries"] == ["q"]


def test_without_a_local_file_the_spec_is_the_public_one(tmp_path):
    from botucha.evaluation import load_spec
    (tmp_path / "prompts.toml").write_text('[[prompt]]\nname = "a"\ntext = "t"\n')
    assert [p["name"] for p in load_spec(tmp_path / "prompts.toml")["prompt"]] == ["a"]
