import os
import shlex
import tempfile
from collections.abc import Generator

import pexpect

from app import config

APPLY_PROMPT = r"\[A\]pply"
TIMEOUT_SECONDS = 300

# Overrides import.quiet (set globally for automated imports) so that
# beets shows interactive prompts, and sets timid so it always asks.
_IMPORT_OVERRIDE_YAML = "import:\n  quiet: no\n  timid: yes\n"


def stream_import(
    stage_path: str,
    mb_uuid: str | None = None,
    use_as_is: bool = False,
) -> Generator[str, None, None]:
    env = {**os.environ, "BEETSDIR": config.BEETSDIR}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(_IMPORT_OVERRIDE_YAML)
        override_cfg = f.name
    cmd = f"beet -c {shlex.quote(override_cfg)} import --noincremental {shlex.quote(stage_path)}"

    child = None
    try:
        child = pexpect.spawnu(cmd, env=env, timeout=TIMEOUT_SECONDS)

        # Wait for initial [A]pply prompt
        try:
            idx = child.expect([APPLY_PROMPT, pexpect.EOF, pexpect.TIMEOUT], timeout=TIMEOUT_SECONDS)
        except pexpect.TIMEOUT:
            yield "data: [ERROR] Import timed out waiting for beets prompt\n\n"
            child.terminate(force=True)
            return

        if child.before:
            for line in child.before.splitlines():
                if line.strip():
                    yield f"data: {line}\n\n"

        if idx != 0:
            # beets exited without showing a match prompt — either EOF (silent skip/duplicate)
            # or timeout. These are different conditions but both mean no interactive prompt.
            if idx == 2:
                yield "data: [WARNING] beets timed out before showing a match prompt\n\n"
            else:
                yield "data: [WARNING] beets exited without a match prompt — import may have been skipped silently (duplicate or no match found)\n\n"
            return

        if child.after:
            yield f"data: {child.after}\n\n"

        if use_as_is or mb_uuid is None:
            child.sendline("U")
        else:
            child.sendline("I")
            try:
                # Wait for the UUID input prompt
                child.expect(r"release ID:", timeout=30)
                if child.before:
                    for line in child.before.splitlines():
                        if line.strip():
                            yield f"data: {line}\n\n"
                child.sendline(mb_uuid)
                child.sendline("A")
            except pexpect.TIMEOUT:
                yield "data: [ERROR] Timed out during ID selection\n\n"
                child.terminate(force=True)
                return

        # Drain remaining output until EOF
        try:
            child.expect(pexpect.EOF, timeout=TIMEOUT_SECONDS)
            if child.before:
                for line in child.before.splitlines():
                    if line.strip():
                        yield f"data: {line}\n\n"
        except (pexpect.TIMEOUT, Exception):
            pass

    except Exception as e:
        yield f"data: [ERROR] Unexpected error: {e}\n\n"
    finally:
        try:
            if child is not None:
                child.close()
        except Exception:
            pass
        try:
            os.unlink(override_cfg)
        except OSError:
            pass
        yield "data: [DONE]\n\n"
