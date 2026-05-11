import unittest

from kodi_xbox_proxy import repo_manager


class RepoManagerTests(unittest.TestCase):
    def test_latest_repo_zip_sorts_semantic_versions(self):
        latest = repo_manager.latest_repo_zip()

        self.assertEqual(latest["name"], "script.xbox.proxy-1.0.10.zip")
        self.assertEqual(latest["version"], "1.0.10")


if __name__ == "__main__":
    unittest.main()
