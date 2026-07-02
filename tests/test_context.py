import unittest
from unittest.mock import MagicMock, patch

from uvr_gtk.context import AppContext


class AppContextHookTests(unittest.TestCase):
    def test_install_unrecognized_hook_is_idempotent(self):
        context = AppContext()
        parent = MagicMock()

        with patch("uvr_gtk.context.ModelRepository") as repo_cls:
            repo = repo_cls.return_value
            context.install_unrecognized_model_hook(parent)
            _ = context.repo
            first_handler = repo.on_unrecognized_model

            context.install_unrecognized_model_hook(parent)
            _ = context.repo
            second_handler = repo.on_unrecognized_model

        self.assertIs(first_handler, second_handler)
        repo_cls.assert_called_once()


if __name__ == "__main__":
    unittest.main()
