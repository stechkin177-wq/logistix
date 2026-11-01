"""Движок шаблонов документов: проверка загружаемого .docx и безопасный рендер.

Шаблоны загружают пользователи компаний, а сервер исполняет содержащийся в них
Jinja-код. Поэтому защита многослойная:

1. Пакет (zip/OOXML) проверяется по каталогу zip ДО распаковки: размер файла,
   число частей, размер каждой части и сумма распакованных размеров
   (`ZipInfo.file_size`; zipfile не отдаёт больше заявленного размера и сверяет CRC),
   имена частей (без `..`, абсолютных путей, `\\`), без шифрования, только
   stored/deflate. Запрещены макросы (`*.bin`, `vbaProject`, ActiveX, macroEnabled
   типы содержимого), внешние связи (`TargetMode="External"`), DTD и сущности в
   XML (`<!DOCTYPE`/`<!ENTITY`: XXE, «billion laughs»), XML не в UTF-8.
2. Jinja исполняется только в `ImmutableSandboxedEnvironment` без загрузчика:
   `include`/`import`/`extends` запрещены ещё при разборе; обращение к
   небезопасному атрибуту сразу даёт ошибку (а не пустую строку); у словарей
   `.имя` - только ключи (не методы dict); `lipsum` убран.
3. Бюджеты внутри рендера: шагов (итерации циклов + вызовы) - `MAX_RENDER_STEPS`,
   выведенных символов - `MAX_OUTPUT_CHARS`, длина любой строки/списка -
   `MAX_VALUE_LEN`, разрядность целых - `MAX_INT_BITS`; предпроверки там, где одна
   операция умножает объём (`*`, `**`, `+`, `%`-формат, ширины в `str.format`,
   `join`/`replace`/`indent`/`wordwrap`, целые аргументы методов строк/списков и
   фильтров до `MAX_INT_ARG`), и срок `RENDER_TIMEOUT_SECONDS`.
4. Предохранитель: весь разбор и рендер идут в дочернем процессе (fork) с лимитами
   процессорного времени и памяти; по истечении срока процесс убивается. Это
   закрывает то, что не ловят бюджеты (одна тяжёлая C-операция и т.п.).

Ошибки шаблона превращаются в `DocumentError("template_invalid", <русское сообщение>)`
без путей сервера и внутренностей Python.
"""

import functools
import io
import json
import os
import re
import select
import signal
import time
import warnings
import zipfile
from collections.abc import Mapping

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

# --- лимиты пакета -----------------------------------------------------------------------
MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
MAX_UNPACKED_BYTES = 20 * 1024 * 1024
MAX_MEMBER_BYTES = 10 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000

# --- лимиты рендера ----------------------------------------------------------------------
MAX_RENDER_STEPS = 200_000  # итерации всех циклов + вызовы (макросы, методы)
MAX_OUTPUT_CHARS = 20_000_000  # все выведенные символы (с запасом на вложенные блоки)
MAX_VALUE_LEN = 1_000_000  # длина любой строки/списка, получаемой в шаблоне
MAX_INT_BITS = 10_000  # разрядность целых при `*` и `**`
MAX_INT_ARG = 100_000  # целые аргументы методов строк/списков и фильтров (ширины, счётчики)
MAX_FORMAT_WIDTH = 10_000  # ширина/точность в `%`-формате и `str.format`
RENDER_TIMEOUT_SECONDS = 15  # срок рендера (бюджет внутри и убийство процесса снаружи)
RENDER_MEMORY_BYTES = 512 * 1024 * 1024  # сверх уже занятого процессом адресного пространства
MAX_RESULT_BYTES = 64 * 1024 * 1024  # готовый .docx из дочернего процесса
RENDER_IN_SUBPROCESS = True

_INVALID = "template_invalid"
_MSG_NOT_DOCX = "Файл не является документом Word (.docx)."
_MSG_TOO_COMPLEX = "Шаблон слишком сложный: превышены лимиты времени, памяти или объёма документа."
_MSG_FORBIDDEN = "Шаблон использует запрещённую операцию."
_MSG_GENERIC = "Не удалось обработать шаблон: проверьте метки и команды."

_ALLOWED_COMPRESSION = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
_REQUIRED_PARTS = ("[content_types].xml", "word/document.xml")
_FORBIDDEN_CONTENT_TYPES = ("macroenabled", "vbaproject", "vbadata", "activex")
_DTD_RE = re.compile(rb"<!\s*(doctype|entity)", re.IGNORECASE)
_DTD_TEXT_RE = re.compile(r"<!\s*(doctype|entity)", re.IGNORECASE)
_UTF16_32_HEADS = (b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff", b"<\x00", b"\x00<")
_XML_SUFFIXES = (".xml", ".rels", ".vml", ".svg", ".xsd")
_SAFE_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    huge_tree=False,
    remove_comments=True,
    remove_pis=True,
)


def _invalid(detail: str) -> DocumentError:
    return DocumentError(_INVALID, detail)


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


