from __future__ import annotations

from server.auth.password_store import PasswordStore
from shared.constants.app_version import APP_VERSION


def test_password_store_preserves_minimum_client_version(tmp_path) -> None:
    config_path = tmp_path / "server.toml"
    store = PasswordStore(config_path)

    assert store.load_minimum_client_version() == APP_VERSION

    store.save("secret")
    store.save_minimum_client_version("1.2.3")

    reloaded = PasswordStore(config_path)
    assert reloaded.load() == "secret"
    assert reloaded.load_minimum_client_version() == "1.2.3"

    reloaded.save("new-secret")
    assert reloaded.load() == "new-secret"
    assert reloaded.load_minimum_client_version() == "1.2.3"


def test_password_store_loads_server_name(tmp_path) -> None:
    config_path = tmp_path / "server.toml"
    config_path.write_text(
        '\n'.join(
            [
                'server_name = "Test Fleet Server"',
                'server_password = "secret"',
            ]
        )
        + '\n',
        encoding="utf-8",
    )

    store = PasswordStore(config_path)

    assert store.load_server_name() == "Test Fleet Server"
