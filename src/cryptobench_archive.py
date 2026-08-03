"""Pure ZIP central-directory parsing for the RI-3 source preflight.

The preflight reads only ZIP metadata through HTTP Range requests. It does not
materialize any CIF member or download the full CryptoBench archive.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any, Mapping, Sequence
import zlib


ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
ZIP_LOCAL_SIGNATURE = b"PK\x03\x04"
ZIP_EOCD_FORMAT = "<4s4H2LH"
ZIP_CENTRAL_FORMAT = "<4s6H3L5H2L"
ZIP_LOCAL_FORMAT = "<4s5H3L2H"
ZIP_EOCD_SIZE = struct.calcsize(ZIP_EOCD_FORMAT)
ZIP_CENTRAL_SIZE = struct.calcsize(ZIP_CENTRAL_FORMAT)
ZIP_LOCAL_SIZE = struct.calcsize(ZIP_LOCAL_FORMAT)
ZIP64_SENTINEL = 0xFFFF
ZIP32_SIZE_SENTINEL = 0xFFFFFFFF


class ZipMetadataError(ValueError):
    """Raised when a remote ZIP metadata range is incomplete or unsupported."""


class ZipMemberError(ZipMetadataError):
    """Raised when a materialized ZIP member fails integrity checks."""


@dataclass(frozen=True)
class ZipDirectory:
    entry_count: int
    central_directory_size: int
    central_directory_offset: int
    comment_length: int


@dataclass(frozen=True)
class ZipMember:
    name: str
    compression_method: int
    flags: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    local_header_offset: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "compression_method": self.compression_method,
            "flags": self.flags,
            "crc32": f"{self.crc32:08x}",
            "compressed_size": self.compressed_size,
            "uncompressed_size": self.uncompressed_size,
            "local_header_offset": self.local_header_offset,
        }


def parse_end_of_central_directory(
    data: bytes,
    *,
    archive_size: int,
) -> ZipDirectory:
    """Parse the final ZIP directory record from a tail range."""

    position = data.rfind(ZIP_EOCD_SIGNATURE)
    if position < 0 or position + ZIP_EOCD_SIZE > len(data):
        raise ZipMetadataError("ZIP end-of-central-directory record is missing from range")
    (
        signature,
        disk,
        disk_start,
        entries_on_disk,
        entry_count,
        central_size,
        central_offset,
        comment_length,
    ) = struct.unpack_from(
        ZIP_EOCD_FORMAT,
        data,
        position,
    )
    if signature != ZIP_EOCD_SIGNATURE:
        raise ZipMetadataError("Invalid ZIP end-of-central-directory signature")
    if disk or disk_start or entries_on_disk != entry_count:
        raise ZipMetadataError("Multi-disk ZIP archives are not supported")
    if (
        entry_count == ZIP64_SENTINEL
        or central_size == ZIP32_SIZE_SENTINEL
        or central_offset == ZIP32_SIZE_SENTINEL
    ):
        raise ZipMetadataError("ZIP64 archive metadata requires an explicit support decision")
    if central_offset + central_size > archive_size:
        raise ZipMetadataError("ZIP central directory exceeds archive size")
    return ZipDirectory(
        entry_count=entry_count,
        central_directory_size=central_size,
        central_directory_offset=central_offset,
        comment_length=comment_length,
    )


def parse_central_directory(
    data: bytes,
    *,
    expected_entry_count: int,
) -> tuple[ZipMember, ...]:
    """Parse central-directory entries without reading local file contents."""

    members: list[ZipMember] = []
    names: set[str] = set()
    position = 0
    while position < len(data):
        if position + ZIP_CENTRAL_SIZE > len(data):
            raise ZipMetadataError("ZIP central directory ends with a truncated header")
        values = struct.unpack_from(ZIP_CENTRAL_FORMAT, data, position)
        if values[0] != ZIP_CENTRAL_SIGNATURE:
            raise ZipMetadataError(f"Unexpected ZIP central signature at offset {position}")
        flags = values[3]
        compression_method = values[4]
        crc32 = values[7]
        compressed_size = values[8]
        uncompressed_size = values[9]
        name_length = values[10]
        extra_length = values[11]
        comment_length = values[12]
        local_header_offset = values[16]
        if (
            compressed_size == ZIP32_SIZE_SENTINEL
            or uncompressed_size == ZIP32_SIZE_SENTINEL
            or local_header_offset == ZIP32_SIZE_SENTINEL
        ):
            raise ZipMetadataError("ZIP64 member metadata requires an explicit support decision")
        end = position + ZIP_CENTRAL_SIZE + name_length + extra_length + comment_length
        if end > len(data):
            raise ZipMetadataError("ZIP central directory entry is truncated")
        name_bytes = data[position + ZIP_CENTRAL_SIZE : position + ZIP_CENTRAL_SIZE + name_length]
        name = _decode_member_name(name_bytes, flags)
        if not name or name in names:
            raise ZipMetadataError(f"ZIP member name is empty or duplicated: {name!r}")
        names.add(name)
        members.append(
            ZipMember(
                name=name,
                compression_method=compression_method,
                flags=flags,
                crc32=crc32,
                compressed_size=compressed_size,
                uncompressed_size=uncompressed_size,
                local_header_offset=local_header_offset,
            )
        )
        position = end
    if len(members) != expected_entry_count:
        raise ZipMetadataError(
            f"ZIP entry count mismatch: expected {expected_entry_count}, parsed {len(members)}"
        )
    return tuple(members)


def _decode_member_name(name_bytes: bytes, flags: int) -> str:
    encoding = "utf-8" if flags & 0x800 else "cp437"
    try:
        return name_bytes.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ZipMetadataError("ZIP member name is not decodable") from exc


def parse_local_file_header(data: bytes, *, member: ZipMember) -> int:
    """Validate a local header and return the compressed-data offset."""

    if len(data) < ZIP_LOCAL_SIZE:
        raise ZipMemberError("ZIP local header range is truncated")
    values = struct.unpack_from(ZIP_LOCAL_FORMAT, data, 0)
    if values[0] != ZIP_LOCAL_SIGNATURE:
        raise ZipMemberError("Invalid ZIP local-file signature")
    flags = values[2]
    compression_method = values[3]
    crc32 = values[6]
    compressed_size = values[7]
    uncompressed_size = values[8]
    name_length = values[9]
    extra_length = values[10]
    header_end = ZIP_LOCAL_SIZE + name_length + extra_length
    if header_end > len(data):
        raise ZipMemberError("ZIP local header name/extra fields are truncated")
    name = _decode_member_name(data[ZIP_LOCAL_SIZE : ZIP_LOCAL_SIZE + name_length], flags)
    if name != member.name:
        raise ZipMemberError(
            f"ZIP local member name mismatch: expected {member.name!r}, got {name!r}"
        )
    if flags != member.flags:
        raise ZipMemberError("ZIP local and central member flags differ")
    if compression_method != member.compression_method:
        raise ZipMemberError("ZIP local and central compression methods differ")
    if not flags & 0x08 and (
        crc32 != member.crc32
        or compressed_size != member.compressed_size
        or uncompressed_size != member.uncompressed_size
    ):
        raise ZipMemberError("ZIP local and central member sizes or CRC differ")
    if flags & 0x01:
        raise ZipMemberError("Encrypted ZIP members are not supported")
    return header_end


def decode_member_payload(compressed: bytes, *, member: ZipMember) -> bytes:
    """Decompress and verify one ZIP member against central-directory metadata."""

    if len(compressed) != member.compressed_size:
        raise ZipMemberError(
            f"Compressed member length mismatch: expected {member.compressed_size}, "
            f"got {len(compressed)}"
        )
    try:
        if member.compression_method == 0:
            content = compressed
        elif member.compression_method == 8:
            content = zlib.decompress(compressed, wbits=-15)
        else:
            raise ZipMemberError(f"Unsupported ZIP compression method: {member.compression_method}")
    except zlib.error as exc:
        raise ZipMemberError("ZIP member deflate stream is invalid") from exc
    if len(content) != member.uncompressed_size:
        raise ZipMemberError(
            f"Uncompressed member length mismatch: expected {member.uncompressed_size}, "
            f"got {len(content)}"
        )
    if (zlib.crc32(content) & 0xFFFFFFFF) != member.crc32:
        raise ZipMemberError("ZIP member CRC-32 mismatch")
    return content


def member_map(members: Sequence[ZipMember]) -> Mapping[str, ZipMember]:
    """Build a case-insensitive lookup while preserving original names."""

    lookup: dict[str, ZipMember] = {}
    for member in members:
        key = member.name.casefold()
        if key in lookup:
            raise ZipMetadataError(f"Case-insensitive ZIP member collision: {member.name}")
        lookup[key] = member
    return lookup
