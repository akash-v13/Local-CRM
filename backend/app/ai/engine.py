"""Rendering layered Jinja prompt templates (see app/ai/templates/README.md).

A draft's prompt is assembled from:

    system  = platform layout + guardrails      (files, locked, cached)
            + baseline  (base.jinja)            ┐
            + persona   (queue/<Queue>.jinja)   ├ the business's templates
            + case type (category/<...>.jinja)  ┘
    user    = case facts + conversation         (file, locked)

Business templates are stored per tenant (versioned in the database) and
rendered one at a time in a **sandbox** with **strict** variables:
- the sandbox blocks access to Python internals (no server-side template injection);
- templates can't include/extend/import anything (layers are combined here, so
  a business can never drop or reorder the platform rules);
- an undefined variable raises instead of rendering as empty text, so a
  template that relies on data a case doesn't have fails visibly.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import FileSystemLoader, StrictUndefined, TemplateSyntaxError, meta
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.sandbox import ImmutableSandboxedEnvironment

TEMPLATE_DIR = Path(__file__).parent / "templates"
DEFAULTS_DIR = TEMPLATE_DIR / "defaults"

BASE = "base.jinja"
PERSONA_DEFAULT = "queue/_default.jinja"
CATEGORY_DEFAULT = "category/_default.jinja"

# Top-level names a business template may use.
VARIABLES = {"business", "case", "customer", "enrichment", "decisions", "thread", "latest_message"}

_NAME = re.compile(r"^(base\.jinja|queue/[A-Za-z0-9_]+\.jinja|category/[A-Za-z0-9_]+\.jinja)$")


def _env(loader: FileSystemLoader | None = None) -> ImmutableSandboxedEnvironment:
    return ImmutableSandboxedEnvironment(
        loader=loader,
        undefined=StrictUndefined,
        autoescape=False,  # plain-text prompts, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
    )


_tenant_env = _env()
_platform_env = _env(FileSystemLoader(str(TEMPLATE_DIR)))


# ----- names ------------------------------------------------------------------------------


def slug(text: str) -> str:
    """'Late delivery' → 'LateDelivery', 'High-value VIP' → 'HighValueVIP'."""
    words = re.findall(r"[A-Za-z0-9]+", text)
    return "".join(w[:1].upper() + w[1:] for w in words)


def persona_names(queue_name: str | None) -> list[str]:
    """Persona templates to try for a queue, most specific first."""
    names = [f"queue/{slug(queue_name)}.jinja"] if queue_name and slug(queue_name) else []
    return [*names, PERSONA_DEFAULT]


def category_names(category: Mapping[str, Any] | None) -> list[str]:
    """Case-type templates to try, most specific first:
    Type_Category_Subcategory → Type_Category → Type → _default."""
    parts = [slug(str((category or {}).get(k) or "")) for k in ("type", "category", "subcategory")]
    names: list[str] = []
    for depth in (3, 2, 1):
        segment = parts[:depth]
        if all(segment):
            names.append(f"category/{'_'.join(segment)}.jinja")
    return [*names, CATEGORY_DEFAULT]


def kind_of(name: str) -> str:
    if name == BASE:
        return "base"
    return "persona" if name.startswith("queue/") else "category"


def is_valid_name(name: str) -> bool:
    return bool(_NAME.match(name))


# ----- header (checks travel inside the file) ------------------------------------------------

_HEADER = re.compile(r"\A\s*\{#---\s*\n(?P<body>.*?)\n---#\}\s*\n?", re.S)


@dataclass
class Checks:
    max_words: int | None = None
    must_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)


@dataclass
class TemplateFile:
    """A template as a file: optional header (description + checks) and the Jinja body."""

    source: str
    description: str | None = None
    checks: Checks = field(default_factory=Checks)


def parse_file(text: str) -> TemplateFile:
    match = _HEADER.match(text)
    if not match:
        return TemplateFile(source=text.strip() + "\n")
    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip().lower()] = value.strip()

    def as_list(key: str) -> list[str]:
        return [v.strip() for v in values.get(key, "").split(",") if v.strip()]

    max_words = values.get("max_words")
    return TemplateFile(
        source=text[match.end() :].strip() + "\n",
        description=values.get("description") or None,
        checks=Checks(
            max_words=int(max_words) if max_words and max_words.isdigit() else None,
            must_include=as_list("must_include"),
            must_not_include=as_list("must_not_include"),
        ),
    )


def to_file(template: TemplateFile) -> str:
    lines = []
    if template.description:
        lines.append(f"description: {template.description}")
    if template.checks.max_words:
        lines.append(f"max_words: {template.checks.max_words}")
    if template.checks.must_include:
        lines.append(f"must_include: {', '.join(template.checks.must_include)}")
    if template.checks.must_not_include:
        lines.append(f"must_not_include: {', '.join(template.checks.must_not_include)}")
    header = "{#---\n" + "\n".join(lines) + "\n---#}\n" if lines else ""
    return header + template.source


def default_files() -> dict[str, TemplateFile]:
    """The starter pack: name → parsed file."""
    files: dict[str, TemplateFile] = {}
    for path in sorted(DEFAULTS_DIR.rglob("*.jinja")):
        name = path.relative_to(DEFAULTS_DIR).as_posix()
        files[name] = parse_file(path.read_text())
    return files


def platform_source(name: str) -> str:
    return (TEMPLATE_DIR / "_platform" / name).read_text()


# ----- validation & rendering ---------------------------------------------------------------


class TemplateError(Exception):
    """A template couldn't be rendered; the message names the template and the problem."""

    def __init__(self, template: str, message: str) -> None:
        super().__init__(f"{template}: {message}")
        self.template = template