def _is_macro_part(key: str) -> bool:
    base = key.rsplit("/", 1)[-1]
    return (
        base.endswith(".bin")
        or base in ("vbaproject.bin", "vbadata.xml")
        or "activex/" in key
        or key.startswith("activex")
    )


def _parse_xml(content: bytes):
    try:
        return etree.fromstring(content, parser=_SAFE_XML_PARSER)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise _invalid("Файл повреждён: часть документа не является корректным XML.") from exc


def _check_member_content(key: str, content: bytes) -> None:
    if content.startswith(_UTF16_32_HEADS) or (key.endswith(_XML_SUFFIXES) and b"\x00" in content):
        raise _invalid("Части документа должны быть в кодировке UTF-8.")
    if _DTD_RE.search(content):
        raise _invalid("Документ содержит запрещённые объявления DTD/сущностей XML.")
    if key.endswith(".rels"):
        for el in _parse_xml(content).iter():
            if (el.get("TargetMode") or "").strip().lower() == "external":
                raise _invalid("Шаблон содержит внешние ссылки (связанные файлы, шаблоны).")
    elif key == "[content_types].xml":
        for el in _parse_xml(content).iter():
            ctype = (el.get("ContentType") or "").lower()
            if any(bad in ctype for bad in _FORBIDDEN_CONTENT_TYPES):
                raise _invalid("Шаблон содержит макросы: загрузите файл .docx без макросов.")


def _check_package(data: bytes) -> None:
    """Проверить zip/OOXML-пакет. Размеры - по каталогу zip до распаковки."""
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
        seen: set[str] = set()
        total = 0
        for info in infos:
            _check_member_name(info.filename)
            key = info.filename.lower()
            if key in seen:
                raise _invalid("Файл .docx содержит повторяющиеся части.")
            seen.add(key)
            if info.flag_bits & 0x1:
                raise _invalid("Файл .docx зашифрован: снимите пароль и загрузите снова.")
            if info.compress_type not in _ALLOWED_COMPRESSION:
                raise _invalid("Файл .docx сжат неподдерживаемым методом.")
            total += info.file_size
            if info.file_size > MAX_MEMBER_BYTES or total > MAX_UNPACKED_BYTES:
                raise _invalid("Файл .docx слишком велик в распакованном виде (больше 20 МБ).")
            if _is_macro_part(key):
                raise _invalid("Шаблон содержит макросы: загрузите файл .docx без макросов.")
        if any(part not in seen for part in _REQUIRED_PARTS):
            raise _invalid("Файл повреждён: нет обязательных частей документа Word.")
        for info in infos:
            if info.is_dir():
                continue
            try:
                content = zf.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, EOFError) as exc:
                raise _invalid("Файл .docx повреждён.") from exc
            except Exception as exc:  # zlib.error и прочие ошибки распаковки
                raise _invalid("Файл .docx повреждён.") from exc
            _check_member_content(info.filename.lower(), content)


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


def _limit_child_resources() -> None:
    try:
        import resource
    except ImportError:  # pragma: no cover - не POSIX
        return
    cpu = int(RENDER_TIMEOUT_SECONDS) + 2
    _soft, hard = resource.getrlimit(resource.RLIMIT_CPU)
    if hard == resource.RLIM_INFINITY or hard > cpu:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, hard))
    try:
        with open("/proc/self/statm") as fh:
            used = int(fh.read().split()[0]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return
    limit = used + RENDER_MEMORY_BYTES
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))


def _child_payload(func, args) -> bytes:
    try:
        return b"O" + bytes(func(*args) or b"")
    except DocumentError as exc:
        info = {"code": exc.get_codes(), "detail": str(exc.detail)}
    except MemoryError:
        info = {"code": _INVALID, "detail": _MSG_TOO_COMPLEX}
    except BaseException:
        info = {"code": _INVALID, "detail": _MSG_GENERIC}
    return b"E" + json.dumps(info, ensure_ascii=False).encode()


def _isolated(func, *args):
    """Выполнить `func(*args)` в дочернем процессе с лимитами времени и памяти.

    Результат - bytes (или b"" для None); `DocumentError` передаётся родителю.
    Если процесс не уложился в срок или умер - `template_invalid`.
    """
    if not RENDER_IN_SUBPROCESS or not hasattr(os, "fork"):
        return func(*args)
    read_fd, write_fd = os.pipe()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # fork в многопоточном процессе
        pid = os.fork()
    if pid == 0:  # pragma: no cover - дочерний процесс
        status = 1
        try:
            os.close(read_fd)
            _limit_child_resources()
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
    deadline = time.monotonic() + RENDER_TIMEOUT_SECONDS + 2
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
    if not finished or os.waitstatus_to_exitcode(status) != 0 or not payload:
        raise _invalid(_MSG_TOO_COMPLEX)
    if payload[:1] == b"O":
        return payload[1:]
    try:
        info = json.loads(payload[1:])
        code, detail = str(info["code"]), str(info["detail"])
    except (ValueError, KeyError, TypeError):
        code, detail = _INVALID, _MSG_GENERIC
    raise DocumentError(code, detail)


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
