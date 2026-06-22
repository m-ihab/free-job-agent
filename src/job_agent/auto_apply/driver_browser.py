"""Browser profile selection and persistent-context launch for auto-apply.

Self-contained: chooses a safe Chrome/Chromium profile (dedicated by default,
the real profile only on explicit opt-in), launches the persistent context, and
checks that Playwright is installed. Re-exported by
:mod:`job_agent.auto_apply.driver`.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AUTO_APPLY_PROFILE_ENV = "JOB_AGENT_AUTO_APPLY_PROFILE_DIR"
_USE_REAL_CHROME_PROFILE_ENV = "JOB_AGENT_AUTO_APPLY_USE_REAL_CHROME_PROFILE"


@dataclass
class BrowserProfileSelection:
    path: Path
    label: str
    warning: str = ""


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _dedicated_browser_profile(config: Any) -> Path:
    """Return Job Agent's private browser profile directory."""
    custom = os.environ.get(_AUTO_APPLY_PROFILE_ENV)
    if custom:
        path = Path(custom).expanduser()
    else:
        data_dir = Path(getattr(config, "data_dir", Path.cwd() / ".job_agent"))
        path = data_dir / "browser_profiles" / "auto_apply"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profile_lock_markers(path: Path) -> list[Path]:
    return [path / name for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")]


def _profile_looks_locked(path: Path) -> bool:
    return any(marker.exists() for marker in _profile_lock_markers(path))


def _select_browser_profile(config: Any) -> BrowserProfileSelection:
    """Pick the browser profile safely.

    The normal Chrome "User Data" directory cannot be controlled while Chrome is
    open. Using a private profile keeps sessions persistent without asking the
    user to close their daily browser.
    """
    custom = os.environ.get(_AUTO_APPLY_PROFILE_ENV)
    if custom:
        return BrowserProfileSelection(_dedicated_browser_profile(config), "custom Job Agent")

    if _truthy_env(_USE_REAL_CHROME_PROFILE_ENV):
        import job_agent.auto_apply as _pkg
        real_profile = _pkg._find_chrome_profile()
        if real_profile:
            real_path = Path(real_profile)
            if not _profile_looks_locked(real_path):
                return BrowserProfileSelection(real_path, "real Chrome")
            return BrowserProfileSelection(
                _dedicated_browser_profile(config),
                "dedicated Job Agent",
                (
                    "Your real Chrome profile is already in use, so auto-apply "
                    "switched to the dedicated Job Agent profile instead."
                ),
            )

    return BrowserProfileSelection(_dedicated_browser_profile(config), "dedicated Job Agent")


def _launch_browser_context(playwright: Any, profile_dir: Path, headless: bool) -> Any:
    """Launch a persistent browser profile with Chrome first, Chromium fallback."""
    kwargs = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "args": ["--start-maximized"] if not headless else [],
        "no_viewport": not headless,
    }
    last_exc: Exception | None = None
    channels: list[str | None] = ["chrome", None] if not headless else [None]
    for channel in channels:
        try:
            if channel:
                return playwright.chromium.launch_persistent_context(channel=channel, **kwargs)
            return playwright.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            if "Opening in existing browser session" in msg or "profile is already in use" in msg:
                raise RuntimeError(
                    "The selected browser profile is already in use. Use the default "
                    "dedicated Job Agent profile, or close every Chrome window before "
                    f"setting {_USE_REAL_CHROME_PROFILE_ENV}=1."
                ) from exc
            if channel:
                logger.info("Chrome channel launch failed; trying Playwright Chromium: %s", exc)
                continue
            break
    raise RuntimeError(
        "Could not start the Playwright browser. Run `python -m playwright install chromium` "
        f"or install Google Chrome. Last error: {last_exc}"
    )


def _find_chrome_profile() -> str | None:
    """Return the path to the user's Chrome profile directory."""
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data"),
        os.path.join(os.environ.get("APPDATA", ""), "Google", "Chrome", "User Data"),
        os.path.expanduser("~/.config/google-chrome"),
        os.path.expanduser("~/Library/Application Support/Google/Chrome"),
    ]
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return None


class _PlaywrightNotInstalled(RuntimeError):
    pass


def _check_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise _PlaywrightNotInstalled(
            "playwright is not installed. Run:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        )
