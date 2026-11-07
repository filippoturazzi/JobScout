import pytest

from jobscout.matching.terms import ExtractedProfile, profile_hash
from jobscout.models import UserPreferences
from jobscout.pipeline.conversation import (
    JUNIOR_EXCLUSIONS,
    Answer,
    Conversation,
    InvalidAnswerError,
    QuestionsPendingError,
    answer,
    current_question,
    from_preferences,
    full_text,
    pending,
    question_for,
    summary,
    title,
    to_preferences,
    widenings,
    with_reading,
    with_reading_error,
    with_refinement,
)

PARAGRAPH = "I want a junior AI engineer job working with Python and LangChain."


def reading(**kw) -> ExtractedProfile:
    kw.setdefault("terms", ["ai engineer", "python"])
    return ExtractedProfile(**kw)


def conv(**kw) -> Conversation:
    return with_reading(Conversation(paragraph=PARAGRAPH), reading(**kw))


def everything_stated(**kw) -> Conversation:
    values: dict[str, object] = {
        "seniority": ["junior"],
        "stated_work_modes": ["hybrid"],
        "stated_regions": ["Brazil", "Recife"],
        "required_skills": ["python"],
    }
    values.update(kw)
    return conv(**values)


def test_no_reading_asks_only_for_the_role():
    c = Conversation(paragraph=PARAGRAPH)
    assert pending(c) == ["role"]


def test_no_terms_asks_only_for_the_role():
    c = conv(terms=[], suggested_skills=["python"])
    assert pending(c) == ["role"]
    question = current_question(c)
    assert question is not None
    assert question.id == "role"
    assert question.typed is True
    assert question.options == []


def test_the_role_is_not_answerable():
    with pytest.raises(InvalidAnswerError):
        answer(conv(terms=[]), "role", Answer(choice="ai engineer"))


def test_a_paragraph_that_states_everything_asks_nothing():
    c = everything_stated()
    assert pending(c) == []
    assert current_question(c) is None


def test_questions_come_in_order_with_a_counter():
    c = conv(suggested_skills=["python", "rag"])
    assert pending(c) == ["level", "work_modes", "country", "skills"]
    question = current_question(c)
    assert question is not None
    assert (question.id, question.number, question.position, question.total) == (
        "level",
        2,
        1,
        4,
    )
    assert [o.choice for o in question.options] == ["intern", "junior", "mid", "senior", "any"]
    assert question.multi is False

    c = answer(c, "level", Answer(choice="junior"))
    question = current_question(c)
    assert question is not None
    assert (question.id, question.position, question.total) == ("work_modes", 2, 4)
    assert question.multi is True
    assert [o.choice for o in question.options] == ["remote", "hybrid", "onsite", "any"]
    assert c.asked == ["level"]


def test_skills_are_offered_from_the_suggestions():
    c = conv(
        seniority=["junior"],
        stated_work_modes=["remote"],
        stated_regions=["Brazil"],
        suggested_skills=["python", "rag"],
    )
    question = current_question(c)
    assert question is not None
    assert question.id == "skills"
    assert question.multi is True
    assert [(o.choice, o.value) for o in question.options] == [
        ("skill", "python"),
        ("skill", "rag"),
    ]
    c = answer(c, "skills", Answer(choice="pick", values=[]))
    assert pending(c) == []


def test_skills_are_not_asked_without_suggestions():
    c = conv(seniority=["junior"], stated_work_modes=["remote"], stated_regions=["Brazil"])
    assert pending(c) == []


def test_remote_only_asks_where_you_can_work_from():
    c = conv(seniority=["junior"], stated_work_modes=["remote"], stated_regions=["Brasil"])
    # A stated country already answers the location.
    assert pending(c) == []

    c = conv(seniority=["junior"], stated_work_modes=["remote"])
    question = current_question(c)
    assert question is not None
    assert question.id == "location"
    assert question.number == 4
    assert [(o.choice, o.value) for o in question.options] == [
        ("anywhere", None),
        ("other", None),
    ]

    c = answer(c, "location", Answer(choice="country", values=["Brasil"]))
    assert c.answers["location"] == Answer(choice="country", values=["Brazil"])
    assert pending(c) == []


def test_remote_only_offers_abroad_when_the_home_country_is_known():
    c = conv(seniority=["junior"], stated_work_modes=["remote"], stated_regions=["Brazil"])
    c = answer(c, "location", Answer(choice="anywhere"))
    reopened = question_for(c, "location")  # from the summary's edit icon
    assert [(o.choice, o.value) for o in reopened.options] == [
        ("country", "Brazil"),
        ("anywhere", None),
        ("abroad", "Brazil"),
        ("other", None),
    ]


