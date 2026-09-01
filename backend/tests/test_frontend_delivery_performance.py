from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIG = ROOT / "frontend" / "nginx.conf"


def test_nginx_compresses_frontend_text_assets() -> None:
    config = NGINX_CONFIG.read_text(encoding="utf-8")

    assert "gzip on;" in config
    assert "application/javascript" in config
    assert "text/css" in config


def test_hashed_assets_are_cached_as_immutable() -> None:
    config = NGINX_CONFIG.read_text(encoding="utf-8")

    assets_location = config.split("location /assets/ {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert 'Cache-Control "public, max-age=31536000, immutable"' in assets_location
    assert "try_files $uri =404;" in assets_location
