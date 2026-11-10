"""Bounded local text extraction for uploaded workflow materials."""

import base64
import binascii
from hashlib import sha256
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile


KINDS = {"spec": "规格书", "test": "测试报告", "manual": "说明书", "faq": "售后 FAQ"}
MAX_FILE = 4 * 1024 * 1024
MAX_REQUEST = ((MAX_FILE + 2) // 3) * 4 + 16 * 1024
MAX_TEXT = 120_000
MAX_DOCX_XML = 2 * 1024 * 1024
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentError(ValueError):
    def __init__(self, message, status=HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


def docx_text(raw):
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML:
                raise DocumentError("DOCX 正文过大，请拆分后再上传。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            xml = archive.read(info)
        markup = xml.decode("utf-8-sig")
        if "<!DOCTYPE" in markup.upper() or "<!ENTITY" in markup.upper():
            raise DocumentError("DOCX 正文包含不支持的 XML 声明。")
        root = ET.fromstring(markup)
        if root.tag != WORD_NS + "document":
            raise DocumentError("未在 DOCX 中识别到 Word 正文。")
        paragraphs = root.iter(WORD_NS + "p")
        return "\n".join("".join(node.text or "" for node in p.iter(WORD_NS + "t")) for p in paragraphs)
    except (zipfile.BadZipFile, KeyError, UnicodeError, ET.ParseError, RuntimeError, NotImplementedError) as exc:
        raise DocumentError("DOCX 无法读取，请重新导出可编辑的 Word 文档。") from exc


def pdf_text(raw):
    if not raw.startswith(b"%PDF-"):
        raise DocumentError("文件内容与 PDF 格式不符。")
    executable = shutil.which("pdftotext")
    if not executable:
        raise DocumentError("本机尚无 PDF 文本提取工具，可先将资料转成 DOCX 或 TXT。", HTTPStatus.SERVICE_UNAVAILABLE)
    try:
        result = subprocess.run(
            [executable, "-enc", "UTF-8", "-layout", "-", "-"],
            input=raw,
            capture_output=True,
            timeout=12,
            check=True,
        )
        return result.stdout.decode("utf-8")
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise DocumentError("PDF 无法提取文本，请检查文件是否加密、损坏或过长。") from exc


def parse_document(kind, name, encoded, *, kinds=KINDS):
    if not isinstance(kind, str) or kind not in kinds:
        raise DocumentError(f'请选择{"、".join(kinds.values())}中的一类资料。')
    if not isinstance(name, str):
        raise DocumentError("缺少资料文件名。")
    name = name.strip()
    if not name or len(name) > 180 or not name.isprintable() or "/" in name or "\\" in name:
        raise DocumentError("资料文件名无效。")
    extension = Path(name).suffix.lower()
    if extension not in {".md", ".txt", ".pdf", ".docx"}:
        raise DocumentError("请选择 PDF、DOCX、Markdown 或 TXT。", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    if not isinstance(encoded, str) or not encoded:
        raise DocumentError("缺少资料文件内容。")
    if len(encoded) > ((MAX_FILE + 2) // 3) * 4:
        raise DocumentError("单份资料不得超过 4 MiB。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DocumentError("资料文件传输格式不正确，请重新选择。") from exc
    if len(raw) > MAX_FILE:
        raise DocumentError("单份资料不得超过 4 MiB。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    if extension == ".docx":
        content = docx_text(raw)
    elif extension == ".pdf":
        content = pdf_text(raw)
    else:
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeError as exc:
            raise DocumentError("请将 Markdown 或 TXT 保存为 UTF-8。") from exc
    if len(content) > MAX_TEXT:
        raise DocumentError("可提取正文超过 12 万字符，请拆分后再上传。", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    if any(not (char.isprintable() or char.isspace()) for char in content):
        raise DocumentError("文件包含无法读取的正文字符，请重新导出文本。")
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        raise DocumentError("没有可读取的正文。扫描件请先做 OCR 后再上传。")
    digest = sha256(raw).hexdigest()
    return {"id": f"DOC-{kind.upper()}-{digest[:12]}", "kind": kind, "name": name, "digest": digest,
            "size": len(raw), "lines": lines}, raw
