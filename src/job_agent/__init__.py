"""Free Job Agent - France/Paris Data & AI Edition."""
import importlib
import importlib.util
import sys

__version__ = "0.3.0"


def _install_vendored_fallback(name: str, vendor_module: str) -> None:
    """Expose a vendored module under ``name`` only when the real package is
    absent. With the real ``requests`` installed this is a no-op, so dev/test
    and prod both use the genuine library (the vendored copy is a minimal
    fallback for locked-down environments, not a shadow of the real one)."""
    if name in sys.modules:
        return
    try:
        if importlib.util.find_spec(name) is not None:
            return  # real package available — use it
    except (ImportError, ValueError):
        pass
    try:
        sys.modules[name] = importlib.import_module(f"job_agent._vendor.{vendor_module}")
    except ImportError:
        pass


_install_vendored_fallback("requests", "requests")
