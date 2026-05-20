"""Minimal local click compatibility layer for tests.

This project only needs ``click.testing.CliRunner`` in the current workspace.
The real Click package remains supported when installed; this shim only fills
the gap in stripped-down environments.
"""


class ClickException(Exception):
    pass


class Exit(Exception):
    def __init__(self, code: int = 0) -> None:
        super().__init__(code)
        self.exit_code = code


class BadParameter(ClickException):
    pass


class exceptions:
    Exit = Exit
    BadParameter = BadParameter