def test_hybrid_asks_the_country_then_the_city():
    c = conv(seniority=["junior"], stated_work_modes=["hybrid"])
    question = current_question(c)
    assert question is not None
    assert question.id == "country"
    assert [o.choice for o in question.options] == ["anywhere", "other"]

    c = answer(c, "country", Answer(choice="country", values=["brazil"]))
    question = current_question(c)
    assert question is not None
    assert question.id == "city"
    assert question.number == 4
    assert [(o.choice, o.value) for o in question.options] == [
        ("anywhere", "Brazil"),
        ("other", None),
    ]

    c = answer(c, "city", Answer(choice="city", values=["Recife"]))
    assert pending(c) == []


def test_country_and_city_share_one_number_in_the_counter():
    c = conv(seniority=["junior"], stated_work_modes=["hybrid"])
    c = answer(c, "country", Answer(choice="country", values=["Brazil"]))
    question = current_question(c)
    assert question is not None
    assert (question.position, question.total) == (1, 1)


def test_dont_mind_on_work_mode_still_asks_the_city():
    c = conv(seniority=["junior"], stated_regions=["Brazil"])
    c = answer(c, "work_modes", Answer(choice="any"))
    assert pending(c) == ["city"]


def test_a_clicked_answer_beats_a_new_reading():
    c = conv(seniority=["junior"], stated_regions=["Brazil"])
    c = answer(c, "work_modes", Answer(choice="pick", values=["remote"]))
    c = with_refinement(c, "Hybrid is fine too.")
    c = with_reading(c, reading(seniority=["senior"], stated_work_modes=["hybrid"]))
    s = summary(c)
    assert s.work_modes == ["remote"]
    assert s.level == "senior"


def test_a_reading_that_adds_hybrid_asks_for_the_city():
    c = conv(seniority=["junior"], stated_work_modes=["remote"], stated_regions=["Brazil"])
    assert pending(c) == []
    c = with_refinement(c, "Hybrid in Brazil works too.")
    c = with_reading(
        c,
        reading(
            seniority=["junior"],
            stated_work_modes=["remote", "hybrid"],
            stated_regions=["Brazil"],
        ),
    )
    assert pending(c) == ["city"]


def test_changing_the_country_drops_the_city():
    c = conv(seniority=["junior"], stated_work_modes=["hybrid"])
    c = answer(c, "country", Answer(choice="country", values=["Brazil"]))
    c = answer(c, "city", Answer(choice="city", values=["Recife"]))
    same = answer(c, "country", Answer(choice="country", values=["Brasil"]))
    assert "city" in same.answers
    other = answer(c, "country", Answer(choice="country", values=["Portugal"]))
    assert "city" not in other.answers
    assert pending(other) == ["city"]


def test_unknown_country_is_rejected():
    c = conv(seniority=["junior"], stated_work_modes=["hybrid"])
    with pytest.raises(InvalidAnswerError):
        answer(c, "country", Answer(choice="country", values=["Atlantis"]))
    with pytest.raises(InvalidAnswerError):
        answer(c, "country", Answer(choice="country", values=["Brazil", "Portugal"]))


def test_abroad_without_a_home_country_is_rejected():
    c = conv(seniority=["junior"], stated_work_modes=["remote"])
    with pytest.raises(InvalidAnswerError):
        answer(c, "location", Answer(choice="abroad"))


def test_invalid_choices_are_rejected():
    c = conv()
    with pytest.raises(InvalidAnswerError):
        answer(c, "level", Answer(choice="guru"))
    with pytest.raises(InvalidAnswerError):
        answer(c, "work_modes", Answer(choice="pick", values=[]))
    with pytest.raises(InvalidAnswerError):
        answer(c, "work_modes", Answer(choice="pick", values=["moon"]))
    with pytest.raises(InvalidAnswerError):
        answer(c, "city", Answer(choice="city", values=["  "]))
    with pytest.raises(InvalidAnswerError):
        answer(c, "skills", Answer(choice="any"))


def test_answering_never_mutates_and_unconfirms():
    c = everything_stated().model_copy(update={"confirmed": True})
    after = answer(c, "level", Answer(choice="mid"))
    assert c.answers == {}
    assert c.asked == []
    assert c.confirmed is True
    assert after.confirmed is False
    assert after.asked == ["level"]
    again = answer(after, "level", Answer(choice="senior"))
    assert again.asked == ["level"]


def test_refinements_join_the_paragraph_and_unconfirm():
    c = everything_stated().model_copy(update={"confirmed": True})
    refined = with_refinement(c, "Also Go.")
    assert full_text(refined) == f"{PARAGRAPH}\n\nAlso Go."
    assert refined.confirmed is False
    assert c.refinements == []


def test_a_reading_error_is_kept_until_a_reading_arrives():
    c = with_reading_error(Conversation(paragraph=PARAGRAPH), "rate limited")
    assert c.reading_error == "rate limited"
    c = with_reading(c, reading())
    assert c.reading_error is None


def test_the_conversation_round_trips_through_json():
    c = everything_stated()
    c = answer(c, "level", Answer(choice="mid"))
    c = with_refinement(c, "Also Go.")
    assert Conversation.model_validate(c.model_dump(mode="json")) == c


