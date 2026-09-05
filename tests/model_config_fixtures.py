"""Config shells for tests of individual lookup/routing operations."""
from core.model_config import (
    DemucsOptions,
    DeviceOptions,
    EnsembleMemberFlags,
    ExportOptions,
    MDXOptions,
    ModelConfig,
    ModelIdentity,
    SecondaryChain,
    StemRouting,
    VROptions,
)
from core.model_config.base import CommonRunOptions


def model_config_shell() -> ModelConfig:
    """Install option owners without running path lookup or secondary resolution."""
    model = ModelConfig.__new__(ModelConfig)
    model.identity = ModelIdentity()
    model.export_options = ExportOptions()
    model.device_options = DeviceOptions()
    model.ensemble_flags = EnsembleMemberFlags()
    model.stem_routing = StemRouting()
    model.secondary_chain = SecondaryChain()
    model.common_options = CommonRunOptions()
    model._mdx_options = MDXOptions(routing=model.stem_routing)
    model._demucs_options = DemucsOptions(routing=model.stem_routing)
    model._vr_options = VROptions()
    return model
