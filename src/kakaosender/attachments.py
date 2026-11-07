"""Decode selected photos once; dispatch the exact immutable previewed pixels."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

MAX_PHOTOS = 10
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 60 * 1024 * 1024
MAX_PIXELS = 24_000_000
PHOTO_FILTER = "사진 (*.jpg *.jpeg *.png *.webp *.bmp)"


@dataclass(frozen=True)
class Photo:
    name: str
    content: bytes = field(repr=False)
    width: int
    height: int
    thumbnail: bytes = field(default=b"", repr=False)
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.content.startswith(b"\x89PNG\r\n\x1a\n") or len(self.content) > MAX_IMAGE_BYTES:
            raise ValueError("사진을 PNG로 변환한 크기는 20 MB 이하여야 합니다.")
        object.__setattr__(self, "fingerprint", hashlib.sha256(self.content).hexdigest())


def load_photo(path: Path) -> Photo:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageReader

    if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("사진 파일은 한 장당 20 MB까지 선택할 수 있습니다.")
    # A memory buffer prevents later edits/deletion of the file changing the approved photo.
    with path.open("rb") as handle:
        source = handle.read(MAX_IMAGE_BYTES + 1)
    if len(source) > MAX_IMAGE_BYTES:
        raise ValueError("사진 파일은 한 장당 20 MB까지 선택할 수 있습니다.")
    buffer = QBuffer()
    buffer.setData(QByteArray(source))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    if bytes(reader.format()).lower() not in {b"jpeg", b"png", b"webp", b"bmp"}:
        raise ValueError("JPG, PNG, WEBP, BMP 사진을 선택해 주세요.")
    if reader.supportsAnimation():
        raise ValueError("움직이는 이미지는 지원하지 않습니다. 정지 사진을 선택해 주세요.")
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > MAX_PIXELS:
        raise ValueError("사진은 2,400만 화소까지 지원합니다.")
    image = reader.read()
    if image.isNull():
        raise ValueError("사진을 읽지 못했습니다. 파일이 손상되지 않았는지 확인해 주세요.")
    output = QBuffer()
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(output, "PNG"):
        raise ValueError("사진을 전송용 이미지로 변환하지 못했습니다.")
    from PySide6.QtCore import Qt
    thumbnail = image.scaled(288, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    small = QBuffer()
    small.open(QIODevice.OpenModeFlag.WriteOnly)
    if not thumbnail.save(small, "PNG"):
        raise ValueError("사진 미리보기를 만들지 못했습니다.")
    return Photo(path.name, bytes(output.data()), image.width(), image.height(), bytes(small.data()))


def validate_photos(photos: tuple[Photo, ...]) -> None:
    if len(photos) > MAX_PHOTOS:
        raise ValueError("사진은 한 번에 10장까지 선택할 수 있습니다.")
    if sum(len(photo.content) for photo in photos) > MAX_TOTAL_BYTES:
        raise ValueError("전송용 사진의 합계는 60 MB까지 지원합니다.")
    if len({photo.fingerprint for photo in photos}) != len(photos):
        raise ValueError("같은 사진이 중복으로 선택되었습니다.")
