from app.analysis import (
    approx_tokens,
    broken_references,
    duplicated_rules,
    line_count,
    path_references,
)


def test_size():
    assert line_count("a\nb\nc\n") == 3
    assert approx_tokens("x" * 400) == 100


def test_finds_paths_and_code_file_names():
    text = """
Run `scripts/test.sh` before pushing; config is in ./config/app.yaml.
Docs live in docs/ and `package.json` holds the scripts.
See https://example.com/guide/setup.md and email dev@team.io/notes.md.
Use and/or CI/CD as you like, e.g. version 1.2.3.
"""
    assert path_references(text) == [
        ("scripts/test.sh", 2),
        ("config/app.yaml", 2),
        ("docs/", 3),
        ("package.json", 3),
    ]


def test_project_names_are_not_folders():
    assert path_references("Welcome to next.js/ and see docs/") == [("docs/", 1)]


def test_paths_relative_to_a_package_are_found():
    files = {"packages/next/src/cli/next-dev.ts"}
    folders = {"packages", "packages/next", "packages/next/src", "packages/next/src/cli"}
    assert broken_references([("src/cli/next-dev.ts", 1)], files, folders) == []


def test_ignores_paths_outside_the_repo():
    assert path_references("Shared code lives in ../langchain-google/ and ../core/a.py") == []


def test_ignores_build_folders_and_placeholders():
    text = "Never edit node_modules/a/index.js, dist/app.js or packages/web/dist/ (path/to/x.ts)"
    assert path_references(text) == []


def test_common_names_get_no_moved_hint():
    files = {f"pkg{i}/README.md" for i in range(5)}
    folders = {f"pkg{i}" for i in range(5)}
    [result] = broken_references([("docs/README.md", 3)], files, folders)
    assert result == {
        "path": "docs/README.md",
        "line": 3,
        "reason": "Nothing at this path.",
        "found_at": [],
    }


def test_broken_references_with_reasons():
    files = {"src/app.py", "src/lib/api.ts", "web/package.json"}
    folders = {"src", "src/lib", "web"}
    refs = [
        ("src/app.py", 1),
        ("src/utils/api.ts", 2),
        ("src/old.py", 3),
        ("src/", 4),
        ("lib/", 5),
        ("package.json", 6),
        ("setup.py", 7),
    ]
    assert broken_references(refs, files, folders) == [
        {
            "path": "src/utils/api.ts",
            "line": 2,
            "reason": "Nothing at this path. A file with this name exists elsewhere.",
            "found_at": ["src/lib/api.ts"],
        },
        {
            "path": "src/old.py",
            "line": 3,
            "reason": "Nothing at this path, and no file named old.py anywhere in the repo.",
            "found_at": [],
        },
        {
            "path": "setup.py",
            "line": 7,
            "reason": "No file named setup.py anywhere in the repo.",
            "found_at": [],
        },
    ]


def test_references_can_be_relative_to_the_artefact_folder():
    files = {".github/workflows/ci.yml"}
    folders = {".github", ".github/workflows"}
    ref = [("workflows/ci.yml", 1)]
    assert broken_references(ref, files, folders, ".github") == []
    assert broken_references(ref, files, folders) == []
    assert [r["path"] for r in broken_references([("jobs/ci.yml", 1)], files, folders)] == [
        "jobs/ci.yml"
    ]


def test_duplicated_rules_ignore_case_punctuation_and_markers():
    texts = {
        "CLAUDE.md": "# Rules\n- Use pnpm, not npm, for installs.\n- Keep functions short, pure.\n",
        "AGENTS.md": "* use PNPM not npm for installs\n```\n- Keep functions short, pure.\n```\n",
    }
    result = duplicated_rules(texts)
    assert result["CLAUDE.md"] == [
        {"text": "- Use pnpm, not npm, for installs.", "other_path": "AGENTS.md"}
    ]
    assert result["AGENTS.md"] == [
        {"text": "* use PNPM not npm for installs", "other_path": "CLAUDE.md"}
    ]


def test_short_lines_and_headings_are_not_rules():
    texts = {
        "a.md": "# Use pnpm for installs\nBe nice.\n",
        "b.md": "# Use pnpm for installs\nBe nice.\n",
    }
    assert duplicated_rules(texts) == {"a.md": [], "b.md": []}
