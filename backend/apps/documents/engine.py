"""Движок шаблонов документов: проверка загружаемого .docx и безопасный рендер.

Шаблоны загружают пользователи компаний, а сервер исполняет содержащийся в них
Jinja-код. Поэтому защита многослойная:

1. Пакет (zip/OOXML) проверяется в веб-процессе БЕЗ `zipfile.read`: сначала каталог
   zip (размер файла, число частей, заявленный размер каждой части и их сумма, имена
   без `..`/абсолютных путей/`\\`, без шифрования, только stored/deflate), затем
   каждая часть распаковывается собственным потоковым inflate с пределом
   «заявленный размер + 1»: лживый заголовок (zip-бомба) обрывается на первых
   килобайтах, а итог сверяется с заявленным размером и CRC. Запрещены макросы
   (`*.bin`, `vbaProject`, ActiveX, macroEnabled типы), встроенные пакеты и
   OLE-объекты (`word/embeddings/`, связи package/oleObject/control/aFChunk,
   вложенный zip/OLE по сигнатуре), внешние связи (`TargetMode="External"`).
   XML-части - только UTF-8 (объявленная кодировка тоже), без DTD и сущностей
   (поиск `<!DOCTYPE`/`<!ENTITY` и разбор защищённым парсером с проверкой docinfo).
2. Jinja исполняется только в `ImmutableSandboxedEnvironment` без загрузчика:
   `include`/`import`/`extends` запрещены ещё при разборе; обращение к
   небезопасному атрибуту сразу даёт ошибку (а не пустую строку); у словарей
   `.имя` - только ключи (не методы dict); `lipsum`, `tojson`, `pprint` убраны.
3. Бюджеты внутри рендера (дают понятные сообщения для типичных случаев): шагов
   (итерации циклов + вызовы) - `MAX_RENDER_STEPS`, выведенных символов -
   `MAX_OUTPUT_CHARS`, длина строки/списка - `MAX_VALUE_LEN`, разрядность целых -
   `MAX_INT_BITS`; предпроверки операций-умножителей и срок `RENDER_TIMEOUT_SECONDS`.
4. Граница по РЕСУРСАМ (главная гарантия от DoS): разбор и рендер идут в дочернем
   процессе (fork) с `RLIMIT_CPU` = `CHILD_CPU_SECONDS` и `RLIMIT_AS` = занятое +
   `RENDER_MEMORY_BYTES`; родитель убивает его через `RENDER_KILL_SECONDS`. Если
   лимиты установить нельзя (нет fork/resource, не читается /proc/self/statm,
   setrlimit отказал) - отказ `render_unavailable` (503), а не рендер без защиты;
   рендер в процессе разрешает только настройка
   `DOCUMENTS_ALLOW_UNISOLATED_RENDER = True` (по умолчанию False).

Ошибки шаблона превращаются в `DocumentError("template_invalid", <русское сообщение>)`
без путей сервера и внутренностей Python.
"""

import functools
import io
import json
import logging
import os
import re
import select
import signal
import struct
import time
import warnings
import zipfile
import zlib
from collections.abc import Mapping

try:
    import resource
except ImportError:  # pragma: no cover - не POSIX
    resource = None

from django.conf import settings
from docxtpl import DocxTemplate
from jinja2 import (
    ChainableUndefined,
    StrictUndefined,
    TemplateError,
    TemplateSyntaxError,
    UndefinedError,
    nodes,
)
from jinja2.exceptions import SecurityError
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.utils import missing
from jinja2.visitor import NodeTransformer
from lxml import etree

from .catalog import sample_context
from .errors import DocumentError

logger = logging.getLogger("apps.documents.engine")

# --- лимиты пакета -----------------------------------------------------------------------
MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
MAX_UNPACKED_BYTES = 20 * 1024 * 1024
MAX_MEMBER_BYTES = 10 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000

# --- лимиты рендера внутри песочницы ------------------------------------------------------
MAX_RENDER_STEPS = 200_000  # итерации всех циклов + вызовы (макросы, методы)
MAX_OUTPUT_CHARS = 20_000_000  # все выведенные символы (с запасом на вложенные блоки)
MAX_VALUE_LEN = 1_000_000  # длина любой строки/списка, получаемой в шаблоне
MAX_INT_BITS = 10_000  # разрядность целых при `*` и `**`
MAX_INT_ARG = 100_000  # целые аргументы методов строк/списков и фильтров (ширины, счётчики)
MAX_FORMAT_WIDTH = 10_000  # ширина/точность в `%`-формате и `str.format`
RENDER_TIMEOUT_SECONDS = 4  # срок внутри песочницы (проверяется на каждом шаге)

