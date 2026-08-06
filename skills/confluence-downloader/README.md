# Confluence Downloader Skill

This reusable agent skill tells Codex, Claude Code, or another compatible harness how to
use `confluence-downloader` to fetch missing or changed Confluence pages as local PDFs,
with optional close-to-original HTML copies and page attachments, before reviewing them.

## Install from a Fresh Machine

Clone the downloader repository first:

```bash
git clone git@gitlab.com:benmort/confluence-downloader.git
cd confluence-downloader
```

Install `uv` if it is not already available:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install the project dependencies:

```bash
uv sync --dev
```

On macOS, install WeasyPrint's native Pango dependency:

```bash
brew install pango
```

Check the CLI:

```bash
uv run confluence-downloader --help
```

Install the CLI as a user-level executable so Codex, Claude Code, and other agent harnesses
can call `confluence-downloader` from `PATH`:

```bash
uv tool install --force --editable .
```

Verify the installed executable:

```bash
command -v confluence-downloader
confluence-downloader --help
```

Because the install is editable, later edits to `src/` take effect immediately. Re-run
`uv tool install --force --editable .` only when `pyproject.toml` changes dependencies or
entry points.

## Install the Skill

Claude Code follows symlinks in its skills directory, so link the skill instead of copying
it. Updates to the repository then reach the agent with no reinstall step:

```bash
mkdir -p "$HOME/.claude/skills"
rm -rf "$HOME/.claude/skills/confluence-downloader"
ln -s "$PWD/skills/confluence-downloader" "$HOME/.claude/skills/confluence-downloader"
```

Codex is not verified to follow symlinked skill directories, so copy the skill there:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
rm -rf "${CODEX_HOME:-$HOME/.codex}/skills/confluence-downloader"
cp -R skills/confluence-downloader "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Restart Codex or Claude Code, or open a new session, so the agent reloads available skills.

Verify the files were installed:

```bash
sed -n '1,5p' "${CODEX_HOME:-$HOME/.codex}/skills/confluence-downloader/SKILL.md"
sed -n '1,5p' "$HOME/.claude/skills/confluence-downloader/SKILL.md"
```

Both should show:

```yaml
name: confluence-downloader
```

## Update the Skill

Edit `SKILL.md`, `references/`, and `scripts/` in this repository, never in an installed
copy. A copy edited in place silently drifts from the repository and is lost the next time
the skill is installed.

After committing a skill change, refresh the copied installs:

```bash
rm -rf "${CODEX_HOME:-$HOME/.codex}/skills/confluence-downloader"
cp -R skills/confluence-downloader "${CODEX_HOME:-$HOME/.codex}/skills/"
```

A symlinked Claude Code install needs no refresh. Confirm any copy is still in sync:

```bash
diff -r skills/confluence-downloader \
  "${CODEX_HOME:-$HOME/.codex}/skills/confluence-downloader"
```

## Configure Authentication

Set Confluence credentials in the shell or environment where the agent harness will run
the helper:

```bash
export CONFLUENCE_BASE_URL="https://confluence.example.com/confluence"
export CONFLUENCE_PAT="your-personal-access-token"
```

For Codex, Claude Code, or another agent harness running commands in a sandbox, the important part is
that these variables must exist inside the sandboxed command environment, not only in a
separate terminal tab. Prefer environment variables or a harness secret manager over
putting tokens in prompts, config files, or command-line flags.

Practical options:

- Start the agent from a shell where `CONFLUENCE_BASE_URL` and `CONFLUENCE_PAT` are already
  exported, if the harness inherits the parent environment.
- Configure the harness to pass `CONFLUENCE_BASE_URL` and `CONFLUENCE_PAT` as allowed
  environment variables or secrets.
- If the harness requires approval for network or cache access, approve only the downloader
  command shape you intend to run, and do not paste the PAT into the approval text.

Avoid this form unless there is no better option, because command-line tokens can appear in
shell history, process listings, or logs:

```bash
uv run confluence-downloader download --token "your-personal-access-token" ...
```

To check whether the sandbox can see the variables without revealing the token:

