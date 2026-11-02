"""Движок шаблонов: проверка загружаемого .docx и безопасный рендер.

Тесты чистые (без БД). Шаблоны собираются фабрикой `make_docx` через python-docx;
опасные варианты пакета - подменой/добавлением частей zip или сборкой zip «вручную»
(`raw_zip`), когда нужен лживый заголовок.
"""

import io
import logging
import os
import resource
import struct
import subprocess
import sys
import textwrap
import time
import zipfile
import zlib

import jinja2
import pytest
from docx import Document

from apps.documents import engine
from apps.documents.catalog import KINDS, placeholders, sample_context
from apps.documents.errors import DocumentError

KIND = "order_request"
LOOP_ROWS = [
    ["{%tr for c in order.consignments %}", ""],
    ["{{ c.name }}", "{{ c.weight_kg }}"],
    ["{%tr endfor %}", ""],
]
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def make_docx(text_or_body="Заказ {{ order.number }}", extra_parts=None, table_rows=None):
    """Собрать .docx: абзацы текста, необязательная таблица, доп./заменённые части zip.

    `text_or_body` - строка (один абзац) или список строк (абзацы).
    `table_rows` - список строк таблицы (списки текстов ячеек).
    `extra_parts` - {имя части: bytes | None}: добавить/заменить часть, None - удалить.
    """
    doc = Document()
    paragraphs = [text_or_body] if isinstance(text_or_body, str) else list(text_or_body)
    for text in paragraphs:
        doc.add_paragraph(text)
    if table_rows:
        table = doc.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for r, row in enumerate(table_rows):
            for c, text in enumerate(row):
                table.cell(r, c).text = text
    buf = io.BytesIO()
    doc.save(buf)
    data = buf.getvalue()
    if extra_parts:
        data = rewrite_zip(data, extra_parts)
    return data


def rewrite_zip(data, parts):
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.filename in parts:
                continue
            dst.writestr(info.filename, src.read(info.filename))
        for name, content in parts.items():
            if content is not None:
                dst.writestr(name, content)
    return out.getvalue()


def patch_part(data, name, old, new):
    content = read_part(data, name).decode()
    assert old in content
    return rewrite_zip(data, {name: content.replace(old, new, 1).encode()})


def add_relationship(data, rel_type, target, extra=""):
    return patch_part(
        data,
        "word/_rels/document.xml.rels",
        "</Relationships>",
        f'<Relationship Id="rIdX" Type="http://schemas.openxmlformats.org/officeDocument/'
        f'2006/relationships/{rel_type}" Target="{target}"{extra}/></Relationships>',
    )


def _deflate(raw):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(raw) + c.flush()


def raw_zip(members):
    """Собрать zip вручную: members = [(имя, сжатые байты, метод, crc, заявленный размер)]."""
    out, cd = bytearray(), bytearray()
    for name, raw, method, crc, usize in members:
        n = name.encode()
        off = len(out)
        out += struct.pack(
            "<IHHHHHIIIHH", 0x04034B50, 20, 0, method, 0, 0, crc, len(raw), usize, len(n), 0
        )
        out += n + raw
        cd += struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50, 20, 20, 0, method, 0, 0, crc, len(raw), usize, len(n), 0, 0, 0, 0, 0, off,
        )  # fmt: skip
        cd += n
    cd_off = len(out)
    out += cd
    out += struct.pack(
        "<IHHHHIIH", 0x06054B50, 0, 0, len(members), len(members), len(cd), cd_off, 0
    )
    return bytes(out)


def honest_members(data):
    zf = zipfile.ZipFile(io.BytesIO(data))
    result = []
    for info in zf.infolist():
        content = zf.read(info)
        result.append((info.filename, _deflate(content), 8, zlib.crc32(content), len(content)))
    return result


def lying_bomb(megabytes, crc_matches_declared):
    """Часть, заявленная как 10 байт, на деле - `megabytes` МБ нулей после распаковки."""
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    chunk = b"\0" * (1024 * 1024)
    comp = b"".join(c.compress(chunk) for _ in range(megabytes)) + c.flush()
    crc = zlib.crc32(b"\0" * 10) if crc_matches_declared else 0
    return raw_zip(honest_members(make_docx()) + [("word/media/a.txt", comp, 8, crc, 10)])


def read_part(data, name):
    return zipfile.ZipFile(io.BytesIO(data)).read(name)


def docx_text(data):
    doc = Document(io.BytesIO(data))
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(lines)


# Отличительные фрагменты сообщений: тест атаки обязан проверить ПРИЧИНУ отказа,
# а не только код, иначе он прошёл бы при отказе по посторонней причине.
FORBIDDEN = "запрещённую операцию"
COMPLEX = "слишком сложный"
MACRO = "макрос"
EXTERNAL = "внешние ссылки"
DTD = "DTD"
ENCODING = "UTF-8"
UNPACKED = "распакованном виде"
CORRUPT = "повреждён"
EMBEDDED = "встроенные объекты"
INCLUDE = "Подключение других шаблонов"


