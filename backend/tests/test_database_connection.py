from __future__ import annotations

from app.db.connection import connect


def test_connect_expands_home_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    connection = connect("~/databases/otello.db")
    try:
        connection.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    assert (tmp_path / "databases" / "otello.db").is_file()