def validate(source: str) -> list[str]:
    """Problems that block saving a business template (empty list = OK)."""
    try:
        ast = _tenant_env.parse(source)
    except TemplateSyntaxError as exc:
        return [f"Syntax error on line {exc.lineno}: {exc.message}"]
    problems: list[str] = []
    if list(meta.find_referenced_templates(ast)):
        problems.append(
            "include / extends / import aren't allowed: the baseline, persona and case-type "
            "layers are combined automatically."
        )
    unknown = sorted(meta.find_undeclared_variables(ast) - VARIABLES)
    if unknown:
        problems.append(
            f"Unknown variable(s): {', '.join(unknown)}. Available: {', '.join(sorted(VARIABLES))}."
        )
    return problems


def render(name: str, source: str, context: Mapping[str, Any]) -> str:
    """Render one business template in the sandbox."""
    try:
        return _tenant_env.from_string(source).render(context).strip()
    except UndefinedError as exc:
        raise TemplateError(
            name,
            f"{exc.message}. This case doesn't have that value: guard optional data with "
            "{% if ... is defined %}.",
        ) from exc
    except SecurityError as exc:
        raise TemplateError(name, f"not allowed: {exc}") from exc
    except TemplateSyntaxError as exc:
        raise TemplateError(name, f"syntax error on line {exc.lineno}: {exc.message}") from exc
    except Exception as exc:  # noqa: BLE001 - any template bug must surface as a readable error
        raise TemplateError(name, f"{type(exc).__name__}: {exc}") from exc


@dataclass(frozen=True)
class StoredTemplate:
    name: str
    version: int | None  # None = unsaved edit being tested/previewed
    source: str
    checks: Checks


@dataclass
class LayerUsed:
    layer: str  # baseline | persona | category
    name: str
    version: int | None
    text: str


@dataclass
class BuiltPrompt:
    system_platform: str  # stable: cached
    system_layers: str  # business layers for this case
    user: str
    layers: list[LayerUsed]
    checks: Checks


def resolve(templates: Mapping[str, StoredTemplate], names: list[str]) -> StoredTemplate:
    for name in names:
        if name in templates:
            return templates[name]
    raise TemplateError(
        names[-1], "missing; restore the starter templates in the Operations Portal"
    )


def merge_checks(parts: list[Checks]) -> Checks:
    """Checks from all layers apply together (the strictest word limit wins)."""
    limits = [c.max_words for c in parts if c.max_words]
    include: list[str] = []
    exclude: list[str] = []
    for c in parts:
        include += [p for p in c.must_include if p not in include]
        exclude += [p for p in c.must_not_include if p not in exclude]
    return Checks(
        max_words=min(limits) if limits else None, must_include=include, must_not_include=exclude
    )


def build_prompt(
    templates: Mapping[str, StoredTemplate],
    context: Mapping[str, Any],
    pinned: str | None = None,
) -> BuiltPrompt:
    """Assemble the full prompt for one case. `context` must already be masked.

    `pinned` forces that template into its layer whatever the case's queue or
    category (the preview and test lab use it to try a template on any input).
    """
    case = context["case"]
    chains = {
        "baseline": [BASE],
        "persona": persona_names(case.get("queue")),
        "category": category_names(case),
    }
    if pinned:
        layer = {"base": "baseline", "persona": "persona", "category": "category"}[kind_of(pinned)]
        chains[layer] = [pinned]
    chosen = [(layer, resolve(templates, names)) for layer, names in chains.items()]
    layers = [
        LayerUsed(layer, t.name, t.version, render(t.name, t.source, context))
        for layer, t in chosen
    ]
    by_layer = {layer.layer: layer.text for layer in layers}

    system_platform = _platform_env.get_template("_platform/system.jinja").render(context).strip()
    system_layers = (
        _platform_env.get_template("_platform/layers.jinja")
        .render(
            baseline=by_layer["baseline"],
            persona=by_layer["persona"],
            category_instructions=by_layer["category"],
        )
        .strip()
    )
    user = _platform_env.get_template("_platform/case.jinja").render(context).strip()
    return BuiltPrompt(
        system_platform=system_platform,
        system_layers=system_layers,
        user=user,
        layers=layers,
        checks=merge_checks([t.checks for _, t in chosen]),
    )