```bash
python -c 'import os; print("base_url", bool(os.getenv("CONFLUENCE_BASE_URL"))); print("pat", bool(os.getenv("CONFLUENCE_PAT")))'
```

If `pat False` is printed, fix the harness environment before asking the agent to download
Confluence pages.

## Use the Skill Helper

Run the helper from the repository root. It uses the current working directory as the
downloader repository by default:

```bash
python skills/confluence-downloader/scripts/ensure_confluence_pdfs.py \
  --config pages.json \
  --output-dir pdfs
```

For a named page:

```bash
python skills/confluence-downloader/scripts/ensure_confluence_pdfs.py \
  --space DOC \
  --title "Architecture Overview" \
  --include-children \
  --output-dir pdfs
```

For a page with its attached files and a standalone HTML copy:

```bash
python skills/confluence-downloader/scripts/ensure_confluence_pdfs.py \
  --space DOC \
  --title "Architecture Overview" \
  --download-html \
  --download-attachments \
  --output-dir pdfs
```

Attachments land under `pdfs/attachments/<page-slug>-<page-id>/`, alongside an
`_external-resources.md` listing files embedded on the page but hosted outside Confluence,
such as Google Docs or Slides. Those cannot be fetched with a Confluence token, so the
agent should surface their URLs rather than report them as missing.

If you only know an approximate title, search first and use the exact returned title in the
helper command:

```bash
uv run confluence-downloader search "architecture overview" --space DOC --limit 5
```

You can also ask the CLI to prompt for downloading the returned matches:

```bash
uv run confluence-downloader search "architecture overview" --space DOC -a --output-dir pdfs
```

Add `--yes` or `-y` to auto-confirm that prompted download.

Or create a bulk config from those matches:

```bash
uv run confluence-downloader search "architecture overview" --space DOC --bulk-config pages.json
```

If you combine `--ask-download`, `--bulk-config`, and `--output-dir`, accepting the
download prompt stores that output folder in `pages.json` for later `bulk --config`
runs.
If `--output-dir` is provided while writing a relative `--bulk-config`, the config file
is written inside that output directory.

From any other directory, pass the clone explicitly:

```bash
python "${CODEX_HOME:-$HOME/.codex}/skills/confluence-downloader/scripts/ensure_confluence_pdfs.py" \
  --repo /path/to/confluence-downloader \
  --config /path/to/confluence-downloader/pages.json \
  --output-dir /path/to/confluence-downloader/pdfs
```

Use `--dry-run` to preview the downloader command without contacting Confluence:

```bash
CONFLUENCE_BASE_URL=https://confluence.example.com/confluence \
CONFLUENCE_PAT=dummy \
python skills/confluence-downloader/scripts/ensure_confluence_pdfs.py \
  --config pages.json \
  --output-dir pdfs \
  --dry-run
```

## Agent Workflow

When the skill is active, ask the agent to review Confluence material and provide the page
space/title or a bulk config. The agent should use existing PDFs when possible, call the
downloader only for missing or changed pages, then review the PDFs plus
`downloaded_pages.md` or `downloaded_pages.html` from the output directory. Use
`--download-html` when local HTML copies are required, and `--download-attachments` when
the review depends on attached files.

## Example Agent Prompts

Ask the agent to use the skill by name and include enough Confluence context for the downloader:

```text
Use the confluence-downloader skill to download the DOC page "Architecture Overview"
with its children if needed, then review the resulting PDFs for outdated decisions.
```

For a repeatable bulk config:

```text
Use the confluence-downloader skill with pages.json. Pull any missing or changed
Confluence PDFs into ./pdfs, then summarize the key risks across the downloaded pages.
```

For a subtree discovery workflow:

```text
Use the confluence-downloader skill to list the DOC space below "Architecture" to
depth 2, create a bulk config from those pages, download the PDFs, and review them for
follow-up actions.
```

For an approximate title:

```text
Use the confluence-downloader skill to search the DOC space for pages matching
"architecture overview", download the best matching page with its children, and summarize
the resulting PDFs.
```

For a review that depends on attached files:

```text
Use the confluence-downloader skill to download the DOC page "Release Checklist" with its
attachments, then review the page and the attached spreadsheets for gaps. List any
externally hosted embeds you could not download.
```
