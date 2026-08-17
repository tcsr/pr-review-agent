from app.llm.fake import FakeLLMAdapter
from app.llm.base import Message


def test_scripted_responses_in_order():
    llm = FakeLLMAdapter(responses=["first", "second"])
    r1 = llm.complete("sys", [Message(role="user", content="a")], max_tokens=100)
    r2 = llm.complete("sys", [Message(role="user", content="b")], max_tokens=100)
    r3 = llm.complete("sys", [Message(role="user", content="c")], max_tokens=100)
    assert (r1.text, r2.text, r3.text) == ("first", "second", "second")


def test_responder_callable_and_calls_recorded():
    llm = FakeLLMAdapter(responder=lambda system, msgs: msgs[-1].content.upper())
    r = llm.complete("sys", [Message(role="user", content="hi")], max_tokens=10)
    assert r.text == "HI"
    assert llm.calls[0][0] == "sys"


def test_count_tokens():
    llm = FakeLLMAdapter(responses=["x"])
    assert llm.count_tokens("one two three") == 3
