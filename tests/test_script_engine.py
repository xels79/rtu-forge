import ast
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from rich.console import Console

from rtuforge.commands import CommandContext, execute_command, run_script_lines
from rtuforge.config import load_config
from rtuforge.crc import append_crc
from rtuforge.i18n import SUPPORTED_LANGUAGES, command_help
from rtuforge.script_engine import LastResponse, ScriptError, compile_script, evaluate, parse_expression
from rtuforge.scripts import ScriptStore
from rtuforge.transport import Exchange


@pytest.fixture
def ctx(tmp_path):
    config = load_config(Path('config.ini'))
    config['ui']['language'] = 'en'
    config['runtime']['inter_command_delay_ms'] = '0'
    config['runtime']['clean_output'] = 'true'
    transport = Mock(connected=True)
    return CommandContext(tmp_path / 'config.ini', config,
                          ScriptStore(tmp_path / 'scripts.ini'), transport,
                          Console(file=StringIO(), record=True, width=180))


@pytest.mark.parametrize('expression', [
    '100 == 100', '0xFF == 255', '1 != 2', '1 < 2', '1 <= 1', '2 > 1', '2 >= 2',
    'true and not false', 'false or true', '(3 & 2) == 2', '(1 | 2) == 3',
    '(3 ^ 1) == 2', '(1 << 3) == 8', '(8 >> 2) == 2', '1 < 2 < 3',
    'true or last.reg[0] == 1', 'not (false and last.timeout)',
])
def test_expressions(expression):
    assert evaluate(parse_expression(expression), None)


@pytest.mark.parametrize('expression', [
    '', 'last.reg[0] ==', '__import__("os")', 'last.__class__', 'last.reg',
    'last.byte[-1]', 'last.byte[1:2]', 'last.byte[true]', 'last.reg[0].real',
    '[x for x in []]', '"text"', '1.5', 'True', 'None', 'lambda: 1',
    '(x := 1)', '1 + 2', '2 ** 8', '{1: 2}', '[1]', 'last.timeout()',
])
def test_reject_python(expression):
    with pytest.raises(ScriptError):
        parse_expression(expression)


@pytest.mark.parametrize(('lines', 'key', 'line'), [
    (['label a', 'label a'], 'duplicate_label', 2),
    (['goto missing'], 'unknown_label', 1),
    (['label'], 'invalid_label', 1),
    (['goto'], 'invalid_label', 1),
    (['label 1bad'], 'invalid_label', 1),
    (['label a b'], 'invalid_label', 1),
    (['else'], 'unmatched_else', 1),
    (['end if'], 'unmatched_end_if', 1),
    (['if true', 'else', 'else', 'end if'], 'duplicate_else', 3),
    (['if true'], 'missing_end_if', 1),
    (['if', 'end if'], 'invalid_expression', 1),
])
def test_compile_errors_before_commands(ctx, lines, key, line):
    with pytest.raises(ScriptError) as caught:
        compile_script(lines)
    assert caught.value.key == 'script_' + key
    assert caught.value.line == line
    with pytest.raises(ValueError, match='broken'):
        run_script_lines(ctx, ['send 05', *lines], source='broken')
    ctx.transport.exchange.assert_not_called()
    ctx.transport.connect.assert_not_called()


