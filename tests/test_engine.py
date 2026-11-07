from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest

from kakaosender.engine import execute
from kakaosender.models import Friend, Plan, Cancelled, UncertainSend
from kakaosender.storage import Journal


class Stub:
    is_demo = False

    def __init__(self):
        self.prepared = []
        self.sent = []
        self.fail_prepare = False
        self.fail_send = False
        self.cancel_prepare = False

    def finish_recipient(self, friend, scope, stop):
        pass

    def prepare(self, friend, scope, stop):
        self.prepared.append(friend.key)
        if self.fail_prepare:
            raise RuntimeError("wrong chat")
        if self.cancel_prepare:
            stop.set()

    def send(self, friend, message, scope, stop):
        self.sent.append((friend.key, message))
        if self.fail_send:
            raise UncertainSend("button result unknown")


@pytest.fixture
def journal(tmp_path):
    value = Journal(tmp_path / "journal.db")
    yield value
    value.close()


def plan(live=True, message="안녕 👋\n둘째 줄", interval=0):
    return Plan((Friend("a", "가"), Friend("b", "나")), message, "account-1", live, interval)


def test_dry_run_never_calls_send_or_reserves(journal):
    backend = Stub()
    result = execute(plan(False), backend, journal, Event(), lambda x: None)
    assert [x.state for x in result] == ["checked", "checked"]
    assert not backend.sent
    assert journal.reserve("account-1", "a", plan().message)


def test_duplicate_persists_across_new_journal(tmp_path):
    file = tmp_path / "journal.db"
    backend = Stub()
    first = Journal(file)
    execute(plan(), backend, first, Event(), lambda x: None)
    first.close()
    second = Journal(file)
    result = execute(plan(), backend, second, Event(), lambda x: None)
    second.close()
    assert [x.state for x in result] == ["duplicate", "duplicate"]
    assert len(backend.sent) == 2
    assert backend.sent[0][1] == "안녕 👋\n둘째 줄"


def test_ambiguous_send_blocks_retry_and_remaining(journal):
    backend = Stub()
    backend.fail_send = True
    result = execute(plan(), backend, journal, Event(), lambda x: None)
    assert [x.state for x in result] == ["uncertain"]
    assert not journal.reserve("account-1", "a", plan().message)
    assert len(backend.sent) == 1


def test_failed_preflight_is_retryable(journal):
    backend = Stub()
    backend.fail_prepare = True
    result = execute(plan(), backend, journal, Event(), lambda x: None)
    assert result[0].state == "failed"
    assert journal.reserve("account-1", "a", plan().message)
    assert not backend.sent


def test_cancel_after_prepare_releases_reservation(journal):
    backend = Stub()
    backend.cancel_prepare = True
    result = execute(plan(), backend, journal, Event(), lambda x: None)
    assert result[0].state == "cancelled"
    assert not backend.sent
    assert journal.reserve("account-1", "a", plan().message)


def test_stop_before_batch_does_not_touch_client(journal):
    backend = Stub()
    event = Event()
    event.set()
    execute(plan(), backend, journal, event, lambda x: None)
    assert not backend.prepared


def test_interrupted_delay_skips_next_person(journal):
    backend = Stub()
    event = Event()
    execute(plan(interval=60), backend, journal, event, lambda x: event.set())
    assert len(backend.sent) == 1


def test_pending_crash_record_is_not_resent(journal):
    journal.reserve("account-1", "a", plan().message)
    backend = Stub()
    execute(plan(), backend, journal, Event(), lambda x: None)
    assert [x[0] for x in backend.sent] == ["b"]


def test_concurrent_reservation_only_one_wins(tmp_path):
    path = tmp_path / "journal.db"
    Journal(path).close()
    def reserve(_):
        journal = Journal(path)
        try:
            return journal.reserve("account", "friend", "message")
        finally:
            journal.close()
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 1


def test_account_and_message_are_separate(journal):
    assert journal.reserve("a", "f", "x")
    assert journal.reserve("b", "f", "x")
    assert journal.reserve("a", "f", "y")


@pytest.mark.parametrize("recipients,message", [
    ((), "hello"), ((Friend("a", "가"),), "  "),
    ((Friend("a", "가"), Friend("a", "나")), "hello"),
    ((Friend("a", "가", False),), "hello"),
    ((Friend("a", "가"),), "x" * 10001),
])
def test_invalid_plan(recipients, message):
    with pytest.raises(ValueError):
        Plan(recipients, message, "scope").validate()


def test_close_only_after_confirmed_send_and_before_next_room(journal):
    backend = Stub()
    events = []
    backend.send = lambda friend, *args: events.append(('send', friend.key))
    backend.finish_recipient = lambda friend, *args: events.append(('close', friend.key))
    results = execute(plan(), backend, journal, Event(), lambda x: None)
    assert events == [('send', 'a'), ('close', 'a'), ('send', 'b'), ('close', 'b')]
    assert [r.state for r in results] == ['submitted', 'submitted']


def test_close_failure_keeps_submitted_journal_and_stops_batch(journal):
    backend = Stub()
    def fail(*args):
        raise RuntimeError('close failed')
    backend.finish_recipient = fail
    results = execute(plan(), backend, journal, Event(), lambda x: None)
    assert len(results) == 1 and results[0].state == 'submitted'
    assert '창 닫기' in results[0].detail
    assert journal.state('account-1', 'a', plan().message) == 'submitted'
    assert [key for key, _ in backend.sent] == ['a']


@pytest.mark.parametrize('mode', ['dry', 'uncertain', 'duplicate'])
def test_dry_uncertain_duplicate_never_close(journal, mode):
    backend = Stub()
    backend.finish_recipient = lambda *args: pytest.fail('must leave window unchanged')
    if mode == 'uncertain': backend.fail_send = True
    if mode == 'duplicate':
        for friend in plan().recipients:
            journal.reserve(plan().scope, friend.key, plan().message)
    execute(plan(live=mode != 'dry'), backend, journal, Event(), lambda x: None)
