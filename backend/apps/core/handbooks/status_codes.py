"""Сопоставление существующих значений статусов рейса с системными кодами.

Чистая логика без обращения к БД: принимает строки значений справочника компании и решает,
какому значению можно безопасно назначить системный код, а что оставить для ручной проверки.
Используется миграцией данных и командами check_system_status_codes / assign_system_status_code.

Автоматически сопоставляется ТОЛЬКО однозначное: пустой код; ровно одно значение с точным
названием (регистр и пробелы строго); признаки is_initial/is_final как у стандартного
значения; код ещё не занят. Всё прочее (переименовано, дубликаты, иные признаки, код занят)
не сопоставляется и попадает в отчёт ручной проверки.
"""

from dataclasses import dataclass, field

TRIP_STATUS = "trip_status"


@dataclass(frozen=True)
class StatusSpec:
    name: str
    code: str
    is_initial: bool = False
    is_final: bool = False


# Стандартный набор статусов рейса (как в defaults.py)
TRIP_STATUS_SPECS: tuple[StatusSpec, ...] = (
    StatusSpec("Планируется", "PLANNED", is_initial=True),
    StatusSpec("Ожидает выезда", "ASSIGNED"),
    StatusSpec("В пути", "IN_PROGRESS"),
    StatusSpec("Выгрузка", "UNLOADING"),
    StatusSpec("Завершён", "COMPLETED", is_final=True),
    StatusSpec("Отменён", "CANCELLED", is_final=True),
)

# Справочники, у которых есть эталонные названия и признаки для автоматического сопоставления
SPECS_BY_HANDBOOK: dict[str, tuple[StatusSpec, ...]] = {TRIP_STATUS: TRIP_STATUS_SPECS}


@dataclass
class CodeReport:
    """Состояние одного системного кода в справочнике компании."""

    code: str
    spec: StatusSpec | None
    value_id: int | None = None  # значение, которое уже несёт код
    assign_to: int | None = None  # значение, которому код можно назначить автоматически
    reason: str = ""  # почему автоматически нельзя (для отчёта)
    candidates: list[dict] = field(default_factory=list)  # кандидаты для ручной проверки

    @property
    def assigned(self) -> bool:
        return self.value_id is not None


def _brief(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "code": row["code"],
        "is_initial": row["is_initial"],
        "is_final": row["is_final"],
    }


def _flags_match(row: dict, spec: StatusSpec) -> bool:
    return bool(row["is_initial"]) == spec.is_initial and bool(row["is_final"]) == spec.is_final


def analyze(handbook_code: str, codes, rows: list[dict]) -> list[CodeReport]:
    """Отчёт по каждому системному коду справочника.

    rows - значения справочника компании: dict(id, name, code, is_initial, is_final).
    codes - коды реестра (порядок отчёта - порядок эталонного набора, затем по алфавиту).
    """
    specs = {s.code: s for s in SPECS_BY_HANDBOOK.get(handbook_code, ())}
    ordered = [*specs, *sorted(set(codes) - set(specs))]
    by_code: dict[str, list[dict]] = {}
    for row in rows:
        by_code.setdefault(row["code"], []).append(row)
    reports = []
    for code in ordered:
        spec = specs.get(code)
        report = CodeReport(code=code, spec=spec)
        reports.append(report)
        holders = by_code.get(code, [])
        if holders:
            report.value_id = holders[0]["id"]
            continue
        if spec is None:
            report.reason = "нет значения с этим кодом, эталонного названия нет"
            continue
        report.candidates = _candidates(rows, spec)
        exact = [r for r in rows if r["name"] == spec.name]
        if len(exact) != 1:
            report.reason = (
                f"нет значения с точным названием «{spec.name}»"
                if not exact
                else f"несколько значений с названием «{spec.name}»: {len(exact)}"
            )
            continue
        row = exact[0]
        if row["code"]:
            report.reason = f"значение «{spec.name}» уже имеет другой код «{row['code']}»"
        elif not _flags_match(row, spec):
            report.reason = (
                f"признаки значения «{spec.name}» не соответствуют ожидаемым "
                f"(начальное={spec.is_initial}, конечное={spec.is_final})"
            )
        else:
            report.assign_to = row["id"]
    return reports


def _candidates(rows: list[dict], spec: StatusSpec) -> list[dict]:
    """Значения без кода, похожие на эталонное: по названию без учёта регистра/пробелов
    или по совпадению ключевых признаков. Только подсказка для ручной проверки."""
    wanted = spec.name.strip().lower()
    out = []
    for row in rows:
        if row["code"]:
            continue
        same_name = row["name"].strip().lower() == wanted
        same_flags = (spec.is_initial and row["is_initial"]) or (spec.is_final and row["is_final"])
        if same_name or same_flags:
            out.append(_brief(row))
    return out


def automatic_assignments(handbook_code: str, codes, rows: list[dict]) -> dict[int, str]:
    """{id значения: код} для однозначного автоматического сопоставления."""
    return {
        r.assign_to: r.code for r in analyze(handbook_code, codes, rows) if r.assign_to is not None
    }
