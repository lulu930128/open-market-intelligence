"""Fixed isolated entry, invoked only by the existing Launcher-owned Runner.

Application modules compile from one immutable, hashed source snapshot. Imports
cannot silently adopt later disk edits or stale pyc. Dependencies use the pinned
repo venv; the receipt deliberately names application-source scope.
"""
import hashlib
import importlib.abc
import importlib.util
from pathlib import Path
import stat
import sys
import types

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))
sys.path.insert(0, str(ROOT / "backend"))


class ApplicationSource(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self):
        self.files = {}
        digest = hashlib.sha256()
        paths = sorted((ROOT / "backend" / "app").rglob("*.py"), key=lambda path: path.as_posix())
        for path in paths:
            # lstat exposes reparse attributes on both Python 3.11 and 3.13.
            # Do not treat an unavailable attribute or failed stat as safe.
            if path.is_symlink() or (sys.platform == "win32" and any(
                p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                for p in (path, *path.parents)
            )):
                raise RuntimeError("SOURCE_REPARSE_REFUSED")
            name = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            self.files[name] = data
            digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
        self.release_id = digest.hexdigest()
        self.verified = False

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "app" and not fullname.startswith("app."):
            return None
        base = "backend/" + fullname.replace(".", "/")
        name = base + "/__init__.py" if base + "/__init__.py" in self.files else base + ".py"
        if name not in self.files:
            # Existing namespace packages remain supported, but only snapshot
            # modules can load; a newly-added disk module is rejected.
            if any(key.startswith(base + "/") for key in self.files):
                spec = importlib.util.spec_from_loader(fullname, loader=None, is_package=True)
                spec.submodule_search_locations = [str(ROOT / base)]
                return spec
            raise ImportError("MODULE_OUTSIDE_APPLICATION_SNAPSHOT")
        return importlib.util.spec_from_file_location(fullname, ROOT / name, loader=self,
                    submodule_search_locations=[str(ROOT / base)] if name.endswith("/__init__.py") else None)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = Path(module.__spec__.origin).relative_to(ROOT).as_posix()
        exec(compile(self.files[name], str(ROOT / name), "exec"), module.__dict__)


def main():
    source = ApplicationSource()
    # Private object exists only in the isolated fixed entry process.
    sys.modules["_omi_owned_release"] = source
    sys.meta_path.insert(0, source)
    from app.owned_uvicorn import main as run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
