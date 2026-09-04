"""Extract browser-safe standalone faces from the approved local TTC.

Code version: v1.0.0
"""

from hashlib import sha256
from pathlib import Path
import struct


FONT_ROOT = Path(__file__).resolve().parents[1] / "app/web/static/fonts"
SOURCE_SHA256 = "e10a317b9da0016c24a9fce70ccbd33eb39458da15253d5abfe051d8cc33e21a"
FACE_NAMES = (
    "Bold", "Light", "LightItalic", "Medium", "Regular", "Thin",
    "ThinItalic", "UltraLight", "UltraLightItalic",
)


def checksum(data: bytes | bytearray) -> int:
    """Compute the OpenType checksum over padded big-endian words."""
    padded = data + bytes((-len(data)) % 4)
    return sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF


def extract_face(source: bytes, offset: int) -> bytes:
    """Relocate shared TTC tables and rebuild the standalone font checksum."""
    count = struct.unpack_from(">H", source, offset + 4)[0]
    result = bytearray(source[offset:offset + 12]) + bytearray(16 * count)
    head_offset = None
    for index in range(count):
        tag, original_checksum, table_offset, length = struct.unpack_from(
            ">4sIII", source, offset + 12 + 16 * index,
        )
        table = bytearray(source[table_offset:table_offset + length])
        if len(table) != length:
            raise ValueError("The collection contains a truncated table.")
        if tag == b"head":
            table[8:12] = bytes(4)
            head_offset = len(result)
        if checksum(table) != original_checksum:
            raise ValueError(f"Invalid source table checksum: {tag!r}")
        struct.pack_into(
            ">4sIII", result, 12 + 16 * index,
            tag, original_checksum, len(result), length,
        )
        result.extend(table)
        result.extend(bytes((-length) % 4))
    if head_offset is None:
        raise ValueError("The collection face has no head table.")
    struct.pack_into(
        ">I", result, head_offset + 8, (0xB1B0AFBA - checksum(result)) & 0xFFFFFFFF,
    )
    return bytes(result)


def main() -> None:
    source = (FONT_ROOT / "UniversNextforHSBC.ttc").read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("The approved font source checksum changed.")
    if source[:4] != b"ttcf" or struct.unpack_from(">I", source, 8)[0] != len(FACE_NAMES):
        raise ValueError("Unexpected font collection structure.")
    for index, name in enumerate(FACE_NAMES):
        offset = struct.unpack_from(">I", source, 12 + 4 * index)[0]
        target = FONT_ROOT / f"UniversNextforHSBC-{name}.ttf"
        target.write_bytes(extract_face(source, offset))
        print(target.name)


if __name__ == "__main__":
    main()
