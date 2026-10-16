#!/usr/bin/env python3
"""Offline regression tests for secret-safe Hermes Telegram token rotation."""

from __future__ import annotations

import errno
import fcntl
import http.server
import json
import os
from pathlib import Path
import pty
import select
import shutil
import stat
import subprocess
import tempfile
import termios
import threading
import time


ROOT = Path(__file__).resolve().parents[2]
ROTATE = ROOT / "scripts" / "rotate-hermes-telegram-token"
OLD_TOKEN = "123456" + ":" + "O" * 32
NEW_TOKEN = "7000001234" + ":" + "N" * 35


def write_mock_curl(bin_dir: Path) -> None:
    script = bin_dir / "curl"
    script.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

request = sys.stdin.read()
token = request.split('/bot', 1)[1].split('/getMe', 1)[0] if '/bot' in request else ''
audit = {
    'argv_has_token': any(token and token in value for value in sys.argv),
    'env_has_token': any(token and token in value for value in os.environ.values()),
    'received_via_stdin': bool(token),
}
with open(os.environ['MOCK_CURL_AUDIT'], 'w', encoding='utf-8') as stream:
    json.dump(audit, stream)
mode = os.environ.get('MOCK_GETME_MODE', 'ok')
if mode == 'network-error':
    raise SystemExit(22)
if mode == 'invalid-json':
    print('not json')
    raise SystemExit(0)
