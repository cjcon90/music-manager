from unittest.mock import MagicMock, patch

import pexpect


@patch("app.importer.pexpect.spawnu")
def test_stream_import_apply_sends_uuid(mock_spawn):
    child = MagicMock()
    child.before = "Tagging: My Album\n"
    child.after = "[A]pply"
    # expect calls: [A]pply prompt, release ID:, second [A]pply prompt, then EOF
    child.expect.side_effect = [0, 0, 0, pexpect.EOF(None)]
    mock_spawn.return_value = child

    from app.importer import stream_import

    output = list(stream_import("/stage/path", mb_uuid="uuid-1234"))

    send_calls = [str(c) for c in child.sendline.call_args_list]
    assert any("I" in c for c in send_calls)
    assert any("uuid-1234" in c for c in send_calls)
    assert any("A" in c for c in send_calls)
    assert any("[DONE]" in line for line in output)


@patch("app.importer.pexpect.spawnu")
def test_stream_import_use_as_is_sends_u(mock_spawn):
    child = MagicMock()
    child.before = "Tagging: My Album\n"
    child.after = "[A]pply"
    child.expect.side_effect = [0, pexpect.EOF(None)]
    mock_spawn.return_value = child

    from app.importer import stream_import

    output = list(stream_import("/stage/path", mb_uuid=None, use_as_is=True))

    send_calls = [str(c) for c in child.sendline.call_args_list]
    assert any("U" in c for c in send_calls)
    assert any("[DONE]" in line for line in output)


@patch("app.importer.pexpect.spawnu")
def test_stream_import_timeout_yields_error(mock_spawn):
    child = MagicMock()
    child.before = ""
    child.expect.side_effect = pexpect.TIMEOUT(None)
    mock_spawn.return_value = child

    from app.importer import stream_import

    output = list(stream_import("/stage/path", mb_uuid="x"))
    assert any("[ERROR]" in line for line in output)
    assert any("[DONE]" in line for line in output)
