"""Prevent local rollback evidence from silently using development images."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rf013_local_rehearsal import Rehearsal


class ReleaseImagesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rehearsal = object.__new__(Rehearsal)
        self.rehearsal.dir = Path(self.temp.name)
        self.rehearsal.prefix = "milana-rf013-test"
        self.rehearsal.proxy_name = "milana-rf013-test-haproxy"
        self.rehearsal.evidence = {"events": []}

    def test_frontend_uses_source_release_recipe_and_baked_local_proxy(self):
        config = {"Id": "sha256:test", "Config": {
            "Cmd": ["node", "server.js"], "Entrypoint": ["docker-entrypoint.sh"],
            "Env": ["NODE_ENV=production"], "User": "nextjs",
        }}
        with patch("rf013_local_rehearsal.subprocess.run") as build, patch(
            "rf013_local_rehearsal.docker", return_value=json.dumps([config])
        ):
            build.return_value.returncode = 0
            self.rehearsal.build("frontend", "old", Path("/source"))
        args = build.call_args.args[0]
        self.assertEqual(args[-1], "/source")
        self.assertEqual(args[args.index("-f") + 1], "/source/frontend/Dockerfile")
        self.assertIn("API_URL=http://milana-rf013-test-haproxy:8000", args)
        self.assertIn("NEXT_PUBLIC_API_URL=", args)
        self.assertEqual(self.rehearsal.evidence["images"][0]["command"], ["node", "server.js"])

    def test_development_frontend_is_refused(self):
        config = {"Id": "sha256:dev", "Config": {
            "Cmd": ["npm", "run", "dev"], "Env": ["NODE_ENV=development"],
        }}
        with patch("rf013_local_rehearsal.subprocess.run") as build, patch(
            "rf013_local_rehearsal.docker", return_value=json.dumps([config])
        ):
            build.return_value.returncode = 0
            with self.assertRaisesRegex(RuntimeError, "production"):
                self.rehearsal.build("frontend", "candidate", Path("/source"))

    def test_backend_keeps_release_build_context(self):
        config = {"Id": "sha256:backend", "Config": {"Cmd": ["uvicorn", "app.main:app"]}}
        with patch("rf013_local_rehearsal.subprocess.run") as build, patch(
            "rf013_local_rehearsal.docker", return_value=json.dumps([config])
        ):
            build.return_value.returncode = 0
            self.rehearsal.build("backend", "candidate", Path("/source"))
        self.assertEqual(build.call_args.args[0][-1], "/source/backend")
        self.assertEqual(self.rehearsal.evidence["images"][0]["command"], ["uvicorn", "app.main:app"])


if __name__ == "__main__":
    unittest.main()
