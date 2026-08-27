from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


ALLOWED_DOCUMENT_SUFFIXES = {".txt", ".md", ".docx"}
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_CHARS = 60_000
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentError(ValueError):
    pass


class DocumentService:
    @classmethod
    def extract(cls, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_DOCUMENT_SUFFIXES:
            raise DocumentError("仅支持 TXT、Markdown 和 DOCX 需求文档")
        if not content:
            raise DocumentError("需求文档不能为空")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise DocumentError("需求文档不能超过 5 MB")

        if suffix == ".docx":
            text = cls._extract_docx(content)
        else:
            text = cls._decode_text(content)
        text = cls._normalize(text)
        if len(text) < 10:
            raise DocumentError("需求文档有效内容过少")
        return text[:MAX_DOCUMENT_CHARS]

    @staticmethod
    def _decode_text(content: bytes) -> str:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise DocumentError("文档编码无法识别，请使用 UTF-8 编码")

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                xml = archive.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise DocumentError("DOCX 文档损坏或格式无效") from exc
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            raise DocumentError("DOCX 文档内容无法解析") from exc

        paragraphs: list[str] = []
        for paragraph in root.iter(f"{WORD_NAMESPACE}p"):
            value = "".join(
                node.text or "" for node in paragraph.iter(f"{WORD_NAMESPACE}t")
            ).strip()
            if value:
                paragraphs.append(value)
        return "\n".join(paragraphs)

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