def assert_invalid(data, contains, kind=KIND, code="template_invalid"):
    with pytest.raises(DocumentError) as ei:
        engine.validate_upload(data, kind)
    assert ei.value.get_codes() == code
    assert ei.value.status_code == 400
    message = str(ei.value.detail)
    assert contains in message, message
    return message


def assert_render_invalid(data, contains, context=None):
    with pytest.raises(DocumentError) as ei:
        engine.render_docx(data, context if context is not None else sample_context(KIND))
    assert ei.value.get_codes() == "template_invalid"
    message = str(ei.value.detail)
    assert contains in message, message
    return message


def assert_no_internals(message):
    for leak in ("Traceback", "/home", "/tmp", "site-packages", "__", "object at 0x", "File "):
        assert leak not in message, message


def maxrss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


# --- обязательные тесты из брифа ---------------------------------------------------------


def test_valid_template_passes():
    engine.validate_upload(make_docx(table_rows=LOOP_ROWS), KIND)


def test_too_large_rejected():
    data = b"x" * (engine.MAX_TEMPLATE_BYTES + 1)
    assert_invalid(data, "больше 2 МБ", code="template_too_large")


def test_not_a_zip_rejected():
    assert_invalid(b"hello", "не является документом Word")


def test_zip_bomb_rejected():
    big = b"\0" * (25 * 1024 * 1024)
    data = make_docx(extra_parts={"word/media/bomb.txt": big})
    assert len(data) < engine.MAX_TEMPLATE_BYTES  # маленький файл, огромная распаковка
    assert_invalid(data, UNPACKED)


@pytest.mark.parametrize("part", ["word/vbaProject.bin", "word/VBAPROJECT.BIN", "word/x.bin"])
def test_macros_rejected(part):
    assert_invalid(make_docx(extra_parts={part: b"\xd0\xcf\x11\xe0macro"}), MACRO)


def test_external_relationship_rejected():
    data = add_relationship(
        make_docx(), "attachedTemplate", "http://evil.example/t.dotm", ' TargetMode="External"'
    )
    assert_invalid(data, EXTERNAL)


def test_unknown_placeholder_rejected():
    message = assert_invalid(make_docx("Номер {{ order.nope }}"), "order.nope")
    assert_no_internals(message)


def test_unknown_placeholder_in_loop_names_full_path():
    rows = [
        ["{%tr for c in order.consignments %}", ""],
        ["{{ c.nope }}", ""],
        ["{%tr endfor %}", ""],
    ]
    assert_invalid(make_docx(table_rows=rows), "order.consignments[].nope")


def test_unknown_root_placeholder_rejected():
    assert_invalid(make_docx("{{ nope }}"), "Неизвестная метка: nope")


def test_syntax_error_rejected():
    message = assert_invalid(make_docx(["Первый абзац", "{% for x in %}"]), "строка 2")
    assert "Синтаксическая" in message
    assert_no_internals(message)


SANDBOX_PAYLOADS = [
    "{{ ''.__class__.__mro__ }}",
    "{{ order.number.__class__ }}",
    "{{ ''.__class__.__mro__[1].__subclasses__() }}",
    "{{ cycler.__init__.__globals__ }}",
    "{{ joiner.__init__.__globals__ }}",
    "{{ namespace.__init__.__globals__ }}",
    "{{ range.__self__ }}",
    "{{ dict.mro() }}",
    "{{ self._TemplateReference__context }}",
    "{{ self.__init__.__globals__ }}",
    "{{ order['__class__'] }}",
    "{{ (order|attr('__class__')) }}",
    "{{ lipsum.__globals__ }}",
]


@pytest.mark.parametrize("expr", SANDBOX_PAYLOADS)
def test_sandbox_blocks_attribute_walk(expr):
    message = assert_invalid(make_docx(expr), FORBIDDEN)
    assert_no_internals(message)
    # и в рабочем рендере - ошибка, а не пустая строка с выполненным кодом
    assert_render_invalid(make_docx(expr), FORBIDDEN)


# `range.__self__` в обычном Jinja просто не определён (range - тип), поэтому исключён.
LEAKING_WITHOUT_SANDBOX = [p for p in SANDBOX_PAYLOADS if p != "{{ range.__self__ }}"]


