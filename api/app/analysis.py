"""Reading artefact text: size, file paths it mentions, and rules repeated across files.

"""

import re

# File extensions treated as "this looks like a file in the repo". Restricting to code
# and config extensions keeps things like "e.g." or "example.com" from being
# mistaken for paths.
# fmt: off
CODE_EXTENSIONS = frozenset(
    [
        "c", "cc", "cfg", "cjs", "conf", "cpp", "cs", "css", "csv", "dart", "env", "go",
        "gradle", "h", "hpp", "html", "ini", "ipynb", "java", "js", "json", "jsx", "kt", "kts",
        "lock", "lua", "md", "mdx", "mjs", "php", "pl", "proto", "py", "rb", "rs", "sass",
        "scss", "sh", "sql", "svelte", "swift", "toml", "ts", "tsx", "txt", "vue", "xml",
        "yaml", "yml", "zsh",
    ]
)
# fmt: on

# Folders usually excluded from git and from searches, so artefacts mentioning them are probably not referring to a real thing.
# fmt: off
IGNORED_FOLDERS = frozenset(
    [
        "node_modules", "dist", "build", "out", "target", "coverage", ".next", ".venv", "venv",
        "__pycache__", ".git", "site", "_site", "htmlcov", ".tox", ".pytest_cache",
        ".mypy_cache",
    ]
)
# fmt: on

_URL = re.compile(r"\w+://\S+")
# A path with at least one "/", e.g. src/app/main.py, ./scripts/build.sh or docs/.
# The look-behind stops matches inside URLs, emails, npm scopes and absolute paths.
_PATH = re.compile(r"(?<![\w@/.:~$-])((?:\./)?[\w.-]+(?:/[\w.-]+)+/?)")
# A single folder written with a trailing slash, e.g. docs/ or ./scripts/.
_FOLDER = re.compile(r"(?<![\w@/.:~$-])((?:\./)?[\w.-]+/)(?![\w.-])")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_FILENAME = re.compile(r"^[\w-][\w.-]*\.([A-Za-z0-9]+)$")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_NON_WORD = re.compile(r"[^\w\s]|_")

MIN_RULE_WORDS = 4
# Suggest where a missing file probably moved only if this few files share its name.
MOVED_HINT_LIMIT = 3


def line_count(text: str) -> int:
    return len(text.splitlines())


def approx_tokens(text: str) -> int:
    """Rough token count: about 4 characters per token for English text and code."""
    return round(len(text) / 4)


def _has_code_extension(name: str) -> bool:
    match = _FILENAME.match(name)
    return bool(match) and match.group(1).lower() in CODE_EXTENSIONS


def path_references(text: str) -> list[tuple[str, int]]:
    """File and folder paths an artefact mentions, with the line each first appears on.

    Two kinds are picked up:
    - paths containing a "/" whose last part has a code extension or that end in "/"
      ("src/api/client.ts", "docs/"), anywhere in the text;
    - bare file names with a code extension written as code ("`package.json`").

    URLs are removed first. Example: "Run `scripts/test.sh` and see docs/setup.md or
    https://x.dev/a.md" on line 1 gives [("scripts/test.sh", 1), ("docs/setup.md", 1)].
    """
    found: dict[str, int] = {}

    def add(candidate: str, line: int) -> None:
        candidate = candidate.removeprefix("./")
        parts = candidate.rstrip("/").split("/")
        # Skip build/dependency folders at any depth, "path/to/..." placeholders, and
        # "../" paths, which point outside the repo (e.g. to a sibling repository).
        outside = candidate.startswith("../")
        if IGNORED_FOLDERS.isdisjoint(parts) and "path/to" not in candidate and not outside:
            found.setdefault(candidate, line)

    for number, raw in enumerate(text.splitlines(), start=1):
        line = _URL.sub(" ", raw)
        for match in _PATH.finditer(line):
            candidate = match.group(1).rstrip(".,;:")
            last_part = candidate.rstrip("/").rsplit("/", 1)[-1]
            if candidate.endswith("/") or _has_code_extension(last_part):
                add(candidate, number)
        for match in _FOLDER.finditer(line):
            # "next.js/" is usually a project name, not a folder.
            if not _has_code_extension(match.group(1).rstrip("/").removeprefix("./")):
                add(match.group(1), number)
        for match in _CODE_SPAN.finditer(line):
            span = match.group(1).strip()
            if _has_code_extension(span):
                add(span, number)

    return list(found.items())


