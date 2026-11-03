import pytest

from bookshelf.cli import main


def test_cli_help():
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
