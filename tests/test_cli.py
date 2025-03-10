import unittest
from unittest.mock import patch, MagicMock
from cli import main


class TestFuzzflow(unittest.TestCase):

    @patch('sys.argv', ['fuzzflow.py', '-c', 'test_configs', '-m', '1024', '-s', 'test_script.sh'])
    @patch('src.utils.parse_cli_args')
    @patch('src.utils.load_all_configs_in_dir', return_value=[])  # Заглушка для загрузки конфигов
    @patch('src.orchestrator.Orchestrator', autospec=True)
    def test_main_function(self, MockOrchestrator, mock_load_configs, mock_parse_cli_args):
        """
        Проверяем, что main() корректно создает Orchestrator и вызывает run().
        """
        # Подменяем `parse_cli_args()`, чтобы оно не падало с argparse
        mock_parse_cli_args.return_value = MagicMock(
            config_dir='test_configs',
            memory_limit=1024,
            single_fuzz_script='test_script.sh'
        )

        # Создаём мок-объект `Orchestrator`
        mock_orchestrator_instance = MockOrchestrator.return_value

        # Вызываем `main()`
        main()

        # Проверяем, что Orchestrator был вызван один раз с нужными аргументами
        MockOrchestrator.assert_called_once_with(
            config_dir='test_configs',
            memory_limit=1024,
            single_fuzz_script='test_script.sh'
        )

        # Проверяем, что `run()` был вызван
        mock_orchestrator_instance.run.assert_called_once()

    @patch('sys.argv', ['fuzzflow.py'])
    def test_missing_arguments(self):
        """
        Проверяем, что при отсутствии обязательных аргументов `parse_cli_args` вызывает SystemExit.
        """
        from src.utils import parse_cli_args
        with self.assertRaises(SystemExit):
            parse_cli_args()


if __name__ == '__main__':
    unittest.main()