def test_junior_excludes_senior_titles():
    assert JUNIOR_EXCLUSIONS == ("senior", "sr", "lead", "staff", "principal")
    prefs = to_preferences(everything_stated(excluded_keywords=["Senior", "php"]))
    assert prefs["seniority"] == ["junior"]
    assert prefs["excluded_keywords"] == ["Senior", "php", "sr", "lead", "staff", "principal"]

    mid = to_preferences(answer(everything_stated(), "level", Answer(choice="mid")))
    assert mid["seniority"] == ["mid"]
    assert mid["excluded_keywords"] == []

    any_level = to_preferences(answer(everything_stated(), "level", Answer(choice="any")))
    assert any_level["seniority"] == []


def test_abroad_stores_home_as_excluded():
    c = conv(seniority=["junior"], stated_work_modes=["remote"], stated_regions=["Brazil"])
    c = answer(c, "location", Answer(choice="abroad"))
    prefs = to_preferences(c)
    assert prefs["regions"] == []
    assert prefs["excluded_regions"] == ["Brazil"]
    assert prefs["city"] is None
    s = summary(c)
    assert (s.country, s.abroad_from) == (None, "Brazil")


def test_remote_only_unanswered_keeps_the_stated_countries():
    c = conv(
        seniority=["junior"],
        stated_work_modes=["remote"],
        stated_regions=["Brasil", "Portugal", "Recife"],
    )
    prefs = to_preferences(c)
    assert prefs["regions"] == ["Brazil", "Portugal"]
    assert prefs["city"] is None


def test_city_is_stored_with_its_country():
    prefs = to_preferences(everything_stated())
    assert prefs["regions"] == ["Brazil"]
    assert prefs["city"] == "Recife"
    assert prefs["work_modes"] == ["hybrid"]
    assert prefs["search_terms"] == ["ai engineer", "python"]
    assert prefs["required_skills"] == ["python"]
    assert prefs["profile_summary"] == PARAGRAPH
    assert prefs["profile_hash"] == profile_hash(PARAGRAPH)


def test_anywhere_in_the_country_stores_no_city():
    c = conv(seniority=["junior"], stated_work_modes=["onsite"], stated_regions=["Brazil"])
    c = answer(c, "city", Answer(choice="anywhere"))
    prefs = to_preferences(c)
    assert (prefs["regions"], prefs["city"]) == (["Brazil"], None)


def test_to_preferences_refuses_while_questions_are_pending():
    with pytest.raises(QuestionsPendingError):
        to_preferences(conv())


def test_widenings_offer_only_what_changes_something():
    assert [w[0] for w in widenings(everything_stated())] == [
        "include_remote",
        "whole_country",
        "any_level",
    ]
    include_remote = widenings(everything_stated())[0]
    assert include_remote == (
        "include_remote",
        "work_modes",
        Answer(choice="pick", values=["hybrid", "remote"]),
    )

    onsite = everything_stated(stated_work_modes=["onsite"])
    assert [w[0] for w in widenings(onsite)][:2] == ["include_remote", "include_hybrid"]

    wide = answer(everything_stated(), "work_modes", Answer(choice="any"))
    wide = answer(wide, "city", Answer(choice="anywhere"))
    wide = answer(wide, "level", Answer(choice="any"))
    assert widenings(wide) == []


def test_title_reads_level_and_role():
    assert title(everything_stated()) == "Junior AI Engineer"
    assert title(answer(everything_stated(), "level", Answer(choice="any"))) == "AI Engineer"
    assert title(conv(terms=["ml ops engineer"])) == "ML Ops Engineer"


def test_title_falls_back_to_the_paragraph():
    long = Conversation(
        paragraph="Looking for something interesting in data with a friendly team please"
    )
    assert title(long) == "Looking for something interesting in data"
    huge = Conversation(paragraph="Supercalifragilisticexpialidocious " * 4)
    assert len(title(huge)) <= 60


@pytest.mark.parametrize(
    "build",
    [
        everything_stated,
        lambda: answer(
            conv(seniority=["junior"], stated_work_modes=["remote"], stated_regions=["Brazil"]),
            "location",
            Answer(choice="abroad"),
        ),
        lambda: answer(
            answer(
                conv(seniority=["mid"], stated_work_modes=["remote"]),
                "location",
                Answer(choice="anywhere"),
            ),
            "skills",
            Answer(choice="pick", values=[]),
        ),
        lambda: answer(
            answer(conv(), "level", Answer(choice="any")),
            "work_modes",
            Answer(choice="any"),
        ),
    ],
)
def test_from_preferences_round_trips_through_to_preferences(build):
    c = build()
    if pending(c) == ["country"]:
        c = answer(c, "country", Answer(choice="anywhere"))
    prefs = to_preferences(c)
    stored = UserPreferences(user_id=1, search_id=1, **prefs)
    rebuilt = from_preferences(stored)
    assert rebuilt.confirmed is True
    assert pending(rebuilt) == []
    assert to_preferences(rebuilt) == prefs
