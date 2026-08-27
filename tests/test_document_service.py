import io
import zipfile

import pytest

from app.services.document_service import DocumentError, DocumentService


def test_extract_utf8_text_document() -> None:
    content = "# 登录需求\n用户输入账号密码后可以登录。".encode()
    assert "用户输入" in DocumentService.extract("requirement.md", content)


def test_extract_docx_paragraphs() -> None:
    xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>Login requirement</w:t></w:r></w:p>
      <w:p><w:r><w:t>User can sign in successfully</w:t></w:r></w:p></w:body>
    </w:document>'''
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)

    assert DocumentService.extract("requirement.docx", buffer.getvalue()) == (
        "Login requirement\nUser can sign in successfully"
    )


def test_reject_unsupported_document() -> None:
    with pytest.raises(DocumentError, match="仅支持"):
        DocumentService.extract("requirement.pdf", b"some requirement text")