username = 'some_other_bot' if mode == 'mismatch' else 'The_NixOS_Bot'
is_bot = mode != 'not-bot'
print(json.dumps({'ok': True, 'result': {'id': 7000001234, 'is_bot': is_bot, 'username': username}}))
""",
        encoding="utf-8",
    )
    script.chmod(0o755)


def fixture(base: Path, *, content: bytes | None = None) -> tuple[Path, Path, Path]:
    base.mkdir(parents=True)
    env_file = base / "hermes.env"
    if content is None:
        content = (
            b"API_SERVER_KEY=keep-this-byte-for-byte\r\n"
            + b"TELEGRAM_BOT_TOKEN="
            + OLD_TOKEN.encode("ascii")
            + b"\r\nTELEGRAM_ALLOWED_USERS=123456789\r\n"
            + b"TELEGRAM_ALLOW_ALL_USERS=false\r\nGATEWAY_ALLOW_ALL_USERS=false"
        )
    env_file.write_bytes(content)
    env_file.chmod(0o600)
    config = base / "deployment.env"
    config.write_text(
        f"HERMES_ENV_FILE={env_file}\n"
        "HERMES_TELEGRAM_BOT_USERNAME=the_nixos_bot\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    return config, env_file, base / "curl-audit.json"


def invoke(
    config: Path,
    audit: Path,
    token: str = NEW_TOKEN,
    mode: str = "ok",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "NIX_ALLOW_TEST_CONFIG": "1",
            "NIX_TELEGRAM_API_BASE": "https://telegram.invalid",
            "MOCK_CURL_AUDIT": str(audit),
            "MOCK_GETME_MODE": mode,
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(ROTATE), "--stdin", str(config)],
        input=token + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )


def invoke_interactively(config: Path, audit: Path, token: str = NEW_TOKEN) -> tuple[int, bytes]:
    env = os.environ.copy()
    env.update(
        {
            "NIX_ALLOW_TEST_CONFIG": "1",
            "NIX_TELEGRAM_API_BASE": "https://telegram.invalid",
            "MOCK_CURL_AUDIT": str(audit),
            "MOCK_GETME_MODE": "ok",
        }
    )
    master_fd, slave_fd = pty.openpty()

    def make_controlling_tty() -> None:
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    process = subprocess.Popen(
        [str(ROTATE), str(config)],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        close_fds=True,
        preexec_fn=make_controlling_tty,
    )
    os.close(slave_fd)
    output = bytearray()
    token_sent = False
    deadline = time.monotonic() + 15
    try:
        while True:
            if time.monotonic() >= deadline:
                process.kill()
                raise AssertionError("interactive token rotation timed out")
            readable, _, _ = select.select([master_fd], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO and process.poll() is not None:
                        break
                    raise
                if not chunk:
                    break
                output.extend(chunk)
            if not token_sent and b"Paste the replacement BotFather token: " in output:
                os.write(master_fd, token.encode("ascii") + b"\n")
                token_sent = True
            if process.poll() is not None and not readable:
                break
        return_code = process.wait(timeout=5)
    finally:
        os.close(master_fd)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    assert token_sent, bytes(output)
    return return_code, bytes(output)


def assert_failed_unchanged(config: Path, env_file: Path, audit: Path, *, token: str = NEW_TOKEN, mode: str = "ok") -> str:
    before = env_file.read_bytes()
    result = invoke(config, audit, token, mode)
    assert result.returncode != 0, result.stdout
    assert env_file.read_bytes() == before
    assert token not in result.stdout
    assert token not in result.stderr
    return result.stderr


def main() -> None:
    real_curl = shutil.which("curl")
    assert real_curl, "curl is required for the rotation regression test"
    with tempfile.TemporaryDirectory(prefix="nix-os-telegram-rotation-") as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        write_mock_curl(bin_dir)
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]

        config, env_file, audit = fixture(root / "success")
        original = env_file.read_bytes()
        original_inode = env_file.stat().st_ino
        result = invoke(config, audit)
        assert result.returncode == 0, result.stderr
        expected = original.replace(OLD_TOKEN.encode("ascii"), NEW_TOKEN.encode("ascii"))
        assert env_file.read_bytes() == expected
        assert env_file.stat().st_ino != original_inode
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
        assert NEW_TOKEN not in result.stdout and NEW_TOKEN not in result.stderr
        curl_audit = json.loads(audit.read_text(encoding="utf-8"))
        assert curl_audit == {
            "argv_has_token": False,
            "env_has_token": False,
            "received_via_stdin": True,
        }
        assert "@The_NixOS_Bot" in result.stdout

        config, env_file, audit = fixture(root / "interactive-pty")
        original = env_file.read_bytes()
        return_code, terminal_output = invoke_interactively(config, audit)
        assert return_code == 0, terminal_output.decode("utf-8", errors="replace")
        assert b"Paste the replacement BotFather token: " in terminal_output
        assert NEW_TOKEN.encode("ascii") not in terminal_output
        assert env_file.read_bytes() == original.replace(
            OLD_TOKEN.encode("ascii"), NEW_TOKEN.encode("ascii")
        )
        curl_audit = json.loads(audit.read_text(encoding="utf-8"))
        assert curl_audit == {
            "argv_has_token": False,
            "env_has_token": False,
            "received_via_stdin": True,
        }

        config, env_file, audit = fixture(root / "interactive-no-tty")
        original = env_file.read_bytes()
        env = os.environ.copy()
        env.update(
            {
                "NIX_ALLOW_TEST_CONFIG": "1",
                "NIX_TELEGRAM_API_BASE": "https://telegram.invalid",
                "MOCK_CURL_AUDIT": str(audit),
                "MOCK_GETME_MODE": "ok",
            }
        )
        result = subprocess.run(
            [str(ROTATE), str(config)],
            input=NEW_TOKEN + "\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
            timeout=10,
            check=False,
        )
        assert result.returncode != 0
        assert "cannot read a hidden token from /dev/tty" in result.stderr
        assert NEW_TOKEN not in result.stdout and NEW_TOKEN not in result.stderr
        assert env_file.read_bytes() == original
        assert not audit.exists(), "non-TTY input unexpectedly reached curl"

        class GetMeHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - inherited API name
                body = json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "id": 7000001234,
                            "is_bot": True,
                            "username": "the_nixos_bot",
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GetMeHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            real_bin = root / "real-bin"
            real_bin.mkdir()
            (real_bin / "curl").symlink_to(real_curl)
            curl_home = root / "curl-home"
            curl_home.mkdir()
            curl_trace = root / "curl-trace.txt"
            (curl_home / ".curlrc").write_text(
                f'trace-ascii = "{curl_trace}"\n', encoding="utf-8"
            )
            config, env_file, audit = fixture(root / "curlrc-disabled")
            result = invoke(
                config,
                audit,
                extra_env={
                    "CURL_HOME": str(curl_home),
                    "NIX_TELEGRAM_API_BASE": f"http://127.0.0.1:{server.server_port}",
                    "PATH": str(real_bin) + os.pathsep + os.environ["PATH"],
                },
            )
            assert result.returncode == 0, result.stderr
            trace_bytes = curl_trace.read_bytes() if curl_trace.exists() else b""
            assert NEW_TOKEN.encode("ascii") not in trace_bytes
            assert env_file.read_bytes().count(NEW_TOKEN.encode("ascii")) == 1
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)

        for mode in ("mismatch", "not-bot", "network-error", "invalid-json"):
            config, env_file, audit = fixture(root / mode)
            assert_failed_unchanged(config, env_file, audit, mode=mode)

        config, env_file, audit = fixture(root / "malformed")
        assert_failed_unchanged(config, env_file, audit, token="not-a-token")
        assert not audit.exists(), "malformed token unexpectedly reached curl"

        for label, content in (
            ("missing", b"API_SERVER_KEY=unchanged\n"),
            (
                "duplicate",
                b"TELEGRAM_BOT_TOKEN="
                + OLD_TOKEN.encode("ascii")
                + b"\nTELEGRAM_BOT_TOKEN="
                + OLD_TOKEN.encode("ascii")
                + b"\n",
            ),
        ):
            config, env_file, audit = fixture(root / label, content=content)
            assert_failed_unchanged(config, env_file, audit)
            assert not audit.exists(), f"{label} token layout unexpectedly reached curl"

        config, env_file, audit = fixture(root / "permissive")
        env_file.chmod(0o640)
        assert_failed_unchanged(config, env_file, audit)
        assert not audit.exists()

        symlink_root = root / "symlink"
        config, env_file, audit = fixture(symlink_root)
        real_file = symlink_root / "real-hermes.env"
        env_file.rename(real_file)
        env_file.symlink_to(real_file)
        assert_failed_unchanged(config, env_file, audit)
        assert not audit.exists()

        hardlink_root = root / "hardlink"
        config, env_file, audit = fixture(hardlink_root)
        os.link(env_file, hardlink_root / "second-link.env")
        assert_failed_unchanged(config, env_file, audit)
        assert not audit.exists()

        relative_root = root / "relative"
        config, env_file, audit = fixture(relative_root)
        config.write_text(
            "HERMES_ENV_FILE=hermes.env\n"
            "HERMES_TELEGRAM_BOT_USERNAME=the_nixos_bot\n",
            encoding="utf-8",
        )
        assert_failed_unchanged(config, env_file, audit)

        duplicate_config_root = root / "duplicate-config"
        config, env_file, audit = fixture(duplicate_config_root)
        with config.open("a", encoding="utf-8") as stream:
            stream.write("HERMES_TELEGRAM_BOT_USERNAME=other_bot\n")
        assert_failed_unchanged(config, env_file, audit)

        if os.geteuid() != 0:
            config, env_file, audit = fixture(root / "requires-root")
            env = os.environ.copy()
            env.pop("NIX_ALLOW_TEST_CONFIG", None)
            result = subprocess.run(
                [str(ROTATE), "--stdin", str(config)],
                input=NEW_TOKEN + "\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            assert result.returncode != 0
            assert "must run as root" in result.stderr
            assert env_file.read_bytes().find(NEW_TOKEN.encode("ascii")) == -1

    print("Hermes Telegram token rotation tests passed.")


if __name__ == "__main__":
    main()
