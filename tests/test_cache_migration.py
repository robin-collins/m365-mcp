from __future__ import annotations

from types import SimpleNamespace

from src.m365_mcp import cache_migration
from src.m365_mcp.encryption import EncryptionKeyManager


class FakeCursor(list):
    def fetchall(self):
        return list(self)


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.closed = False
        self.committed = False

    def execute(self, statement: str):
        self.statements.append(statement)
        return FakeCursor()

    def executemany(self, statement: str, rows):
        self.statements.append(statement)
        return FakeCursor(rows)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def test_migration_uses_encoded_sqlcipher_key(tmp_path, monkeypatch) -> None:
    """Migration should use the shared encoded key PRAGMA."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"
    old_db.write_bytes(b"sqlite")
    key = EncryptionKeyManager.generate_key()
    connections = [FakeConnection(), FakeConnection()]
    created_connections = connections.copy()

    def fake_connect(path: str):
        assert path in {str(old_db), str(new_db)}
        return connections.pop(0)

    monkeypatch.setattr(
        cache_migration,
        "sqlite3",
        SimpleNamespace(connect=fake_connect),
    )
    monkeypatch.setattr(
        EncryptionKeyManager,
        "get_or_create_key",
        staticmethod(lambda: key),
    )

    assert cache_migration.migrate_to_encrypted_cache(old_db, new_db, backup=False)

    expected_pragma = EncryptionKeyManager.sqlcipher_key_pragma(key)
    assert expected_pragma in created_connections[1].statements
