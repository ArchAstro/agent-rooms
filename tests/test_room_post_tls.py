import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOM_POST_PATH = (
    Path(__file__).parents[1] / "skills" / "team-room" / "room_post.py"
)
SPEC = importlib.util.spec_from_file_location("room_post", ROOM_POST_PATH)
room_post = importlib.util.module_from_spec(SPEC)
original_argv = sys.argv
try:
    # `help` is a soft-config command, so importing the single-file client for
    # unit tests does not require a machine-specific room.json.
    sys.argv = [str(ROOM_POST_PATH), "help"]
    SPEC.loader.exec_module(room_post)
finally:
    sys.argv = original_argv


class ConfigureCaBundleTest(unittest.TestCase):
    def test_respects_explicit_certificate_file(self):
        with (
            patch.dict(
                os.environ,
                {"SSL_CERT_FILE": "/custom/team-ca.pem"},
                clear=True,
            ),
            patch.object(room_post.os.path, "isfile") as isfile,
        ):
            room_post.configure_ca_bundle()

            self.assertEqual(os.environ["SSL_CERT_FILE"], "/custom/team-ca.pem")
            isfile.assert_not_called()

    def test_keeps_an_existing_python_default(self):
        defaults = SimpleNamespace(cafile="/python/default-ca.pem")

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                room_post.ssl,
                "get_default_verify_paths",
                return_value=defaults,
            ),
            patch.object(
                room_post.os.path,
                "isfile",
                side_effect=lambda path: path == defaults.cafile,
            ),
        ):
            room_post.configure_ca_bundle()

            self.assertNotIn("SSL_CERT_FILE", os.environ)

    def test_uses_the_first_available_system_bundle(self):
        defaults = SimpleNamespace(cafile="/missing/python-ca.pem")

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                room_post.ssl,
                "get_default_verify_paths",
                return_value=defaults,
            ),
            patch.object(
                room_post.os.path,
                "isfile",
                side_effect=lambda path: path == "/etc/ssl/cert.pem",
            ),
        ):
            room_post.configure_ca_bundle()

            self.assertEqual(os.environ["SSL_CERT_FILE"], "/etc/ssl/cert.pem")


if __name__ == "__main__":
    unittest.main()
