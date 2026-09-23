"""Compatibility imports for CLI discovery parsers and commands.

Handlers live in their command-family owners.
"""

from .commands.completion import add_completion_parser as add_completion_parser
from .commands.completion import cmd_completion as cmd_completion
from .commands.devices import add_devices_parser as add_devices_parser
from .commands.devices import cmd_devices_list as cmd_devices_list
from .commands.ensembles import add_ensembles_parser as add_ensembles_parser
from .commands.ensembles import cmd_ensembles_create as cmd_ensembles_create
from .commands.ensembles import cmd_ensembles_delete as cmd_ensembles_delete
from .commands.ensembles import cmd_ensembles_list as cmd_ensembles_list
from .commands.ensembles import cmd_ensembles_show as cmd_ensembles_show
from .commands.model_catalogue import cmd_models_catalog as cmd_models_catalog
from .commands.model_catalogue import cmd_models_download as cmd_models_download
from .commands.model_registration import cmd_models_configure as cmd_models_configure
from .commands.model_registration import cmd_models_register as cmd_models_register
from .commands.models import add_models_parser as add_models_parser
from .commands.models import cmd_models_list as cmd_models_list
from .commands.models import cmd_models_show as cmd_models_show
from .commands.models import cmd_models_validate as cmd_models_validate
from .commands.settings import add_settings_parser as add_settings_parser
from .commands.settings import cmd_profile_create as cmd_profile_create
from .commands.settings import cmd_profile_delete as cmd_profile_delete
from .commands.settings import cmd_profile_list as cmd_profile_list
from .commands.settings import cmd_profile_show as cmd_profile_show
from .commands.settings import cmd_settings_explain as cmd_settings_explain
from .commands.settings import cmd_settings_show as cmd_settings_show
from .commands.settings import cmd_settings_validate as cmd_settings_validate
