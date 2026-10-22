from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ClientVoiceBegin(_message.Message):
    __slots__ = ("session_id", "sample_rate", "channel_config", "audio_format")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_RATE_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_CONFIG_FIELD_NUMBER: _ClassVar[int]
    AUDIO_FORMAT_FIELD_NUMBER: _ClassVar[int]
    session_id: int
    sample_rate: int
    channel_config: int
    audio_format: int
    def __init__(self, session_id: _Optional[int] = ..., sample_rate: _Optional[int] = ..., channel_config: _Optional[int] = ..., audio_format: _Optional[int] = ...) -> None: ...

class VoiceSessionId(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: int
    def __init__(self, session_id: _Optional[int] = ...) -> None: ...

class ServerVoiceBegin(_message.Message):
    __slots__ = ("session_id", "package_name")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    session_id: int
    package_name: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, session_id: _Optional[int] = ..., package_name: _Optional[_Iterable[str]] = ...) -> None: ...

class ClientVoiceMessage(_message.Message):
    __slots__ = ("begin", "audio", "end")
    BEGIN_FIELD_NUMBER: _ClassVar[int]
    AUDIO_FIELD_NUMBER: _ClassVar[int]
    END_FIELD_NUMBER: _ClassVar[int]
    begin: ClientVoiceBegin
    audio: bytes
    end: VoiceSessionId
    def __init__(self, begin: _Optional[_Union[ClientVoiceBegin, _Mapping]] = ..., audio: _Optional[bytes] = ..., end: _Optional[_Union[VoiceSessionId, _Mapping]] = ...) -> None: ...

class ServerVoiceMessage(_message.Message):
    __slots__ = ("begin", "close")
    BEGIN_FIELD_NUMBER: _ClassVar[int]
    CLOSE_FIELD_NUMBER: _ClassVar[int]
    begin: ServerVoiceBegin
    close: VoiceSessionId
    def __init__(self, begin: _Optional[_Union[ServerVoiceBegin, _Mapping]] = ..., close: _Optional[_Union[VoiceSessionId, _Mapping]] = ...) -> None: ...
