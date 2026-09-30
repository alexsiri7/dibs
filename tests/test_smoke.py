import dibs
from dibs import models, server  # noqa: F401


def test_package_imports() -> None:
    assert dibs.__version__
    assert server.mcp.name == "dibs"
