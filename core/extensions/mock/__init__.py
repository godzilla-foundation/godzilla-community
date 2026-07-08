try:
    from extensions import EXTENSION_REGISTRY_MD, EXTENSION_REGISTRY_TD
    from .md_mock import MockMd
    from .td_mock import MockTd
except ImportError:
    EXTENSION_REGISTRY_MD = None
    EXTENSION_REGISTRY_TD = None
else:
    EXTENSION_REGISTRY_MD.register_extension("mock", MockMd)
    EXTENSION_REGISTRY_TD.register_extension("mock", MockTd)
