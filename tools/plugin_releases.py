"""Publish a GitHub release for every plugin whose version has none yet.

`.github/workflows/plugin-releases.yml` runs this after a push that changes a
plugin's manifest. A release is tagged `<folder>-v<version>`, such as
`bookmarks-v1.1.0`, and its text lists every commit that changed the plugin's folder
since the plugin's previous release, with subject and description. Preview it with
`python tools/plugin_releases.py --dry-run`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_FOLDER = "plugins"
MANIFEST = "plugin.toml"
TEMPLATE_PREFIX = "_"  # Such folders are never offered as plugins.
TAG_FORMAT = "{folder}-v{version}"
COMMAND_TIMEOUT_SECONDS = 120
FIELD_END, RECORD_END = "\x1f", "\x1e"  # Never in a commit message.
BODY_INDENT = "  "  # Nests a commit's own list under its subject.


@dataclass(frozen=True, slots=True)
class PluginRelease:
    folder: str
    name: str
    version: str
    previous_tag: str | None

    @property
    def tag(self) -> str:
        return TAG_FORMAT.format(folder=self.folder, version=self.version)

    @property
    def title(self) -> str:
        return f"{self.name} {self.version}"


@dataclass(frozen=True, slots=True)
class Commit:
    subject: str
    body: str


def due_releases(root: Path = ROOT) -> list[PluginRelease]:
    """Plugins whose current version has no release tag yet."""
    due = []
    for folder in sorted((root / PLUGINS_FOLDER).iterdir()):
        manifest = folder / MANIFEST
        if folder.name.startswith(TEMPLATE_PREFIX) or not manifest.is_file():
            continue
        declared = tomllib.loads(manifest.read_text(encoding="utf-8"))
        version = str(declared.get("version", "")).strip()
        if not version:
            continue  # Without a version WinLauncher never offers an update either.
        release = PluginRelease(
            folder.name,
            str(declared.get("name") or folder.name),
            version,
            _latest_tag(folder.name, root),
        )
        if not _tag_exists(release.tag, root):
            due.append(release)
    return due


def commits_of(release: PluginRelease, root: Path = ROOT) -> list[Commit]:
    """The commits that changed the plugin's folder since its previous release, oldest first."""
    revisions = f"{release.previous_tag}..HEAD" if release.previous_tag else "HEAD"
    log = _git(
        root,
        "log",
        "--reverse",
        "--no-merges",
        f"--format=%s{FIELD_END}%b{RECORD_END}",
        revisions,
        "--",
        f"{PLUGINS_FOLDER}/{release.folder}",
    )
    commits = []
    for record in log.split(RECORD_END):
        subject, _, body = record.strip("\n").partition(FIELD_END)
        if subject.strip():
            commits.append(Commit(subject.strip(), body.strip()))
    return commits


def release_notes(release: PluginRelease, commits: list[Commit]) -> str:
    """Markdown: each change of the release with its description, oldest first."""
    changes = "\n\n".join(_change(commit) for commit in commits) or "- No changes recorded."
    return f"## Changes\n\n{changes}\n"


def publish(release: PluginRelease, notes: str, root: Path = ROOT) -> None:
    """Tag the current commit and create the GitHub release with `notes`."""
    target = _git(root, "rev-parse", "HEAD").strip()
    subprocess.run(
        [
            "gh",
            "release",
            "create",
            release.tag,
            "--target",
            target,
            "--title",
            release.title,
            "--notes-file",
            "-",
        ],
        cwd=root,
        input=notes,
        text=True,
        encoding="utf-8",
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=True,
    )


def _change(commit: Commit) -> str:
    if not commit.body:
        return f"- **{commit.subject}**"
    body = "\n".join(BODY_INDENT + line if line else "" for line in commit.body.splitlines())
    return f"- **{commit.subject}**\n\n{body}"


def _latest_tag(folder: str, root: Path) -> str | None:
    """The plugin's newest release tag by version; the dash keeps `ai` from `ai_sessions`."""
    prefix = TAG_FORMAT.format(folder=folder, version="")
    tags = _git(root, "tag", "--list", f"{prefix}*", "--sort=-v:refname").split()
    return tags[0] if tags else None


def _tag_exists(tag: str, root: Path) -> bool:
    found = subprocess.run(
        ["git", "rev-parse", "--quiet", "--verify", f"refs/tags/{tag}"],
        cwd=root,
        capture_output=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    return found.returncode == 0


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=True,
    )
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print the notes, publish nothing")
    arguments = parser.parse_args(argv)
    due = due_releases()
    if not due:
        print("Every plugin version has its release.")
    for release in due:
        notes = release_notes(release, commits_of(release))
        if arguments.dry_run:
            sys.stdout.buffer.write(f"# {release.tag}: {release.title}\n\n{notes}\n".encode())
        else:
            publish(release, notes)
            print(f"Published {release.tag}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
