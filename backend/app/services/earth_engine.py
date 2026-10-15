import ee

from app.config import get_settings

_initialised = False


def init_ee() -> None:
    """Initialise once per process, not per request."""
    global _initialised
    if not _initialised:
        ee.Initialize(project=get_settings().ee_project)
        _initialised = True


def ping() -> int:
    init_ee()
    return ee.Number(1).getInfo()
