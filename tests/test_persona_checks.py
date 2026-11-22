import asyncio
import json

from botucha.persona_checks import (
    caricature_flags, jargon_in, judge, judge_messages, overused, parse_verdict, repeated_phrases, summarize,
)
from tests.fakes import FakeLLM

STEMS = ["bajer", "nax", "hodlin", "pump"]


def test_jargon_matches_inflected_forms_at_word_start():
    assert jargon_in("nu bajeris, nax", STEMS) == ["bajer", "nax"]
    assert jargon_in("tie bajerai vėl", STEMS) == ["bajer"]


def test_jargon_ignores_stem_inside_a_word():
    assert jargon_in("čia anax", STEMS) == []


def test_one_jargon_word_per_reply_is_fine():
    assert caricature_flags(["geras bajeris"], STEMS) == []


def test_two_jargon_words_in_one_reply_is_caricature():
    assert caricature_flags(["nax, geras bajeris"], STEMS) == ["caricature: nax, bajer"]


def test_serious_reply_allows_no_jargon():
    assert caricature_flags(["čia pumpas, GPM 15 %"], STEMS, serious=True) == ["jargon in serious: pump"]


def test_repeated_phrase_across_prompts_is_found():
    replies = {"leverage": ["nu aš tau ne mama, bet nuomos pinigų ten nekišk."],
               "nuomos": ["aš tau ne mama, bet nuomos pinigų ten nekišk"],
               "gta": ["dar nepasirodė"]}
    found = repeated_phrases(replies, n=5)
    assert found and found[0][1] == ["leverage", "nuomos"]
    assert "aš tau ne mama bet" in found[0][0]


def test_repeated_phrase_within_one_prompt_does_not_count():
    assert repeated_phrases({"a": ["vienas du trys keturi penki", "vienas du trys keturi penki"]}, n=5) == []


def test_overused_counts_prompts_not_occurrences():
    replies = {"a": ["bajeris bajeris"], "b": ["tu bajeris"], "c": ["koks bajeris"], "d": ["nax"]}
    assert overused(replies, STEMS, min_count=3) == [("bajer", 3)]


def test_judge_messages_carry_persona_rubric_and_replies():
    msgs = judge_messages("PERSONA TEKSTAS", "botucha kaip sekasi", ["normaliai"], "atsako trumpai")
    blob = json.dumps(msgs, ensure_ascii=False)
    assert "PERSONA TEKSTAS" in blob and "botucha kaip sekasi" in blob and "normaliai" in blob and "atsako trumpai" in blob


def test_parse_verdict_reads_score_atoms_and_feedback():
    v = parse_verdict(json.dumps({"atoms": [{"text": "normaliai", "ok": True, "why": ""},
                                            {"text": "investuoju į ETF kasdien", "ok": False, "why": "treideris"}],
                                  "score": 4, "feedback": "gerai, bet"}))
    assert v.score == 4 and v.error is None and v.feedback == "gerai, bet"
    assert [a.text for a in v.ooc] == ["investuoju į ETF kasdien"]


def test_parse_verdict_clamps_score():
    assert parse_verdict('{"atoms": [], "score": 9, "feedback": ""}').score == 5
    assert parse_verdict('{"atoms": [], "score": -2, "feedback": ""}').score == 1


def test_parse_verdict_garbage_is_an_error_not_a_crash():
    v = parse_verdict("nu ne json")
    assert v.score is None and v.error


def test_judge_uses_json_mode_and_parses():
    llm = FakeLLM(['{"atoms": [{"text": "x", "ok": true, "why": ""}], "score": 5, "feedback": "ok"}'])
    v = asyncio.run(judge(llm, "P", "klausimas", ["x"], ""))
    assert v.score == 5 and llm.calls[0]["fmt_json"] is True


def test_judge_failure_becomes_an_error_verdict():
    v = asyncio.run(judge(FakeLLM([RuntimeError("ollama down")]), "P", "k", ["x"], ""))
    assert v.score is None and "ollama down" in v.error


def test_summary_averages_by_category():
    rows = [{"category": "kalba", "score": 4, "ooc": 0, "atoms": 2},
            {"category": "kalba", "score": 2, "ooc": 1, "atoms": 2},
            {"category": "ribos", "score": None, "ooc": 0, "atoms": 0}]
    s = summarize(rows)
    assert s["by_category"]["kalba"] == 3.0
    assert s["by_category"]["ribos"] is None
    assert s["score"] == 3.0 and s["ooc"] == 1 and s["atoms"] == 4 and s["judge_failed"] == 1


def test_judge_is_told_the_real_group_members():
    msgs = judge_messages("P", "k", ["Degenier sako laikys"], "", members=["Degenier", "rowhammer"])
    assert "Degenier, rowhammer" in msgs[1]["content"]


def test_judge_retries_once_after_a_failed_generation():
    llm = FakeLLM([RuntimeError("token repeat limit reached"), '{"atoms": [], "score": 4, "feedback": "ok"}'])
    v = asyncio.run(judge(llm, "P", "k", ["x"], ""))
    assert v.score == 4 and len(llm.calls) == 2