# --- ресурсы дочернего процесса рендера ----------------------------------------------------
# Рассчитаны на контейнер backend 768 МБ с 3 воркерами: даже 3 одновременных вредных
# загрузки не выводят cgroup за предел памяти, а воркер занят не дольше ~8 с.
# Ограничение частоты загрузок/рендеров на компанию - задача слоя API.
CHILD_CPU_SECONDS = 5  # RLIMIT_CPU дочернего процесса (SIGXCPU по истечении)
RENDER_KILL_SECONDS = 8  # родитель убивает дочерний процесс (SIGKILL) по стенным часам
RENDER_MEMORY_BYTES = 192 * 1024 * 1024  # RLIMIT_AS: сверх уже занятого адресного пространства
MAX_RESULT_BYTES = 64 * 1024 * 1024  # готовый .docx из дочернего процесса

_INVALID = "template_invalid"
_MSG_NOT_DOCX = "Файл не является документом Word (.docx)."
_MSG_CORRUPT = "Файл .docx повреждён."
_MSG_TOO_COMPLEX = "Шаблон слишком сложный: превышены лимиты времени, памяти или объёма документа."
_MSG_FORBIDDEN = "Шаблон использует запрещённую операцию."
_MSG_GENERIC = "Не удалось обработать шаблон: проверьте метки и команды."
_MSG_MACROS = "Шаблон содержит макросы: загрузите файл .docx без макросов."
_MSG_EMBEDDED = (
    "Шаблон содержит встроенные объекты (вложенные документы, OLE, элементы ActiveX): "
    "удалите их и загрузите снова."
)
_MSG_DTD = "Документ содержит запрещённые объявления DTD/сущностей XML."
_MSG_ENCODING = "Части документа должны быть в кодировке UTF-8."
_MSG_UNAVAILABLE = "Сервис обработки шаблонов временно недоступен"

_ALLOWED_COMPRESSION = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
_REQUIRED_PARTS = ("[content_types].xml", "word/document.xml")
_FORBIDDEN_CONTENT_TYPES = ("macroenabled", "vbaproject", "vbadata", "activex")
_EMBEDDING_REL_SUFFIXES = ("/package", "/oleobject", "/control", "/afchunk")
_EMBEDDED_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"\xd0\xcf\x11\xe0")
_DTD_RE = re.compile(rb"<!\s*(doctype|entity)", re.IGNORECASE)
_DTD_TEXT_RE = re.compile(r"<!\s*(doctype|entity)", re.IGNORECASE)
_XML_DECL_RE = re.compile(rb"^<\?xml\b[^>]*?\bencoding\s*=\s*[\"']([^\"']*)[\"']")
_UTF8_NAMES = frozenset({"utf-8", "utf8", "us-ascii", "ascii"})
_XML_SUFFIXES = (".xml", ".rels", ".vml", ".svg", ".xsd")
_INFLATE_CHUNK = 64 * 1024
_SAFE_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    dtd_validation=False,
    huge_tree=False,
)


def _invalid(detail: str) -> DocumentError:
    return DocumentError(_INVALID, detail)


def _unavailable() -> DocumentError:
    return DocumentError("render_unavailable", _MSG_UNAVAILABLE, status_code=503)


# =========================================================================================
# 1. Проверка пакета
# =========================================================================================


def _check_member_name(name: str) -> None:
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name)
        or ".." in name.split("/")
    ):
        raise _invalid("Недопустимое имя части в файле .docx.")


def _is_embedded_part(key: str) -> bool:
    return key.startswith("word/embeddings/") or "/embeddings/" in key or "activex" in key


def _is_macro_part(key: str) -> bool:
    base = key.rsplit("/", 1)[-1]
    return base.endswith(".bin") or base in ("vbaproject.bin", "vbadata.xml")


