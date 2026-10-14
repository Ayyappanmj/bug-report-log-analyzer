"""Which local paths may the app read? Default (single user, own machine): any normal folder/file, minus sensitive places.
Public-demo mode (`PUBLIC_DEMO=true`): no local paths at all, only uploads and the bundled demo, because on a shared server
a path box would let any visitor read files from the server."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_ROOT = ROOT / "demo"
SENSITIVE_DIRS = {".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure", ".gcloud", ".password-store"}


class PolicyError(ValueError):
    """The requested path is not allowed by the security policy."""


def _real(p) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(p))))


def is_inside(child: Path, parent: Path) -> bool:
    c, p = os.path.normcase(str(child)), os.path.normcase(str(parent))
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives on Windows
        return False


@dataclass(frozen=True)
class PathPolicy:
    allow_local_paths: bool = True
    allowed_roots: tuple[str, ...] = ()

    def check(self, path) -> Path:
        """Return the resolved path or raise PolicyError. The bundled demo is always allowed."""
        p = _real(path)
        if is_inside(p, _real(DEMO_ROOT)):
            return p
        if not self.allow_local_paths:
            raise PolicyError("Local file paths are disabled in this deployment. Upload a file or use the demo.")
        if p == Path(p.anchor):
            raise PolicyError("Refusing to read from a filesystem root. Choose a specific folder.")
        if any(part.lower() in SENSITIVE_DIRS for part in p.parts):
            raise PolicyError("That location holds credentials or keys and is blocked.")
        if self.allowed_roots and not any(is_inside(p, _real(r)) for r in self.allowed_roots):
            raise PolicyError("That path is outside the folders this deployment allows.")
        return p
