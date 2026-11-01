"""运维相关测试：健康检查与 SQLite 热备份。

这两件事平时没人测，出问题时最要命，所以单独覆盖。
"""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cg-ops-"))
os.environ.setdefault("CLAUSEGUARD_DB", str(TMP / "test.sqlite3"))
os.environ.setdefault("CLAUSEGUARD_DATA", str(TMP))
os.environ.setdefault("CLAUSEGUARD_ALLOW_PRIVATE_MODEL", "0")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from scripts.backup_db import backup, main, prune  # noqa: E402


class HealthTests(unittest.TestCase):
    def test_health_reports_real_checks(self):
        client = TestClient(app, base_url="http://testserver")
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["checks"], {"db": "ok", "data_dir": "ok"})
        self.assertEqual(body["service"], "clauseguard")

    def test_health_does_not_require_login(self):
        """健康检查必须免鉴权，否则监控探活会被 401 挡住。"""
        client = TestClient(app, base_url="http://testserver")
        self.assertNotEqual(client.get("/api/health").status_code, 401)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.db = TMP / f"source-{self._testMethodName}.sqlite3"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE demo(id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany("INSERT INTO demo(name) VALUES(?)", [("a",), ("b",), ("c",)])
        conn.commit()
        conn.close()
        self.out = TMP / f"out-{self._testMethodName}"

    def test_backup_copies_rows_and_passes_integrity_check(self):
        target = backup(self.db, self.out)
        self.assertTrue(target.exists())
        copied = sqlite3.connect(target)
        try:
            rows = copied.execute("SELECT COUNT(*) FROM demo").fetchone()[0]
            self.assertEqual(rows, 3)
        finally:
            copied.close()

    def test_backup_missing_db_raises(self):
        with self.assertRaises(SystemExit):
            backup(TMP / "not-exists.sqlite3", self.out)

    def test_prune_keeps_newest(self):
        for index in range(5):
            (self.out).mkdir(parents=True, exist_ok=True)
            (self.out / f"clauseguard-2026010{index + 1}-000000.sqlite3").write_bytes(b"x")
        removed = prune(self.out, keep=2)
        self.assertEqual(len(removed), 3)
        remaining = sorted(path.name for path in self.out.glob("clauseguard-*.sqlite3"))
        self.assertEqual(len(remaining), 2)
        self.assertIn("20260105", remaining[-1])

    def test_cli_writes_backup_and_reports(self):
        code = main(["--db", str(self.db), "--out", str(self.out), "--keep", "2"])
        self.assertEqual(code, 0)
        self.assertEqual(len(list(self.out.glob("clauseguard-*.sqlite3"))), 1)


if __name__ == "__main__":
    unittest.main()
