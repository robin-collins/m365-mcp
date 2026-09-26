"""Handlers for the unified 30-tool surface.

Importing this package imports every module in it, so each domain module
(mail, calendar, drive, ...) registers its handlers and per-resource
functions on import, then the ``m365_*`` dispatchers are installed.
"""

import importlib
import pkgutil

from .common import install_generic_handlers, install_generic_rules

install_generic_rules()

for _module in sorted(m.name for m in pkgutil.iter_modules(__path__)):
    if _module != "common":
        importlib.import_module(f"{__name__}.{_module}")

install_generic_handlers()
