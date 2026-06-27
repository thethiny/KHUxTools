from dataclasses import dataclass
import struct


@dataclass
class AKBData:
    magic: bytes
    version: int
    header_size: int
    total_size: int
    sample_rate: int
    channels: int
    ogg_offset: int
    ogg_data: bytes
    raw_data: bytes


def parse_akb(data: bytes) -> AKBData:
    if len(data) < 16 or data[:4] != b"AKB ":
        raise ValueError("Not a valid AKB file")

    version = struct.unpack_from("<H", data, 4)[0]
    header_size = struct.unpack_from("<H", data, 6)[0]
    total_size = struct.unpack_from("<I", data, 8)[0]

    ogg_offset = data.find(b"OggS")
    if ogg_offset < 0:
        ogg_offset = header_size if header_size < len(data) else len(data)

    ogg_data = data[ogg_offset:] if ogg_offset < len(data) else b""

    sample_rate = 0
    channels = 0
    if ogg_data and len(ogg_data) > 40:
        vorbis_pos = ogg_data.find(b"\x01vorbis")
        if vorbis_pos >= 0 and vorbis_pos + 16 <= len(ogg_data):
            channels = ogg_data[vorbis_pos + 7]
            sample_rate = struct.unpack_from("<I", ogg_data, vorbis_pos + 8)[0]

    return AKBData(
        magic=data[:4],
        version=version,
        header_size=header_size,
        total_size=total_size,
        sample_rate=sample_rate,
        channels=channels,
        ogg_offset=ogg_offset,
        ogg_data=ogg_data,
        raw_data=data,
    )
