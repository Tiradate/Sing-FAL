import os
import subprocess
import unittest
from unittest.mock import patch

os.environ.setdefault("ICON_SKIP_RUNTIME_BOOTSTRAP", "1")

import app


class RuntimeBootstrapTests(unittest.TestCase):
    def test_relaunch_exits_with_child_status_without_wrapping_failure(self):
        requirements_path = os.path.join(app.BASE_DIR, "requirements.txt")
        venv_python = os.path.join(app.BASE_DIR, ".venv", "test-python")

        def fake_exists(path):
            return path in {requirements_path, venv_python}

        with patch.object(app.sys, "base_prefix", "python"), patch.object(
            app.sys, "prefix", "python"
        ), patch.object(app.sys, "executable", "/usr/bin/python3"), patch.object(
            app.sys, "argv", ["app.py"]
        ), patch(
            "app._venv_python_path", return_value=venv_python
        ), patch(
            "app.os.path.exists", side_effect=fake_exists
        ), patch(
            "app.subprocess.run",
            return_value=subprocess.CompletedProcess([venv_python, app.__file__], 1),
        ) as run_mock:
            with self.assertRaises(SystemExit) as exc:
                app.ensure_runtime_environment()

        self.assertEqual(1, exc.exception.code)
        run_mock.assert_called_once_with([venv_python, os.path.abspath(app.__file__)])


if __name__ == "__main__":
    unittest.main()