@pytest.mark.parametrize("expr", LEAKING_WITHOUT_SANDBOX)
def test_mutation_plain_jinja_would_leak(expr):
    """Мутационная проверка: без песочницы те же полезные нагрузки «работают».

    Если бы engine рендерил обычным `jinja2.Environment`, они вывели бы внутренности
    Python - значит, test_sandbox_blocks_attribute_walk ловит именно песочницу.
    """
    out = jinja2.Environment().from_string(expr).render(sample_context(KIND))
    assert out.strip()
    assert any(s in out for s in ("class", "function", "module", "built-in", "Context", "{"))


def test_render_fills_text_and_loop():
    ctx = sample_context(KIND)
    data = engine.render_docx(make_docx("Заказ {{ order.number }}", table_rows=LOOP_ROWS), ctx)
    text = docx_text(data)
    assert f"Заказ {ctx['order']['number']}" in text
    for c in ctx["order"]["consignments"]:
        assert c["name"] in text
        assert c["weight_kg"] in text
    assert "{{" not in text and "{%" not in text


def test_render_missing_optional_is_blank():
    ctx = sample_context(KIND)
    del ctx["order"]["comment"]
    data = engine.render_docx(make_docx("Комментарий:[{{ order.comment }}]"), ctx)
    assert "Комментарий:[]" in docx_text(data)


def test_render_missing_nested_optional_is_blank():
    data = engine.render_docx(make_docx("[{{ order.nope.deeper }}]"), sample_context(KIND))
    assert "[]" in docx_text(data)


def test_render_huge_range_is_bounded():
    started = time.monotonic()
    data = make_docx("{% for i in range(10**9) %}x{% endfor %}")
    assert_invalid(data, COMPLEX)
    assert_render_invalid(data, COMPLEX)
    assert time.monotonic() - started < 10


# --- пакет: дополнительные угрозы --------------------------------------------------------


@pytest.mark.parametrize("crc_ok", [False, True], ids=["bad-crc", "crc-of-declared"])
def test_zip_bomb_with_lying_header_rejected(crc_ok):
    data = lying_bomb(64, crc_ok)
    assert len(data) < engine.MAX_TEMPLATE_BYTES
    assert_invalid(data, CORRUPT)
    assert_render_invalid(data, CORRUPT)


_MEASURE_SCRIPT = textwrap.dedent(
    """
    import os, resource, sys, time, django
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_test"
    os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-0123456789-abcdefghijklmnop")
    django.setup()
    from apps.documents import engine
    from apps.documents.errors import DocumentError
    data = open(sys.argv[1], "rb").read()
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    t = time.monotonic()
    try:
        engine.validate_upload(data, "order_request")
        print("ACCEPTED")
    except DocumentError as exc:
        print("REJECTED", exc.detail)
    grown = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
    print("GROWN_MB", grown // 1024, "SECONDS", round(time.monotonic() - t, 2))
    """
)


