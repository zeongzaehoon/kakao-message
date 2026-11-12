from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from kakaosender.adapters.accessibility import Node
from kakaosender.adapters.macos import MacDriver
from kakaosender.adapters.open_chats import OpenChatsBackend
from kakaosender.models import Cancelled, IntegrationError


class ImmediateEvent(Event):
    def wait(self, timeout=None):
        return self.is_set()


def changing_tree(*, persistent=False, error=-25202, duplicate=False):
    driver = object.__new__(MacDriver)
    driver.pid = 42
    nodes = {
        'window': Node('AXWindow', '테스트 대화', '_NS:443', 'window', 'window'),
        'old': Node('AXTextArea', '', '_NS:51', 'old', 'old'),
        'new': Node('AXTextArea', '', '_NS:51', 'new', 'new'),
        'duplicate': Node('AXTextArea', '', '_NS:51', 'duplicate', 'duplicate'),
        'send': Node('AXButton', '전송', '', 'send', 'send'),
    }
    reads = []
    generations = []

    def read(ref, attribute, unused):
        assert attribute == 'AXChildren'
        reads.append(ref)
        if ref == 'window':
            generations.append(1)
            if len(generations) == 1 or persistent:
                return 0, ['old', 'send']
            return 0, ['new', 'send'] + (['duplicate'] if duplicate else [])
        if ref == 'old':
            return error, None
        return -25205, None

    driver.ax = SimpleNamespace(AXUIElementCopyAttributeValue=read)
    driver._node = lambda ref: nodes[ref]
    driver.same_element = lambda a, b: a == b
    driver.current_roots = lambda: [nodes['window']]
    driver.read_value = lambda node: ''
    driver.can_write = lambda node: True
    driver.can_press = lambda node: True
    driver.photo_sheets = lambda chat: []
    driver.press = lambda node: pytest.fail('Lookup must never press a button')
    driver.set_value = lambda *args: pytest.fail('Lookup must never write text')
    return driver, nodes, reads, generations


def test_stale_descendant_is_reacquired_from_original_window():
    driver, nodes, reads, generations = changing_tree()
    editor = driver.one({'role': 'AXTextArea'}, ImmediateEvent(), nodes['window'])
    assert editor.key == 'new'
    assert len(generations) == 2
    assert reads.count('old') == 1


def test_persistent_invalid_branch_is_not_silently_ignored():
    driver, nodes, reads, generations = changing_tree(persistent=True)
    with pytest.raises(IntegrationError, match='-25202'):
        driver.one({'role': 'AXButton'}, ImmediateEvent(), nodes['window'])
    assert len(generations) == 3
    assert reads.count('old') == 3


def test_partial_matches_are_discarded_and_duplicates_in_fresh_tree_block_lookup():
    driver, nodes, reads, generations = changing_tree(duplicate=True)
    with pytest.raises(IntegrationError, match='2개'):
        driver.one({'role': 'AXTextArea'}, ImmediateEvent(), nodes['window'])
    assert len(generations) == 2


@pytest.mark.parametrize('error', [-25200, -25204, -25211])
def test_other_errors_are_not_retried(error):
    driver, nodes, reads, generations = changing_tree(error=error)
    with pytest.raises(IntegrationError, match=str(error)):
        driver.one({'role': 'AXTextArea'}, ImmediateEvent(), nodes['window'])
    assert len(generations) == 1


def test_cancel_during_retry_stops_before_second_read():
    driver, nodes, reads, generations = changing_tree()
    stop = ImmediateEvent()
    stop.wait = lambda timeout: stop.set()
    with pytest.raises(Cancelled):
        driver.one({'role': 'AXTextArea'}, stop, nodes['window'])
    assert len(generations) == 1


@pytest.mark.parametrize('change', ['native', 'name', 'role', 'identifier', 'key'])
def test_changed_parent_during_retry_is_never_rebound(change):
    driver, nodes, reads, generations = changing_tree()
    original = nodes['window']
    stop = ImmediateEvent()
    stop.wait = lambda timeout: nodes.update(window=replace(original, **{change: 'changed'}))
    with pytest.raises(IntegrationError, match='대상이 변경'):
        driver.one({'role': 'AXTextArea'}, stop, original)
    assert len(generations) == 1


def test_parent_is_checked_again_after_successful_traversal():
    driver, nodes, reads, generations = changing_tree()
    generations.append(1)  # Start with the valid descendants.
    original = nodes['window']
    read = driver.ax.AXUIElementCopyAttributeValue

    def replace_window_after_read(ref, attribute, unused):
        result = read(ref, attribute, unused)
        if ref == 'send':
            nodes['window'] = replace(original, name='다른 대화')
        return result

    driver.ax.AXUIElementCopyAttributeValue = replace_window_after_read
    with pytest.raises(IntegrationError, match='대상이 변경'):
        driver.one({'role': 'AXTextArea'}, ImmediateEvent(), original)


def composer_tree():
    driver, nodes, reads, _ = changing_tree()
    nodes.update({
        'history': Node('AXScrollArea', '', '_NS:29', 'history', 'history'),
        'area': Node('AXScrollArea', '', '_NS:47', 'area', 'area'),
    })
    tree = {'window': ['history', 'area', 'send'], 'area': ['new']}

    def read(ref, attribute, unused):
        assert attribute == 'AXChildren'
        reads.append(ref)
        if ref == 'history':
            pytest.fail('Composer lookup must not traverse changing message history')
        return (0, tree[ref]) if ref in tree else (-25205, None)

    driver.ax.AXUIElementCopyAttributeValue = read
    return driver, nodes, reads, tree


def test_prepare_reads_composer_without_traversing_message_history():
    driver, nodes, reads, tree = composer_tree()
    backend = OpenChatsBackend(driver, {})
    listing = backend.list_friends(ImmediateEvent())
    assert listing.friends[0].selectable
    backend.prepare(listing.friends[0], listing.scope, ImmediateEvent())
    assert backend.prepared == listing.friends[0].key
    assert set(reads) == {'window', 'area'}


@pytest.mark.parametrize('change', ['missing-area', 'missing-editor', 'missing-send', 'duplicate-editor', 'duplicate-send'])
def test_composer_lookup_fails_closed_on_missing_or_ambiguous_controls(change):
    driver, nodes, reads, tree = composer_tree()
    selectors = {'editor': {'role': 'AXTextArea', 'identifier': '_NS:51'},
                 'send_button': {'role': 'AXButton', 'name': '전송'}}
    if change == 'missing-area': tree['window'].remove('area')
    if change == 'missing-editor': tree['area'] = []
    if change == 'missing-send': tree['window'].remove('send')
    if change == 'duplicate-editor': tree['area'].append('duplicate')
    if change == 'duplicate-send':
        nodes['send2'] = replace(nodes['send'], native='send2', key='send2')
        tree['window'].append('send2')
    with pytest.raises(IntegrationError, match='하나로 식별'):
        driver.chat_controls(nodes['window'], selectors, ImmediateEvent())
    assert 'history' not in reads