def _inflate_member(data: bytes, info: zipfile.ZipInfo) -> bytes:
    """Распаковать часть, не доверяя заголовку: вывод не больше заявленного + 1 байт.

    `zipfile.read` в CPython распаковывает весь поток deflate до обрезки по заявленному
    размеру (zip-бомба с лживым заголовком съедает память веб-процесса), поэтому здесь -
    свой потоковый inflate с `max_length`, сверка размера, конца потока и CRC.
    """
    off = info.header_offset
    head = data[off : off + 30]
    if len(head) < 30 or head[:4] != b"PK\x03\x04":
        raise _invalid(_MSG_CORRUPT)
    name_len, extra_len = struct.unpack("<HH", head[26:30])
    encoding = "utf-8" if info.flag_bits & 0x800 else "cp437"
    try:
        expected_name = info.orig_filename.encode(encoding)
    except UnicodeEncodeError as exc:
        raise _invalid(_MSG_CORRUPT) from exc
    if data[off + 30 : off + 30 + name_len] != expected_name:
        raise _invalid(_MSG_CORRUPT)
    start = off + 30 + name_len + extra_len
    raw = memoryview(data)[start : start + info.compress_size]
    if len(raw) != info.compress_size:
        raise _invalid(_MSG_CORRUPT)
    limit = info.file_size
    if info.compress_type == zipfile.ZIP_STORED:
        out = bytes(raw)
    else:
        inflater = zlib.decompressobj(-15)
        buf = bytearray()
        try:
            for pos in range(0, len(raw), _INFLATE_CHUNK):
                pending = bytes(raw[pos : pos + _INFLATE_CHUNK])
                while pending and not inflater.eof:
                    buf += inflater.decompress(pending, limit - len(buf) + 1)
                    if len(buf) > limit:
                        raise _invalid(
                            "Файл .docx повреждён: размер части не совпадает с заголовком."
                        )
                    pending = inflater.unconsumed_tail
                if inflater.eof:
                    break
        except zlib.error as exc:
            raise _invalid(_MSG_CORRUPT) from exc
        if not inflater.eof:
            raise _invalid(_MSG_CORRUPT)
        out = bytes(buf)
    if len(out) != limit or zlib.crc32(out) != info.CRC:
        raise _invalid(_MSG_CORRUPT)
    return out


def _parse_xml(content: bytes):
    try:
        root = etree.fromstring(content, parser=_SAFE_XML_PARSER)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise _invalid("Файл повреждён: часть документа не является корректным XML.") from exc
    docinfo = root.getroottree().docinfo
    if docinfo.doctype or docinfo.internalDTD is not None or docinfo.externalDTD is not None:
        raise _invalid(_MSG_DTD)
    if next(root.iter(etree.Entity), None) is not None:
        raise _invalid(_MSG_DTD)
    return root


def _content_types(content: bytes) -> tuple[dict, dict]:
    defaults, overrides = {}, {}
    for el in _parse_xml(content).iter():
        ctype = (el.get("ContentType") or "").lower()
        if any(bad in ctype for bad in _FORBIDDEN_CONTENT_TYPES):
            raise _invalid(_MSG_MACROS)
        if el.get("Extension") is not None:
            defaults[el.get("Extension").lower()] = ctype
        elif el.get("PartName") is not None:
            overrides[el.get("PartName").lstrip("/").lower()] = ctype
    return defaults, overrides


def _check_xml_encoding(content: bytes) -> None:
    body = content[3:] if content.startswith(b"\xef\xbb\xbf") else content
    if not body.lstrip(b" \t\r\n").startswith(b"<") or b"\x00" in body:
        raise _invalid(_MSG_ENCODING)
    decl = _XML_DECL_RE.match(body.lstrip(b" \t\r\n"))
    if decl and decl.group(1).decode("ascii", "replace").strip().lower() not in _UTF8_NAMES:
        raise _invalid(_MSG_ENCODING)
    try:
        body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _invalid(_MSG_ENCODING) from exc


def _check_member_content(key: str, content: bytes, ctype: str) -> None:
    if _DTD_RE.search(content):
        raise _invalid(_MSG_DTD)
    if content.startswith(_EMBEDDED_MAGIC):  # вложенный zip (docx/xlsx...) или OLE
        raise _invalid(_MSG_EMBEDDED)
    is_xml = key.endswith(_XML_SUFFIXES) or "xml" in ctype
    if not is_xml and content.startswith((b"\xff\xfe", b"\xfe\xff", b"<\x00", b"\x00<")):
        is_xml = True  # XML в UTF-16 под чужим расширением
    if not is_xml and content.lstrip()[:1] == b"<":
        is_xml = True
    if not is_xml:
        return
    _check_xml_encoding(content)
    root = _parse_xml(content)
    if key.endswith(".rels"):
        for el in root.iter():
            if (el.get("TargetMode") or "").strip().lower() == "external":
                raise _invalid("Шаблон содержит внешние ссылки (связанные файлы, шаблоны).")
            if (el.get("Type") or "").strip().lower().endswith(_EMBEDDING_REL_SUFFIXES):
                raise _invalid(_MSG_EMBEDDED)