def validate_in_subprocess(tmp_path, data):
    """validate_upload в отдельном процессе: (первая строка вывода, рост пика RSS в МБ, секунды).

    ru_maxrss веб-процесса не включает дочерний процесс рендера - меряется именно
    память того процесса, что вызвал validate_upload.
    """
    path = tmp_path / "upload.docx"
    path.write_bytes(data)
    proc = subprocess.run(
        [sys.executable, "-c", _MEASURE_SCRIPT, str(path)],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.split("\n")
    stats = lines[1].split()
    return lines[0], int(stats[1]), float(stats[3])


def test_zip_bomb_with_lying_header_does_not_inflate_memory(tmp_path):
    """300 МБ нулей под заголовком «10 байт»: отказ без роста памяти веб-процесса."""
    outcome, grown_mb, seconds = validate_in_subprocess(tmp_path, lying_bomb(300, True))
    assert outcome.startswith("REJECTED") and CORRUPT in outcome, outcome
    assert grown_mb < 40, grown_mb
    assert seconds < 5, seconds


XML_COMPLEX = "элементов XML"
XML_AMPLIFIERS = {
    "elements": b"<a/>",
    "attributes": b'<a b="" c="" d="" e="" f="" g="" h=""/>',
    "text": b"<a>x</a>",
    "pi": b"<?a?>",
    "comments": b"<!---->",
}


def xml_amplifier_docx(body):
    """Две XML-части почти по пределу части: мелкие узлы, честные заголовки zip."""
    limit = engine.MAX_MEMBER_BYTES - 500_000
    head = (
        b'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.'
        b'openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    )
    tail = b"</w:body></w:document>"
    doc = head + body * ((limit - len(head) - len(tail)) // len(body)) + tail
    junk = b"<x>" + body * ((limit - 10) // len(body)) + b"</x>"
    return make_docx(extra_parts={"word/document.xml": doc, "word/media/junk.xml": junk})


@pytest.mark.parametrize("shape", sorted(XML_AMPLIFIERS))
def test_xml_amplifier_does_not_inflate_web_process(shape, tmp_path):
    """Миллионы узлов XML: отказ с понятной причиной, память веб-процесса не растёт.

    Разбор XML идёт в дочернем процессе с лимитами, потоково и со счётчиком узлов.
    """
    data = xml_amplifier_docx(XML_AMPLIFIERS[shape])
    assert len(data) < engine.MAX_TEMPLATE_BYTES
    outcome, grown_mb, seconds = validate_in_subprocess(tmp_path, data)
    assert outcome.startswith("REJECTED") and XML_COMPLEX in outcome, outcome
    assert grown_mb < 50, grown_mb
    assert seconds < engine.RENDER_KILL_SECONDS + 2, seconds


@pytest.mark.parametrize("shape", sorted(XML_AMPLIFIERS))
def test_xml_amplifier_rejected_by_node_budget(shape, monkeypatch, settings):
    # та же причина и без дочернего процесса: счётчик узлов, а не нехватка памяти
    monkeypatch.setattr(engine, "resource", None)
    settings.DOCUMENTS_ALLOW_UNISOLATED_RENDER = True
    assert_invalid(xml_amplifier_docx(XML_AMPLIFIERS[shape]), XML_COMPLEX)


def test_web_process_does_not_parse_xml(monkeypatch):
    """В веб-процессе проверяется только каталог zip; lxml-разбор - только в дочернем."""
    calls = []
    real = engine._scan_xml

    def spy(*args, **kwargs):
        calls.append(os.getpid())
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "_scan_xml", spy)
    engine.validate_upload(make_docx(), KIND)
    assert os.getpid() not in calls


XXE = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<!DOCTYPE w:document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>"
)

LAUGHS = (
    b'<?xml version="1.0"?>\n<!DOCTYPE lolz [<!ENTITY lol "lol">'
    b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>\n'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>&lol3;</w:t></w:r></w:p></w:body></w:document>"
)


@pytest.mark.parametrize("payload", [XXE, LAUGHS], ids=["xxe", "billion-laughs"])
def test_xml_dtd_and_entities_rejected(payload):
    data = make_docx(extra_parts={"word/document.xml": payload})
    message = assert_invalid(data, DTD)
    assert "passwd" not in message
    # рабочий рендер тоже перепроверяет пакет и не раскрывает сущности
    assert_render_invalid(data, DTD)


@pytest.mark.parametrize(
    "part", ["word/styles.xml", "word/header1.xml", "word/footer1.xml", "word/footnotes.xml"]
)
def test_dtd_in_any_xml_part_rejected(part):
    payload = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>'
    assert_invalid(make_docx(extra_parts={part: payload}), DTD)


def _dtd_document(encoding):
    body = (
        '<!DOCTYPE w:document [<!ENTITY lol "LOLENTITY">]>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>&lol; Z</w:t></w:r></w:p></w:body></w:document>"
    )
    decl = f'<?xml version="1.0" encoding="{encoding}"?>'
    if encoding == "UTF-7":
        return (decl + body.replace("<!", "+ADw-!")).encode("ascii")
    return (decl + body).encode({"IBM037": "cp037", "UTF-16": "utf-16"}[encoding])


@pytest.mark.parametrize("encoding", ["UTF-7", "IBM037", "UTF-16"])
def test_non_utf8_xml_part_rejected(encoding):
    data = make_docx(extra_parts={"word/document.xml": _dtd_document(encoding)})
    assert_invalid(data, ENCODING)
    assert_render_invalid(data, ENCODING)


def test_declared_encoding_must_be_utf8_even_for_ascii_bytes():
    xml = b'<?xml version="1.0" encoding="ISO-8859-1"?><x/>'
    assert_invalid(make_docx(extra_parts={"word/styles.xml": xml}), ENCODING)


@pytest.mark.parametrize(
    "name",
    ["../evil.xml", "word/../../evil.xml", "/etc/evil.xml", "C:/evil.xml", "word\\evil.xml"],
)
def test_path_traversal_member_rejected(name):
    assert_invalid(make_docx(extra_parts={name: b"<x/>"}), "Недопустимое имя")


def test_duplicate_member_rejected():
    import warnings

    data = make_docx()
    out = io.BytesIO(data)
    with zipfile.ZipFile(out, "a") as zf:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            zf.writestr("word/document.xml", b"<x/>")
    assert_invalid(out.getvalue(), "повторяющиеся")


def test_encrypted_member_rejected():
    data = bytearray(make_docx())
    zf = zipfile.ZipFile(io.BytesIO(bytes(data)))
    info = zf.getinfo("word/document.xml")
    # бит 0 флагов "зашифровано" в локальном заголовке и в центральном каталоге
    data[info.header_offset + 6] |= 0x01
    cd = bytes(data).find(b"PK\x01\x02")
    while cd != -1:
        name_len = int.from_bytes(data[cd + 28 : cd + 30], "little")
        if bytes(data[cd + 46 : cd + 46 + name_len]) == b"word/document.xml":
            data[cd + 8] |= 0x01
            break
        cd = bytes(data).find(b"PK\x01\x02", cd + 4)
    assert zipfile.ZipFile(io.BytesIO(bytes(data))).getinfo("word/document.xml").flag_bits & 1
    assert_invalid(bytes(data), "зашифрован")


def test_too_many_entries_rejected():
    parts = {f"word/media/f{i}.txt": b"" for i in range(engine.MAX_ZIP_ENTRIES + 1)}
    assert_invalid(make_docx(extra_parts=parts), "слишком много частей")


@pytest.mark.parametrize("missing", ["[Content_Types].xml", "word/document.xml"])
def test_missing_required_part_rejected(missing):
    assert_invalid(make_docx(extra_parts={missing: None}), "обязательных частей")


def test_macro_enabled_content_type_rejected():
    data = patch_part(
        make_docx(),
        "[Content_Types].xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "application/vnd.ms-word.document.macroEnabled.main+xml",
    )
    assert_invalid(data, MACRO)


# --- встроенные пакеты и объекты ----------------------------------------------------------


def _nested_docx_with_macro():
    return make_docx(extra_parts={"word/vbaProject.bin": b"\xd0\xcf\x11\xe0macro"})


def test_embedded_docx_with_macro_rejected():
    data = make_docx(extra_parts={"word/embeddings/evil.docx": _nested_docx_with_macro()})
    data = add_relationship(data, "package", "embeddings/evil.docx")
    data = patch_part(
        data,
        "[Content_Types].xml",
        "</Types>",
        '<Default Extension="docx" ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.document"/></Types>',
    )
    assert_invalid(data, EMBEDDED)
    assert_render_invalid(data, EMBEDDED)


def test_embedded_xlsx_rejected():
    xlsx = io.BytesIO()
    with zipfile.ZipFile(xlsx, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
    data = make_docx(
        extra_parts={"word/embeddings/Microsoft_Excel_Worksheet.xlsx": xlsx.getvalue()}
    )
    assert_invalid(data, EMBEDDED)


def test_ole_object_rejected():
    data = make_docx(extra_parts={"word/embeddings/oleObject1.bin": b"\xd0\xcf\x11\xe0ole"})
    assert_invalid(data, EMBEDDED)


def test_nested_zip_outside_embeddings_rejected():
    # тот же вложенный docx, но спрятанный под видом картинки
    data = make_docx(extra_parts={"word/media/image1.png": _nested_docx_with_macro()})
    assert_invalid(data, EMBEDDED)


def test_ole_magic_outside_embeddings_rejected():
    data = make_docx(extra_parts={"word/media/image1.emf": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"})
    assert_invalid(data, EMBEDDED)


@pytest.mark.parametrize("rel_type", ["package", "oleObject", "control", "aFChunk"])
def test_embedding_relationship_rejected(rel_type):
    data = add_relationship(make_docx(), rel_type, "media/whatever.dat")
    assert_invalid(data, EMBEDDED)


# --- двоичные части OOXML с типом содержимого "openxml" не являются XML -------------------

FONT_CT = (
    '<Default Extension="odttf" '
    'ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont"/></Types>'
)
SIGS_CT = (
    '<Default Extension="sigs" '
    'ContentType="application/vnd.openxmlformats-package.digital-signature-origin"/></Types>'
)


def test_embedded_font_passes_and_renders():
    font = bytes(range(256)) * 40  # двоичные байты, не UTF-8, есть NUL
    data = make_docx(extra_parts={"word/fonts/font1.odttf": font})
    data = patch_part(data, "[Content_Types].xml", "</Types>", FONT_CT)
    engine.validate_upload(data, KIND)
    out = engine.render_docx(data, sample_context(KIND))
    assert sample_context(KIND)["order"]["number"] in docx_text(out)


def test_empty_signature_origin_passes():
    data = make_docx(extra_parts={"_xmlsignatures/origin.sigs": b""})
    data = patch_part(data, "[Content_Types].xml", "</Types>", SIGS_CT)
    engine.validate_upload(data, KIND)


def test_utf7_xml_part_still_rejected_next_to_font():
    data = make_docx(
        extra_parts={
            "word/fonts/font1.odttf": bytes(range(256)),
            "word/document.xml": _dtd_document("UTF-7"),
        }
    )
    data = patch_part(data, "[Content_Types].xml", "</Types>", FONT_CT)
    assert_invalid(data, ENCODING)


# --- песочница Jinja: дополнительные угрозы -----------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "{% include 'x.xml' %}",
        "{% import 'x.xml' as x %}",
        "{% from 'x.xml' import y %}",
        "{% extends 'x.xml' %}",
    ],
)
def test_include_import_extends_rejected(expr):
    message = assert_invalid(make_docx(expr), INCLUDE)
    assert_no_internals(message)
    assert_render_invalid(make_docx(expr), INCLUDE)


@pytest.mark.parametrize(
    "expr",
    [
        "{{ '{0.__class__}'.format(order.number) }}",
        "{{ '{x.__class__.__mro__}'.format_map({'x': 1}) }}",
        "{{ '{x.__init__.__globals__}'.format(x=cycler) }}",
    ],
)
def test_format_string_attack_blocked(expr):
    message = assert_invalid(make_docx(expr), FORBIDDEN)
    assert_no_internals(message)
    assert_render_invalid(make_docx(expr), FORBIDDEN)


def test_config_and_self_do_not_leak():
    # {{ config }} - неизвестная метка, а не настройки сервера
    assert_invalid(make_docx("{{ config }}"), "Неизвестная метка: config")
    data = engine.render_docx(make_docx("[{{ config }}][{{ config.SECRET_KEY }}]"), {})
    assert "[][]" in docx_text(data)


def test_nested_loop_blowup_bounded():
    started = time.monotonic()
    data = make_docx(
        "{% for i in range(100000) %}{% for j in range(100000) %}{% endfor %}{% endfor %}"
    )
    message = assert_invalid(data, COMPLEX)
    assert_no_internals(message)
    assert time.monotonic() - started < 10


def test_recursive_macro_blowup_bounded():
    started = time.monotonic()
    data = make_docx(
        "{% macro f(n) %}{% if n %}{{ f(n - 1) }}{{ f(n - 1) }}{% endif %}{% endmacro %}{{ f(60) }}"
    )
    assert_invalid(data, COMPLEX)
    assert time.monotonic() - started < 10


AMPLIFIERS = [
    ("{{ 'x' * 100000000 }}", COMPLEX),
    ("{{ ['x'] * 100000000 }}", COMPLEX),
    ("{{ 'x'.center(100000000) }}", COMPLEX),
    ("{{ 'x'.zfill(100000000) }}", COMPLEX),
    ("{{ 'x'|center(100000000) }}", COMPLEX),
    ("{{ 'x'|indent(100000000, true) }}", COMPLEX),
    ("{{ [1]|batch(100000000, 'x')|list }}", COMPLEX),
    ("{{ '{:>100000000}'.format(1) }}", COMPLEX),
    ("{{ '%100000000d' % 1 }}", COMPLEX),
    ("{{ '%100000000d'|format(1) }}", COMPLEX),
    ("{{ 10 ** 100000000 }}", COMPLEX),
    (
        "{% set ns = namespace(s='xxxxxxxxxx') %}{% for i in range(60) %}"
        "{% set ns.s = ns.s ~ ns.s %}{% endfor %}{{ ns.s|length }}",
        COMPLEX,
    ),
    (
        "{% set ns = namespace(s='xxxxxxxxxx') %}{% for i in range(60) %}"
        "{% set ns.s = ns.s + ns.s %}{% endfor %}{{ ns.s|length }}",
        COMPLEX,
    ),
    (
        "{% set ns = namespace(n=2) %}{% for i in range(60) %}"
        "{% set ns.n = ns.n * ns.n %}{% endfor %}{{ ns.n > 0 }}",
        COMPLEX,
    ),
    ("{% for i in range(100000) %}{{ 'x' * 1000 }}{% endfor %}", COMPLEX),
    ("{{ ('x' * 99999).join(['a'] * 99999) }}", COMPLEX),
    ("{{ (['a'] * 99999)|join('x' * 99999) }}", COMPLEX),
    ("{{ ('a' * 99999).replace('', 'x' * 99999) }}", COMPLEX),
    ("{{ ('a' * 99999)|replace('a', 'x' * 99999) }}", COMPLEX),
    ("{{ ('\\t' * 99999).expandtabs(99999) }}", FORBIDDEN),
    ("{{ ('\\n' * 99999)|indent(99999, true) }}", COMPLEX),
    ("{{ ('x ' * 99999)|wordwrap(1, wrapstring='y' * 99999) }}", COMPLEX),
    (
        "{% set ns = namespace(l=[1]) %}{% for i in range(40) %}"
        "{% set ns.l = [ns.l, ns.l] %}{% endfor %}{{ ns.l }}",
        "цикл",
    ),
]


@pytest.mark.parametrize(("expr", "reason"), AMPLIFIERS)
def test_amplification_bounded(expr, reason):
    started = time.monotonic()
    message = assert_invalid(make_docx(expr), reason)
    assert_no_internals(message)
    assert time.monotonic() - started < 10


@pytest.mark.parametrize(("expr", "reason"), AMPLIFIERS)
def test_amplification_bounded_without_isolation(expr, reason, monkeypatch, settings):
    # бюджеты внутри процесса сами по себе ловят эти нагрузки (без дочернего процесса)
    monkeypatch.setattr(engine, "resource", None)
    settings.DOCUMENTS_ALLOW_UNISOLATED_RENDER = True
    assert_invalid(make_docx(expr), reason)


# Нагрузки, которые бюджеты не ловят (одна тяжёлая операция): их ограничивают ресурсы
# дочернего процесса (процессорное время, память) и принудительное завершение.
ONE_CALL_AMPLIFIERS = [
    "{{ ([[1]] * 1000000)|sum(start=[])|length }}",
    (
        "{% set ns = namespace(l=[1]) %}{% for i in range(40) %}"
        "{% set ns.l = [ns.l, ns.l] %}{% endfor %}{{ (ns.l ~ '')|length }}"
    ),
    "{{ ('{0}' * 500000).format('x' * 999999)|length }}",
    "{{ ('%s' * 300000)|format(*(['x' * 999999] * 300000))|length }}",
    "{{ '{:{w}}'.format(1, w='400000000')|length }}",
]


def test_one_call_amplifiers_bounded_by_process_limits():
    before = maxrss_mb()
    for expr in ONE_CALL_AMPLIFIERS:
        started = time.monotonic()
        message = assert_invalid(make_docx(expr), COMPLEX)
        assert_no_internals(message)
        assert time.monotonic() - started < engine.RENDER_KILL_SECONDS + 3, expr
    assert maxrss_mb() - before < 50  # память веб-процесса не раздулась


@pytest.mark.parametrize("filter_name", ["tojson", "pprint"])
def test_tojson_pprint_filters_removed(filter_name):
    data = make_docx("{{ order|" + filter_name + " }}")
    assert_invalid(data, f"No filter named '{filter_name}'")


def test_resource_caps_fit_the_deployment():
    assert engine.CHILD_CPU_SECONDS <= 5
    assert engine.RENDER_KILL_SECONDS <= 8
    assert engine.RENDER_MEMORY_BYTES <= 192 * 1024 * 1024
    assert engine.RENDER_TIMEOUT_SECONDS < engine.CHILD_CPU_SECONDS < engine.RENDER_KILL_SECONDS


def _full_template(kind):
    """Все метки вида: скаляры абзацами, списки - циклами по строкам таблицы."""
    paragraphs, loops = [], {}
    for p in placeholders(kind):
        name = p["name"]
        if "[]" in name:
            prefix, field = name.split("[].", 1)
            loops.setdefault(prefix, []).append(field)
        else:
            paragraphs.append("{{ " + name + " }}")
    rows = []
    for prefix, fields in loops.items():
        rows.append(["{%tr for it in " + prefix + " %}"])
        rows.append([" ".join("{{ it." + f + " }}" for f in fields)])
        rows.append(["{%tr endfor %}"])
    return make_docx(paragraphs, table_rows=rows or None)


def _scale_lists(value, rows):
    if isinstance(value, dict):
        return {k: _scale_lists(v, rows) for k, v in value.items()}
    if isinstance(value, list):
        return [_scale_lists(value[i % len(value)], rows) for i in range(rows)]
    return value


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_legitimate_templates_render_well_within_caps(kind):
    data = _full_template(kind)
    started = time.monotonic()
    engine.validate_upload(data, kind)
    ctx = _scale_lists(sample_context(kind), 100)
    out = engine.render_docx(data, ctx)
    assert time.monotonic() - started < engine.CHILD_CPU_SECONDS / 2
    text = docx_text(out)
    assert ctx["doc"]["number"] in text
    assert "{{" not in text


def test_rendered_xml_cannot_inject_doctype():
    # автор шаблона может вывести "сырой" XML через |safe - но не DTD/сущности
    expr = "{{ ('%c'|format(60) ~ '!DOCTYPE x [' ~ '%c'|format(60) ~ '!ENTITY a \"b\">]>')|safe }}"
    message = assert_invalid(make_docx(expr), "объявления XML")
    assert_no_internals(message)


def test_lipsum_global_removed():
    data = make_docx("{{ lipsum(100000) }}")
    assert_invalid(data, "Неизвестная метка: lipsum")
    assert_render_invalid(data, "Неизвестная метка: lipsum")


def test_render_prints_whole_list_rejected():
    assert_render_invalid(make_docx("{{ order.consignments }}"), "цикл")


def test_render_escapes_xml_special_chars():
    ctx = sample_context(KIND)
    ctx["order"]["comment"] = 'A & B <c> "d"'
    data = engine.render_docx(make_docx("{{ order.comment }}"), ctx)
    assert 'A & B <c> "d"' in docx_text(data)


def test_dict_keys_win_over_dict_methods():
    rows = [
        ["{%tr for it in invoice.items %}", ""],
        ["{{ it.title }}", "{{ it.amount_net }}"],
        ["{%tr endfor %}", ""],
    ]
    data = make_docx(table_rows=rows)
    engine.validate_upload(data, "invoice_print")
    ctx = sample_context("invoice_print")
    text = docx_text(engine.render_docx(data, ctx))
    for item in ctx["invoice"]["items"]:
        assert item["title"] in text


def test_render_rejects_structurally_bad_package():
    data = make_docx(extra_parts={"word/vbaProject.bin": b"macro"})
    assert_render_invalid(data, MACRO)


# --- изоляция рендера в дочернем процессе --------------------------------------------------


def test_isolation_timeout_kills_child(monkeypatch, caplog):
    monkeypatch.setattr(engine, "RENDER_KILL_SECONDS", 1)
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="apps.documents.engine"):
        with pytest.raises(DocumentError) as ei:
            engine._isolated(time.sleep, 30)
    assert ei.value.get_codes() == "template_invalid"
    assert COMPLEX in str(ei.value.detail)
    assert time.monotonic() - started < 4
    assert any("phase=timeout" in r.getMessage() for r in caplog.records)


def test_isolation_memory_limit():
    with pytest.raises(DocumentError) as ei:
        engine._isolated(bytearray, 1024 * 1024 * 1024)
    assert ei.value.get_codes() == "template_invalid"
    assert COMPLEX in str(ei.value.detail)


def test_isolation_passes_document_error_and_result():
    def boom():
        raise DocumentError("template_invalid", "Проверка")

    with pytest.raises(DocumentError) as ei:
        engine._isolated(boom)
    assert str(ei.value.detail) == "Проверка"
    assert engine._isolated(bytes, 3) == b"\0\0\0"


def test_unexpected_child_error_is_logged_without_content(caplog):
    def boom():
        raise KeyError("секретный текст шаблона")

    with caplog.at_level(logging.WARNING, logger="apps.documents.engine"):
        with pytest.raises(DocumentError) as ei:
            engine._isolated(boom)
    assert ei.value.get_codes() == "template_invalid"
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "KeyError" in logged and "phase=render" in logged
    assert "секретный" not in logged


def _open_fds():
    return len(os.listdir("/proc/self/fd"))


def assert_unavailable(callable_, *args):
    with pytest.raises(DocumentError) as ei:
        callable_(*args)
    assert ei.value.get_codes() == "render_unavailable"
    assert ei.value.status_code == 503
    assert "временно недоступен" in str(ei.value.detail)


def test_fork_failure_is_unavailable_and_closes_pipe(monkeypatch, caplog):
    def no_fork():
        raise OSError(11, "Resource temporarily unavailable")

    monkeypatch.setattr(engine.os, "fork", no_fork)
    before = _open_fds()
    with caplog.at_level(logging.ERROR, logger="apps.documents.engine"):
        assert_unavailable(engine.validate_upload, make_docx(), KIND)
    assert _open_fds() == before
    assert any("phase=fork" in r.getMessage() for r in caplog.records)


def test_no_memory_baseline_fails_closed(monkeypatch, caplog):
    monkeypatch.setattr(engine, "_address_space_used", lambda: None)
    with caplog.at_level(logging.ERROR, logger="apps.documents.engine"):
        assert_unavailable(engine.render_docx, make_docx(), sample_context(KIND))
    assert any("phase=limits" in r.getMessage() for r in caplog.records)


def test_setrlimit_failure_fails_closed(monkeypatch, caplog):
    def broken(*args):
        raise ValueError("not allowed")

    monkeypatch.setattr(engine.resource, "setrlimit", broken)
    with caplog.at_level(logging.ERROR, logger="apps.documents.engine"):
        assert_unavailable(engine.validate_upload, make_docx(), KIND)
    assert any("phase=limits" in r.getMessage() for r in caplog.records)


def test_no_resource_module_fails_closed_by_default(monkeypatch, settings):
    monkeypatch.setattr(engine, "resource", None)
    settings.DOCUMENTS_ALLOW_UNISOLATED_RENDER = False
    assert_unavailable(engine.validate_upload, make_docx(), KIND)


def test_no_resource_module_renders_in_process_when_allowed(monkeypatch, settings):
    monkeypatch.setattr(engine, "resource", None)
    settings.DOCUMENTS_ALLOW_UNISOLATED_RENDER = True
    engine.validate_upload(make_docx(), KIND)
    out = engine.render_docx(make_docx(), sample_context(KIND))
    assert sample_context(KIND)["order"]["number"] in docx_text(out)
