from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseEnvelope(BaseModel, Generic[T]):
    """Matches the controllers' `{success, data, error, meta}` envelope so the
    React `Envelope<T>` unwrap works identically in both modes."""

    success: bool = True
    data: T
    error: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