def _check_package(data: bytes) -> None:
    """Проверить zip/OOXML-пакет; ни одна часть не распаковывается сверх заявленного."""
    if len(data) > MAX_TEMPLATE_BYTES:
        raise DocumentError("template_too_large", "Файл шаблона больше 2 МБ.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError, EOFError) as exc:
        raise _invalid(_MSG_NOT_DOCX) from exc
    with zf:
        infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise _invalid("В файле .docx слишком много частей.")
    seen: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        _check_member_name(info.filename)
        key = info.filename.lower()
        if key in seen:
            raise _invalid("Файл .docx содержит повторяющиеся части.")
        seen[key] = info
        if info.flag_bits & 0x1:
            raise _invalid("Файл .docx зашифрован: снимите пароль и загрузите снова.")
        if info.compress_type not in _ALLOWED_COMPRESSION:
            raise _invalid("Файл .docx сжат неподдерживаемым методом.")
        total += info.file_size
        if info.file_size > MAX_MEMBER_BYTES or total > MAX_UNPACKED_BYTES:
            raise _invalid("Файл .docx слишком велик в распакованном виде (больше 20 МБ).")
        if _is_embedded_part(key):
            raise _invalid(_MSG_EMBEDDED)
        if _is_macro_part(key):
            raise _invalid(_MSG_MACROS)
    if any(part not in seen for part in _REQUIRED_PARTS):
        raise _invalid("Файл повреждён: нет обязательных частей документа Word.")
    ct_content = _inflate_member(data, seen["[content_types].xml"])
    _check_member_content("[content_types].xml", ct_content, "xml")
    defaults, overrides = _content_types(ct_content)
    for key, info in seen.items():
        if info.is_dir() or key == "[content_types].xml":
            continue
        ext = key.rsplit(".", 1)[-1] if "." in key.rsplit("/", 1)[-1] else ""
        ctype = overrides.get(key) or defaults.get(ext, "")
        _check_member_content(key, _inflate_member(data, info), ctype)


# =========================================================================================
# 2-3. Песочница Jinja с бюджетами
# =========================================================================================


class _LimitError(SecurityError):
    """Превышен бюджет рендера; сообщение - для пользователя."""


def _label(undefined) -> str:
    name = undefined._undefined_name
    obj = undefined._undefined_obj
    path = getattr(obj, "_lx_path", None) if obj is not missing else None
    if name is None:
        return path or "?"
    return f"{path}.{name}" if path else str(name)


class _StrictUndefined(StrictUndefined):
    """Пробный рендер: любая неизвестная метка - ошибка с её полным именем."""

    __slots__ = ()

    @property
    def _undefined_message(self) -> str:
        return f"Неизвестная метка: {_label(self)}"


class _LenientUndefined(ChainableUndefined):
    """Рабочий рендер: отсутствующее значение (и цепочка от него) - пустая строка."""

    __slots__ = ()

    @property
    def _undefined_message(self) -> str:
        return f"Неизвестная метка: {_label(self)}"


class _Node(dict):
    """Словарь контекста, знающий свой путь (для сообщения о неизвестной метке)."""

    __slots__ = ("_lx_path",)


def _track(value, path: str):
    if isinstance(value, Mapping):
        node = _Node((k, _track(v, f"{path}.{k}" if path else str(k))) for k, v in value.items())
        node._lx_path = path
        return node
    if isinstance(value, (list, tuple)):
        return [_track(v, f"{path}[]") for v in value]
    return value


def _check_value(value):
    if isinstance(value, (str, bytes, list, tuple, dict, set, frozenset)):
        if len(value) > MAX_VALUE_LEN:
            raise _LimitError(_MSG_TOO_COMPLEX)
    elif isinstance(value, int) and not isinstance(value, bool):
        if value.bit_length() > MAX_INT_BITS:
            raise _LimitError(_MSG_TOO_COMPLEX)
    return value


def _check_int_args(args, kwargs) -> None:
    for arg in (*args, *kwargs.values()):
        if isinstance(arg, int) and not isinstance(arg, bool) and abs(arg) > MAX_INT_ARG:
            raise _LimitError(_MSG_TOO_COMPLEX)


_PERCENT_SPEC_RE = re.compile(r"%(?:\([^)]*\))?[#0\- +]*(\*|\d+)?(?:\.(\*|\d+))?")
_BRACE_FIELD_RE = re.compile(r"\{[^{}]*\}")


def _check_percent_format(fmt: str) -> None:
    for width, precision in _PERCENT_SPEC_RE.findall(fmt):
        for part in (width, precision):
            if part == "*" or (part and int(part) > MAX_FORMAT_WIDTH):
                raise _LimitError(_MSG_TOO_COMPLEX)


def _check_brace_format(fmt: str) -> None:
    for field in _BRACE_FIELD_RE.findall(fmt):
        for digits in re.findall(r"\d+", field):
            if len(digits) > 6 or int(digits) > MAX_FORMAT_WIDTH:
                raise _LimitError(_MSG_TOO_COMPLEX)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_binop(operator: str, left, right) -> None:
    sized = (str, bytes, list, tuple)
    if operator == "*":
        if _is_int(left) and _is_int(right):
            if left.bit_length() + right.bit_length() > MAX_INT_BITS:
                raise _LimitError(_MSG_TOO_COMPLEX)
        elif (
            isinstance(left, sized) and _is_int(right) or isinstance(right, sized) and _is_int(left)
        ):
            seq, times = (left, right) if isinstance(left, sized) else (right, left)
            if len(seq) * max(times, 0) > MAX_VALUE_LEN:
                raise _LimitError(_MSG_TOO_COMPLEX)
    elif operator == "**":
        if _is_int(left) and _is_int(right) and right > 0 and abs(left) > 1:
            if left.bit_length() * right > MAX_INT_BITS:
                raise _LimitError(_MSG_TOO_COMPLEX)
    elif operator == "+":
        if isinstance(left, sized) and isinstance(right, sized):
            if len(left) + len(right) > MAX_VALUE_LEN:
                raise _LimitError(_MSG_TOO_COMPLEX)
    elif operator == "%" and isinstance(left, str):
        _check_percent_format(left)


def _over(count: int, size: int) -> None:
    if count * size > MAX_VALUE_LEN:
        raise _LimitError(_MSG_TOO_COMPLEX)


def _sized_len(value) -> int:
    return len(value) if isinstance(value, (str, bytes, list, tuple)) else 0


# Методы строк, умножающие объём «длина x аргумент», которые шаблонам не нужны.
_DENIED_STR_METHODS = frozenset({"expandtabs", "translate", "maketrans"})


def _check_method(owner, name: str, args, kwargs) -> None:
    """Предпроверка метода строки/списка: целые аргументы и операции-умножители."""
    _check_int_args(args, kwargs)
    if not isinstance(owner, str):
        return
    if name in _DENIED_STR_METHODS:
        raise SecurityError("denied str method")
    if name in ("format", "format_map"):
        _check_brace_format(owner)
    elif name == "join" and args:
        _over(_sized_len(args[0]), len(owner))
    elif name == "replace" and len(args) >= 2 and isinstance(args[0], str):
        _over(owner.count(args[0]) + 1, _sized_len(args[1]))


def _check_filter(name: str, value, args, kwargs) -> None:
    """Предпроверка фильтра: целые аргументы (кроме значения) и операции-умножители."""
    _check_int_args(args, kwargs)
    if name == "format" and isinstance(value, str):
        _check_percent_format(value)
    elif name == "join":
        sep = args[0] if args else kwargs.get("d", "")
        _over(_sized_len(value), _sized_len(sep))
    elif name == "replace" and isinstance(value, str) and len(args) >= 2:
        if isinstance(args[0], str):
            _over(value.count(args[0]) + 1, _sized_len(args[1]))
    elif name == "indent" and isinstance(value, str):
        width = args[0] if args else kwargs.get("width", 4)
        _over(value.count("\n") + 1, width if _is_int(width) else _sized_len(width))
    elif name == "wordwrap" and isinstance(value, str):
        wrap = args[2] if len(args) > 2 else kwargs.get("wrapstring") or "\n"
        _over(len(value) + 1, _sized_len(wrap) + 1)


def _guard_filter(name: str, func):
    """Фильтр с предпроверкой аргументов и проверкой размера результата."""
    skip = 2 if _passes_arg(func) else 1  # context/eval_ctx/env, затем значение

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        value = args[skip - 1] if len(args) >= skip else None
        _check_filter(name, value, args[skip:], kwargs)
        return _check_value(func(*args, **kwargs))

    return wrapper


def _passes_arg(func) -> bool:
    return getattr(func, "jinja_pass_arg", None) is not None


def _finalize(value):
    """`{{ ... }}` выводит только скаляры: список/словарь целиком - ошибка автора шаблона
    (и защита от экспоненциального str() вложенных общих списков)."""
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        raise _LimitError("Метка выводит список целиком: используйте цикл {% for %}.")
    return value


class _Guard(NodeTransformer):
    """Вставить проверки в дерево шаблона: бюджет итераций и размер склеек `~`."""

    def __init__(self, env):
        self.env = env

    def _wrap(self, attr: str, expr):
        call = nodes.Call(nodes.EnvironmentAttribute(attr), [expr], [], None, None)
        call.set_lineno(expr.lineno or 1)
        call.set_environment(self.env)
        return call

    def visit_For(self, node):
        node = self.generic_visit(node)
        node.iter = self._wrap("lx_iter", node.iter)
        return node

    def visit_Concat(self, node):
        return self._wrap("lx_value", self.generic_visit(node))


class _SandboxEnv(ImmutableSandboxedEnvironment):
    intercepted_binops = frozenset({"*", "**", "+", "%"})

    def __init__(self, strict: bool):
        super().__init__(
            autoescape=True,
            undefined=_StrictUndefined if strict else _LenientUndefined,
            loader=None,
            finalize=_finalize,
        )
        self.globals.pop("lipsum", None)
        for name in ("tojson", "pprint"):  # шаблонам не нужны; тяжёлые на больших данных
            self.filters.pop(name, None)
        self.filters = {name: _guard_filter(name, f) for name, f in self.filters.items()}
        self.lx_steps = 0
        self.lx_output = 0
        self.lx_deadline = time.monotonic() + RENDER_TIMEOUT_SECONDS

    # --- разбор: запрет подключений и вставка проверок
    def _parse(self, source, name, filename):
        tree = super()._parse(source, name, filename)
        for node in tree.find_all((nodes.Extends, nodes.Include, nodes.Import, nodes.FromImport)):
            raise TemplateSyntaxError(
                "Подключение других шаблонов (include/import/extends) запрещено.",
                node.lineno,
                name,
                filename,
            )
        return _Guard(self).visit(tree)

    # --- бюджеты
    def lx_step(self) -> None:
        self.lx_steps += 1
        if self.lx_steps > MAX_RENDER_STEPS or time.monotonic() > self.lx_deadline:
            raise _LimitError(_MSG_TOO_COMPLEX)

    def lx_iter(self, iterable):
        for item in iterable:
            self.lx_step()
            yield item

    def lx_value(self, value):
        return _check_value(value)

    def concat(self, chunks):  # вывод шаблона, макросов и блоков идёт через него
        out = []
        for chunk in chunks:
            self.lx_output += len(chunk)
            if self.lx_output > MAX_OUTPUT_CHARS:
                raise _LimitError(_MSG_TOO_COMPLEX)
            out.append(chunk)
        return "".join(out)

    # --- доступ к атрибутам
    def getattr(self, obj, attribute):
        if isinstance(attribute, str) and attribute.startswith("_"):
            raise SecurityError("private attribute access")
        if isinstance(obj, Mapping):
            try:
                return obj[attribute]
            except (KeyError, TypeError):
                return self.undefined(obj=obj, name=attribute)
        return super().getattr(obj, attribute)

    def getitem(self, obj, argument):
        if isinstance(argument, str) and argument.startswith("_"):
            raise SecurityError("private attribute access")
        if isinstance(obj, Mapping) and isinstance(argument, str):
            try:
                return obj[argument]
            except (KeyError, TypeError):
                return self.undefined(obj=obj, name=argument)
        return super().getitem(obj, argument)

    def unsafe_undefined(self, obj, attribute):
        raise SecurityError("unsafe attribute access")

    # --- операции и вызовы
    def call_binop(self, context, operator, left, right):
        _check_binop(operator, left, right)
        return _check_value(super().call_binop(context, operator, left, right))

    def call(__self, __context, __obj, *args, **kwargs):  # noqa: N805
        __self.lx_step()
        target = getattr(__obj, "__wrapped__", __obj)
        owner = getattr(target, "__self__", None)
        if isinstance(owner, (str, bytes, list, tuple)):
            _check_method(owner, getattr(target, "__name__", ""), args, kwargs)
        return _check_value(super().call(__context, __obj, *args, **kwargs))


class _DocxTemplate(DocxTemplate):
    def render_xml_part(self, src_xml, part, context, jinja_env=None):
        dst_xml = super().render_xml_part(src_xml, part, context, jinja_env)
        if _DTD_TEXT_RE.search(dst_xml):
            raise _LimitError("Шаблон выводит запрещённые объявления XML.")
        return dst_xml


def _syntax_message(exc: TemplateSyntaxError) -> str:
    """Сообщение о синтаксической ошибке: номер строки и её текст.

    docxtpl ставит перевод строки перед каждым абзацем `<w:p>`, поэтому строка N
    исходника Jinja - это абзац N-1 документа (по порядку, включая ячейки таблиц).
    """
    lineno = exc.lineno or 1
    line = max(lineno - 1, 1)
    snippet = ""
    context = list(getattr(exc, "docx_context", None) or [])
    index = lineno - 1 - max(lineno - 4, 0)
    if 0 <= index < len(context):
        snippet = " ".join(context[index].split())[:80]
    where = f"строка {line}" + (f": «{snippet}»" if snippet else "")
    return f"Синтаксическая ошибка в шаблоне ({where}). {exc.message}"


def _render_in_process(data: bytes, context: dict, strict: bool) -> bytes:
    """Открыть, отрендерить и сохранить .docx; все ошибки - `DocumentError`."""
    try:
        env = _SandboxEnv(strict=strict)
        tpl = _DocxTemplate(io.BytesIO(data))
        tpl.render(_track(context, ""), jinja_env=env)
        out = io.BytesIO()
        tpl.save(out)
        return out.getvalue()
    except DocumentError:
        raise
    except TemplateSyntaxError as exc:
        raise _invalid(_syntax_message(exc))
    except UndefinedError as exc:
        message = str(exc)
        if not message.startswith("Неизвестная метка"):
            message = _MSG_GENERIC
        raise _invalid(message)
    except _LimitError as exc:
        raise _invalid(str(exc))
    except SecurityError:
        raise _invalid(_MSG_FORBIDDEN)
    except (OverflowError, MemoryError, RecursionError):
        raise _invalid(_MSG_TOO_COMPLEX)
    except TemplateError:
        raise _invalid(_MSG_GENERIC)
    except Exception:
        raise _invalid(_MSG_GENERIC)


# =========================================================================================
# 4. Изоляция в дочернем процессе
# =========================================================================================


class _IsolationError(Exception):
    """Не удалось установить лимиты дочернего процесса: рендерить нельзя."""


def _allow_unisolated() -> bool:
    return bool(getattr(settings, "DOCUMENTS_ALLOW_UNISOLATED_RENDER", False))


def _address_space_used() -> int | None:
    """Занятое процессом адресное пространство (байт) или None, если узнать нельзя."""
    try:
        with open("/proc/self/statm") as fh:
            return int(fh.read().split()[0]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def _limit_child_resources() -> None:
    """Лимиты CPU и памяти; если хоть один не установлен - `_IsolationError`."""
    if resource is None:
        raise _IsolationError("resource")
    used = _address_space_used()
    if used is None:
        raise _IsolationError("statm")
    # мягкий предел шлёт SIGXCPU (завершение), жёсткий на секунду позже - SIGKILL
    _soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
    if hard == resource.RLIM_INFINITY or hard > CHILD_CPU_SECONDS + 1:
        hard = CHILD_CPU_SECONDS + 1
    resource.setrlimit(resource.RLIMIT_CPU, (min(CHILD_CPU_SECONDS, hard), hard))
    limit = used + RENDER_MEMORY_BYTES
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))


