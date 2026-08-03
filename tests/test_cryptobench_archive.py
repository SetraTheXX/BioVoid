from __future__ import annotations

from io import BytesIO
import zipfile

from src.cryptobench_archive import (
    decode_member_payload,
    member_map,
    parse_central_directory,
    parse_end_of_central_directory,
    parse_local_file_header,
)


def test_zip_metadata_parser_reads_members_without_extracting_contents() -> None:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("cif-files/1abc.cif", "data_1abc")
        archive.writestr("cif-files/2def.cif", "data_2def")
    payload = output.getvalue()
    directory = parse_end_of_central_directory(payload, archive_size=len(payload))
    central = payload[
        directory.central_directory_offset : directory.central_directory_offset
        + directory.central_directory_size
    ]
    members = parse_central_directory(central, expected_entry_count=2)
    lookup = member_map(members)
    assert lookup["cif-files/1abc.cif"].uncompressed_size == len("data_1abc")
    assert lookup["CIF-FILES/2DEF.CIF".casefold()].compression_method == zipfile.ZIP_DEFLATED

    member = lookup["cif-files/1abc.cif"]
    local_header = payload[member.local_header_offset : member.local_header_offset + 1024]
    data_offset = member.local_header_offset + parse_local_file_header(
        local_header,
        member=member,
    )
    compressed = payload[data_offset : data_offset + member.compressed_size]
    assert decode_member_payload(compressed, member=member) == b"data_1abc"
