"""UUIDv7 helper.

Python's stdlib gained `uuid.uuid7` only in 3.14; on the Odoo runtime (3.11/3.12)
it is absent, so fall back to a manual RFC 9562 v7 implementation: a 48-bit
Unix-ms timestamp + 74 random bits, with the version/variant nibbles set. v7 is
time-ordered, which keeps index locality good for a `tenant_uuid` column.
"""
import os
import time
import uuid

if hasattr(uuid, "uuid7"):
    uuid7 = uuid.uuid7
else:
    def uuid7() -> uuid.UUID:
        unix_ts_ms = int(time.time() * 1000)
        uuid_bytes = bytearray(unix_ts_ms.to_bytes(6, "big") + os.urandom(10))
        uuid_bytes[6] = (uuid_bytes[6] & 0x0F) | 0x70  # version 7
        uuid_bytes[8] = (uuid_bytes[8] & 0x3F) | 0x80  # variant 1 (RFC 4122)
        return uuid.UUID(bytes=bytes(uuid_bytes))