def _child_payload(func, args) -> bytes:
    """Результат дочернего процесса: b"O"+байты, b"E"+json ошибки, b"U"+json отказа лимитов."""
    try:
        _limit_child_resources()
    except BaseException as exc:
        info = {"error": type(exc).__name__, "phase": "limits"}
        return b"U" + json.dumps(info).encode()
    try:
        return b"O" + bytes(func(*args) or b"")
    except DocumentError as exc:
        info = {"code": exc.get_codes(), "detail": str(exc.detail)}
    except MemoryError:
        info = {"code": _INVALID, "detail": _MSG_TOO_COMPLEX}
    except BaseException as exc:
        info = {
            "code": _INVALID,
            "detail": _MSG_GENERIC,
            "error": type(exc).__name__,
            "phase": "render",
        }
    return b"E" + json.dumps(info, ensure_ascii=False).encode()


def _isolated(func, *args):
    """Выполнить `func(*args)` в дочернем процессе с лимитами процессора и памяти.

    Результат - bytes (b"" для None); `DocumentError` передаётся родителю. Не уложился
    в срок или умер - `template_invalid`; лимиты/fork недоступны - `render_unavailable`.
    В журнал попадают только фаза и класс ошибки, но не текст шаблона.
    """
    if resource is None or not hasattr(os, "fork"):
        if _allow_unisolated():
            return func(*args)
        logger.error("template render isolation unavailable: phase=platform")
        raise _unavailable()
    try:
        read_fd, write_fd = os.pipe()
    except OSError as exc:
        logger.error("template render isolation failed: phase=pipe error=%s", type(exc).__name__)
        raise _unavailable() from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)  # fork в многопоточном процессе
            pid = os.fork()
    except OSError as exc:
        os.close(read_fd)
        os.close(write_fd)
        logger.error("template render isolation failed: phase=fork error=%s", type(exc).__name__)
        raise _unavailable() from exc
    if pid == 0:  # pragma: no cover - дочерний процесс
        status = 1
        try:
            os.close(read_fd)
            payload = _child_payload(func, args)
            with os.fdopen(write_fd, "wb") as fh:
                fh.write(payload)
            status = 0
        finally:
            os._exit(status)

    os.close(write_fd)
    chunks: list[bytes] = []
    size = 0
    finished = False
    deadline = time.monotonic() + RENDER_KILL_SECONDS
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([read_fd], [], [], remaining)
            if not ready:
                continue
            chunk = os.read(read_fd, 1 << 20)
            if not chunk:
                finished = True
                break
            size += len(chunk)
            if size > MAX_RESULT_BYTES:
                break
            chunks.append(chunk)
    finally:
        os.close(read_fd)
        if not finished:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        _, status = os.waitpid(pid, 0)
    payload = b"".join(chunks)
    exit_code = os.waitstatus_to_exitcode(status)
    if not finished or exit_code != 0 or not payload:
        phase = "timeout" if not finished else "exit"
        logger.warning("template render child stopped: phase=%s exit=%s", phase, exit_code)
        raise _invalid(_MSG_TOO_COMPLEX)
    kind, body = payload[:1], payload[1:]
    if kind == b"O":
        return body
    try:
        info = json.loads(body)
    except ValueError:
        info = {}
    if kind == b"U":
        logger.error(
            "template render isolation failed: phase=%s error=%s",
            info.get("phase", "limits"),
            info.get("error", "?"),
        )
        raise _unavailable()
    if info.get("error"):
        logger.warning(
            "template render failed in child: phase=%s error=%s",
            info.get("phase", "render"),
            info["error"],
        )
    raise DocumentError(str(info.get("code", _INVALID)), str(info.get("detail", _MSG_GENERIC)))


# =========================================================================================
# Публичный интерфейс
# =========================================================================================


def _trial_render(data: bytes, context: dict) -> None:
    _render_in_process(data, context, strict=True)


def validate_upload(data: bytes, kind: str) -> None:
    """Проверить загружаемый шаблон: пакет, затем пробный рендер тестового контекста.

    Неизвестная метка -> сообщение с её именем; синтаксическая ошибка -> со строкой.
    """
    _check_package(data)
    _isolated(_trial_render, data, sample_context(kind))


def render_docx(data: bytes, context: dict) -> bytes:
    """Отрендерить шаблон в песочнице. Отсутствующие значения дают пустую строку."""
    _check_package(data)
    return _isolated(_render_in_process, data, context, False)
