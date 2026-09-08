from click.testing import CliRunner
from chatsite.cli import main


def test_todo_service_commands_are_registered():
    result = CliRunner().invoke(main, ['--tree'])
    assert result.exit_code == 0
    assert 'todo' in result.output and 'serve' in result.output and 'check' in result.output
    for command in ('serve', 'check'):
        result = CliRunner().invoke(main, ['todo', command, '--help'])
        assert result.exit_code == 0
