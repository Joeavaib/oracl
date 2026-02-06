import py_compile
from pathlib import Path


def test_routes_module_compiles():
    path = Path(__file__).resolve().parents[1] / "app" / "ui" / "routes.py"
    py_compile.compile(str(path), doraise=True)