def test_branches_forward_goto_and_order(ctx, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr('rtuforge.commands.time.sleep', sleep)
    run_script_lines(ctx, [
        'goto start', 'pause 99', 'label start', 'if true', 'if false',
        'pause 98', 'else', 'pause 1', 'end if', 'else', 'pause 97', 'end if',
        'if false', 'pause 96', 'end if', 'pause 2',
    ], source='branches')
    assert [c.args[0] for c in sleep.call_args_list] == [.001, .002]


def test_last_fields_and_unavailable():
    last = LastResponse.from_rx(append_crc(bytes.fromhex('05 03 04 00 02 FF FF')))
    for expr in ['last.reg[0] == 2', 'last.reg[1] == 65535', 'last.byte[0] == 5',
                 'last.rx_len == 9', 'last.address == 5', 'last.function == 3',
                 'not last.timeout', 'last.exception == 0']:
        assert evaluate(parse_expression(expr), last)
    for expr in ['last.reg[2]', 'last.byte[9]']:
        with pytest.raises(ScriptError, match='script_unavailable'):
            evaluate(parse_expression(expr), last)
    timeout = LastResponse.from_rx(b'')
    assert evaluate(parse_expression('last.timeout and last.rx_len == 0'), timeout)
    with pytest.raises(ScriptError):
        evaluate(parse_expression('last.address'), timeout)
    exception = LastResponse.from_rx(append_crc(bytes.fromhex('05 83 02')))
    assert evaluate(parse_expression('last.function == 0x83 and last.exception == 2'), exception)
    with pytest.raises(ScriptError):
        evaluate(parse_expression('last.reg[0]'), exception)


POLLING = [
    'send 05 06 00 0F 00 1E', 'label wait_b', 'pause 100',
    'send 05 03 00 0C 00 01', 'if last.timeout', 'goto wait_b', 'end if',
    'if (last.reg[0] & 0x0002) != 0', 'goto wait_b', 'end if',
    'send 05 03 00 0F 00 01',
]


@pytest.mark.parametrize('count', [2, 1500])
def test_polling_no_stack_growth_clean_output_and_delays(ctx, monkeypatch, count):
    responses = [bytes.fromhex('05 06 00 0F 00 1E'), b'',
                 *([bytes.fromhex('05 03 02 00 02')] * count),
                 bytes.fromhex('05 03 02 00 00'), bytes.fromhex('05 03 02 00 1E')]
    def exchange(tx):
        rx = responses.pop(0)
        return Exchange(tx=append_crc(tx), rx=append_crc(rx) if rx else b'', elapsed_ms=1)
    ctx.transport.exchange.side_effect = exchange
    ctx.config['runtime']['inter_command_delay_ms'] = '7'
    sleep = Mock()
    monkeypatch.setattr('rtuforge.commands.time.sleep', sleep)
    ctx.scripts.set('ponic-test', POLLING)
    execute_command(ctx, 'run script ponic-test -r')
    assert not responses
    calls = ctx.transport.exchange.call_args_list
    assert len(calls) == count + 4
    assert calls[-1].args[0] == bytes.fromhex('05 03 00 0F 00 01')
    delays = [call.args[0] for call in sleep.call_args_list]
    assert delays.count(.1) == count + 2
    assert delays.count(.007) == 2 * count + 5
    text = ctx.console.export_text()
    assert 'goto' not in text and 'if ' not in text and 'TX' not in text
    assert '05 03 02 00 00' in text


def test_linear_delay_compatibility(ctx, monkeypatch):
    ctx.config['runtime']['inter_command_delay_ms'] = '7'
    sleep = Mock()
    monkeypatch.setattr('rtuforge.commands.time.sleep', sleep)
    run_script_lines(ctx, ['pause 1', 'pause 2', 'pause 3'], source='linear')
    assert [c.args[0] for c in sleep.call_args_list] == [.001, .007, .002, .007, .003]


def test_nested_labels_and_shared_response(ctx):
    rx = append_crc(bytes.fromhex('05 03 02 00 02'))
    ctx.transport.exchange.return_value = Exchange(tx=b'\x05', rx=rx, elapsed_ms=1)
    ctx.scripts.set('inner', ['goto done', 'send 99', 'label done', 'send 05'])
    ctx.scripts.set('outer', ['run script inner', 'if last.reg[0] == 2',
                              'goto done', 'end if', 'send 99', 'label done'])
    execute_command(ctx, 'run script outer -r')
    ctx.transport.exchange.assert_called_once_with(b'\x05')


@pytest.mark.parametrize('language', SUPPORTED_LANGUAGES)
def test_localization_and_help(ctx, language):
    ctx.config['ui']['language'] = language
    for topic in ['help', 'help script', 'help scripts', 'help label', 'help goto', 'help if']:
        execute_command(ctx, topic)
    text = ctx.console.export_text()
    assert ('Управление выполнением' if language == 'ru' else 'Script control flow') in text
    for token in ['label <name>', 'goto <name>', 'if <expression>', 'end if', 'last.reg[N]']:
        assert token in text
    for lines, reason in [(['goto missing'], 'script_unknown_label'),
                          (['if'], 'script_invalid_expression'),
                          (['if last.reg[0]', 'end if'], 'script_no_response')]:
        with pytest.raises(ValueError) as caught:
            run_script_lines(ctx, lines, source='demo')
        assert ('строка 1' if language == 'ru' else 'line 1') in str(caught.value)
        assert reason not in str(caught.value)
    ctx.last_response = LastResponse.from_rx(b'')
    with pytest.raises(ValueError) as caught:
        run_script_lines(ctx, ['# comment', 'if last.reg[0]', 'end if'], source='demo')
    assert ('недоступен' if language == 'ru' else 'unavailable') in str(caught.value)
    assert ('строка 2' if language == 'ru' else 'line 2') in str(caught.value)
    ctx.transport.connect.assert_not_called()


def test_compilation_language_independent_and_help_examples():
    from rtuforge.i18n import SCRIPT_EXAMPLES
    compile_script(SCRIPT_EXAMPLES.splitlines())
    programs = []
    for language in SUPPORTED_LANGUAGES:
        assert command_help(language, 'script')
        program = compile_script(['label wait', 'if last.timeout', 'goto wait', 'end if'])
        programs.append([(i.kind, i.target, ast.dump(i.expression) if i.expression else None)
                         for i in program.instructions])
    assert all(p == programs[0] for p in programs)


def test_interrupt_disconnects_without_continuing(ctx, monkeypatch):
    monkeypatch.setattr('rtuforge.commands.time.sleep', Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        run_script_lines(ctx, ['label loop', 'pause 1', 'goto loop', 'send 05'], source='loop')
    ctx.transport.disconnect.assert_called_once()
    ctx.transport.exchange.assert_not_called()


def test_external_cli_acceptance_raw_clean(tmp_path, monkeypatch, capsys):
    from rtuforge.cli import main
    from rtuforge.formatting import hex_line

    config_path = tmp_path / 'config.ini'
    config_path.write_bytes(Path('config.ini').read_bytes())
    script_path = Path('examples/ponic-test.ini').resolve()
    before = script_path.read_bytes()
    transport = Mock(connected=True)
    replies = [bytes.fromhex('05 06 00 0F 00 1E'), bytes.fromhex('05 03 02 00 02'),
               bytes.fromhex('05 03 02 00 02'), bytes.fromhex('05 03 02 00 00'),
               bytes.fromhex('05 03 02 00 1E')]
    exchanges = []
    def exchange(tx):
        item = Exchange(tx=append_crc(tx), rx=append_crc(replies.pop(0)), elapsed_ms=1)
        exchanges.append(item)
        return item
    transport.exchange.side_effect = exchange
    monkeypatch.setattr('rtuforge.cli.SerialTransport', lambda *args: transport)
    monkeypatch.setattr('rtuforge.commands.time.sleep', Mock())
    monkeypatch.setattr('sys.argv', ['rtuforge', '--config', str(config_path), '--scripts', str(script_path),
                                    'run', 'script', 'ponic-test', '-r', '-c'])
    assert main() == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert captured.out.splitlines() == [hex_line(frame) for item in exchanges for frame in (item.tx, item.rx)]
    assert len(exchanges) == 5
    assert script_path.read_bytes() == before
    transport.disconnect.assert_called_once()


def test_run_file_control_flow(ctx, tmp_path, monkeypatch):
    from rtuforge.script_file import save_script_file
    path = tmp_path / 'flow.rtus'
    save_script_file(path, {'flow': ['goto done', 'send 99', 'label done',
                                    'if true', 'pause 2', 'end if']})
    sleep = Mock()
    monkeypatch.setattr('rtuforge.commands.time.sleep', sleep)
    execute_command(ctx, f'run file "{path}" -r')
    sleep.assert_called_once_with(.002)
    ctx.transport.exchange.assert_not_called()


def test_cli_interrupt_returns_130(tmp_path, monkeypatch):
    from rtuforge.cli import main
    path = tmp_path / 'config.ini'
    path.write_bytes(Path('config.ini').read_bytes())
    transport = Mock()
    monkeypatch.setattr('rtuforge.cli.SerialTransport', lambda *args: transport)
    monkeypatch.setattr('rtuforge.cli.execute_command', Mock(side_effect=KeyboardInterrupt))
    monkeypatch.setattr('sys.argv', ['rtuforge', '--config', str(path), 'run', 'script', 'loop'])
    assert main() == 130
    transport.disconnect.assert_called_once()
