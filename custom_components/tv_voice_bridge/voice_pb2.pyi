from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DeviceInfo(_message.Message):
    __slots__ = ("model", "vendor", "unknown1", "unknown2", "package_name", "app_version")
    MODEL_FIELD_NUMBER: _ClassVar[int]
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    UNKNOWN1_FIELD_NUMBER: _ClassVar[int]
    UNKNOWN2_FIELD_NUMBER: _ClassVar[int]
    PACKAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    APP_VERSION_FIELD_NUMBER: _ClassVar[int]
    model: str
    vendor: str
    unknown1: int
    unknown2: str
    package_name: str
    app_version: str
    def __init__(self, model: _Optional[str] = ..., vendor: _Optional[str] = ..., unknown1: _Optional[int] = ..., unknown2: _Optional[str] = ..., package_name: _Optional[str] = ..., app_version: _Optional[str] = ...) -> None: ...

class Configure(_message.Message):
    __slots__ = ("features", "device_info")
    FEATURES_FIELD_NUMBER: _ClassVar[int]
    DEVICE_INFO_FIELD_NUMBER: _ClassVar[int]
    features: int
    device_info: DeviceInfo
    def __init__(self, features: _Optional[int] = ..., device_info: _Optional[_Union[DeviceInfo, _Mapping]] = ...) -> None: ...

class SetActive(_message.Message):
    __slots__ = ("active",)
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    active: int
    def __init__(self, active: _Optional[int] = ...) -> None: ...

class PingRequest(_message.Message):
    __slots__ = ("val1", "val2")
    VAL1_FIELD_NUMBER: _ClassVar[int]
    VAL2_FIELD_NUMBER: _ClassVar[int]
    val1: int
    val2: int
    def __init__(self, val1: _Optional[int] = ..., val2: _Optional[int] = ...) -> None: ...

class PingResponse(_message.Message):
    __slots__ = ("val1",)
    VAL1_FIELD_NUMBER: _ClassVar[int]
    val1: int
    def __init__(self, val1: _Optional[int] = ...) -> None: ...

class KeyInject(_message.Message):
    __slots__ = ("key_code", "direction")
    KEY_CODE_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    key_code: int
    direction: int
    def __init__(self, key_code: _Optional[int] = ..., direction: _Optional[int] = ...) -> None: ...

class RemoteError(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ImeKeyInject(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RemoteStart(_message.Message):
    __slots__ = ("started",)
    STARTED_FIELD_NUMBER: _ClassVar[int]
    started: bool
    def __init__(self, started: bool = ...) -> None: ...

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

class ClientMessage(_message.Message):
    __slots__ = ("configure", "set_active", "ping_response", "key_inject", "voice_begin", "voice_audio", "voice_end")
    CONFIGURE_FIELD_NUMBER: _ClassVar[int]
    SET_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    PING_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    KEY_INJECT_FIELD_NUMBER: _ClassVar[int]
    VOICE_BEGIN_FIELD_NUMBER: _ClassVar[int]
    VOICE_AUDIO_FIELD_NUMBER: _ClassVar[int]
    VOICE_END_FIELD_NUMBER: _ClassVar[int]
    configure: Configure
    set_active: SetActive
    ping_response: PingResponse
    key_inject: KeyInject
    voice_begin: ClientVoiceBegin
    voice_audio: bytes
    voice_end: VoiceSessionId
    def __init__(self, configure: _Optional[_Union[Configure, _Mapping]] = ..., set_active: _Optional[_Union[SetActive, _Mapping]] = ..., ping_response: _Optional[_Union[PingResponse, _Mapping]] = ..., key_inject: _Optional[_Union[KeyInject, _Mapping]] = ..., voice_begin: _Optional[_Union[ClientVoiceBegin, _Mapping]] = ..., voice_audio: _Optional[bytes] = ..., voice_end: _Optional[_Union[VoiceSessionId, _Mapping]] = ...) -> None: ...

class ServerMessage(_message.Message):
    __slots__ = ("configure", "set_active", "error", "ping_request", "ime_key_inject", "voice_begin", "voice_close", "start")
    CONFIGURE_FIELD_NUMBER: _ClassVar[int]
    SET_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    PING_REQUEST_FIELD_NUMBER: _ClassVar[int]
    IME_KEY_INJECT_FIELD_NUMBER: _ClassVar[int]
    VOICE_BEGIN_FIELD_NUMBER: _ClassVar[int]
    VOICE_CLOSE_FIELD_NUMBER: _ClassVar[int]
    START_FIELD_NUMBER: _ClassVar[int]
    configure: Configure
    set_active: SetActive
    error: RemoteError
    ping_request: PingRequest
    ime_key_inject: ImeKeyInject
    voice_begin: ServerVoiceBegin
    voice_close: VoiceSessionId
    start: RemoteStart
    def __init__(self, configure: _Optional[_Union[Configure, _Mapping]] = ..., set_active: _Optional[_Union[SetActive, _Mapping]] = ..., error: _Optional[_Union[RemoteError, _Mapping]] = ..., ping_request: _Optional[_Union[PingRequest, _Mapping]] = ..., ime_key_inject: _Optional[_Union[ImeKeyInject, _Mapping]] = ..., voice_begin: _Optional[_Union[ServerVoiceBegin, _Mapping]] = ..., voice_close: _Optional[_Union[VoiceSessionId, _Mapping]] = ..., start: _Optional[_Union[RemoteStart, _Mapping]] = ...) -> None: ...
