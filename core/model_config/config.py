"""Public typed model configuration."""

from ..model_data import _ModelConfigImplementation


class ModelConfig(_ModelConfigImplementation):
    """Configuration consumed by separation engines.

    The inherited flat attributes are the stable duck-typed engine API. New
    callers can use the typed nested groups populated by the implementation:
    ``identity``, ``export_options``, ``device_options``, ``ensemble_flags``,
    ``stem_routing``, ``secondary_chain``, and the architecture option group.
    """