def broken_references(
    refs: list[tuple[str, int]], files: set[str], folders: set[str], artefact_folder: str = ""
) -> list[dict]:
    """The references that don't exist in the repo, each with the reason.

    A path with "/" inside must exist (as a file or folder) from the repo root, from
    the artefact's own folder, or under some subfolder (monorepo packages often
    describe paths relative to themselves). A bare name ("package.json", or
    "run_internal/" for a folder) counts as found if a file or folder with that name
    exists anywhere, since it's often written without its parent folders.

    Each result is {"path", "line", "reason", "found_at"}. ``found_at`` lists where a
    file or folder with the same name does exist, which usually means it was moved.
    Example: "src/utils/api.ts" on line 12, when only "src/lib/api.ts" exists, gives
    {"path": "src/utils/api.ts", "line": 12, "found_at": ["src/lib/api.ts"],
     "reason": "Nothing at this path. A file with this name exists elsewhere."}
    """
    broken = []
    for ref, line in refs:
        is_folder = ref.endswith("/")
        path = ref.rstrip("/")
        name = path.rsplit("/", 1)[-1]
        kind = "folder" if is_folder else "file"
        candidates = folders if is_folder else files
        same_name = sorted(c for c in candidates if c.rsplit("/", 1)[-1] == name)

        if "/" not in path:
            if same_name:
                continue
            reason = f"No {kind} named {name} anywhere in the repo."
        else:
            options = [path, f"{artefact_folder}/{path}"] if artefact_folder else [path]
            if any(p in files or p in folders for p in options):
                continue
            # In monorepos, paths are often written relative to a package
            # ("src/cli/dev.ts" for packages/app/src/cli/dev.ts). this fixes such things.
            if any(c.endswith("/" + path) for c in candidates):
                continue
            if not same_name:
                reason = f"Nothing at this path, and no {kind} named {name} anywhere in the repo."
            elif len(same_name) <= MOVED_HINT_LIMIT:
                reason = f"Nothing at this path. A {kind} with this name exists elsewhere."
            else:
                # A common name (README.md, index.ts): a guess at where it went would be noise.
                reason = "Nothing at this path."
                same_name = []
        broken.append({"path": ref, "line": line, "reason": reason, "found_at": same_name})
    return broken


def normalise_rule(line: str) -> str:
    """Comparison form of a rule line: no list marker, lowercase, no punctuation."""
    return " ".join(_NON_WORD.sub(" ", _LIST_MARKER.sub("", line.strip()).lower()).split())


def _rules(text: str) -> dict[str, str]:
    """Rule lines keyed by their normalised form (lowercase, no punctuation or list
    marker)."""
    rules: dict[str, str] = {}
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code or not stripped or stripped.startswith("#"):
            continue
        normalised = normalise_rule(stripped)
        if len(normalised.split()) >= MIN_RULE_WORDS:
            rules.setdefault(normalised, stripped)
    return rules


def duplicated_rules(texts: dict[str, str]) -> dict[str, list[dict]]:
    """For each artefact, the rule lines that also appear in another artefact.

    Matching ignores case, punctuation and list markers, so "- Use pnpm, not npm."
    and "* use pnpm not npm" count as the same rule.
    Returns {path: [{"text": original line, "other_path": where else it appears}]}.
    """
    rules = {path: _rules(text) for path, text in texts.items()}
    result: dict[str, list[dict]] = {}
    for path, own in rules.items():
        result[path] = []
        for normalised, original in own.items():
            others = [p for p in rules if p != path and normalised in rules[p]]
            if others:
                result[path].append({"text": original, "other_path": others[0]})
    return result
