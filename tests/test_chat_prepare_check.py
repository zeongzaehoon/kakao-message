import json
from threading import Event

import pytest

from kakaosender.adapters.open_chats import OpenChatsBackend
from kakaosender.open_chat_checks import run_chat_prepare_check
from test_sender import FakeDriver


@pytest.mark.parametrize('change', ['valid', 'confirmation', 'pid', 'key', 'name', 'draft', 'attachment'])
def test_explicit_chat_preflight_is_read_only_and_preserves_drafts(tmp_path, monkeypatch, change):
    driver = FakeDriver()
    listing = OpenChatsBackend(driver, {}).list_friends(Event())
    friend = listing.friends[0]
    target = {'pid': driver.pid, 'key': friend.key, 'name': friend.name, 'confirmed_chat': True}
    if change == 'confirmation': target['confirmed_chat'] = False
    if change == 'pid': target['pid'] += 1
    if change == 'key': target['key'] = 'other-window'
    if change == 'name': target['name'] = '다른 대상'
    if change == 'draft': driver.value = '기존 초안'
    if change == 'attachment': driver.photo_sheets = lambda node: [object()]
    before = driver.value
    monkeypatch.setattr('kakaosender.adapters.native_driver', lambda: driver)
    target_path = tmp_path / 'target.json'
    target_path.write_text(json.dumps(target), encoding='utf-8')
    report = tmp_path / 'result.json'
    status = run_chat_prepare_check(report, target_path)
    result = json.loads(report.read_text(encoding='utf-8'))
    assert status == (0 if change == 'valid' else 1)
    assert result['ok'] is (change == 'valid')
    assert result['typed'] == result['sent'] == 0
    assert driver.value == before
    assert not driver.writes and not driver.presses
