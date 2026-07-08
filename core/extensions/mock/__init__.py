try:
    from extensions import EXTENSION_REGISTRY_MD, EXTENSION_REGISTRY_TD
except ImportError:
    EXTENSION_REGISTRY_MD = None
    EXTENSION_REGISTRY_TD = None

from .md_mock import MockMd
from .td_mock import MockTd


if EXTENSION_REGISTRY_MD is not None and EXTENSION_REGISTRY_TD is not None:
    EXTENSION_REGISTRY_MD.register_extension("mock", MockMd)
    EXTENSION_REGISTRY_TD.register_extension("mock", MockTd)
