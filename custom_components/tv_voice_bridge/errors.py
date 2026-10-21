"""Stable error codes, independent of user-visible translations."""


class VoiceError(Exception):
    """An expected failure safe to expose as a translation key."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
