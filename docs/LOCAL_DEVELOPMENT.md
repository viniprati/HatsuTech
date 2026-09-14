# Local Development

This guide explains how to inspect and validate HatsuTech locally without
committing secrets or changing production configuration.

## Requirements

- Python compatible with the project dependencies
- Git
- Access to private runtime values only when you are authorized to run the bot

Install dependencies in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Environment Variables

Runtime configuration is loaded from `.env` in the repository directory and
from `~/.env` as a fallback.

Never commit `.env`, `.env.*`, Discord tokens, MongoDB URIs, API keys or
hosting credentials.

Typical private values include:

- Discord bot token
- MongoDB URI
- Clash Royale API token
- guild, role or channel IDs used by the production community

Use independent credentials for test environments when possible.

## Validation Commands

The repository currently has compile and dependency validation, but no dedicated
test suite or linter.

Run:

```bash
python -m compileall -q main.py config.py database.py utils.py cogs scripts
python -m pip check
```

For documentation and workflow-only changes, also validate:

```bash
git diff --check
ruby -e 'require "yaml"; files = Dir[".github/**/*.yml"] + Dir[".github/**/*.yaml"]; files.sort.each { |file| YAML.load_file(file); puts "valid #{file}" }'
```

## Running The Bot

Only run the bot locally when you have explicit authorization and correct
environment values.

Before running:

- confirm you are not using production credentials by accident;
- confirm the bot should connect to the intended Discord application;
- confirm MongoDB network access is allowed;
- avoid running a second instance against the same production bot token unless
  maintenance requires it.

Start with:

```bash
python main.py
```

## Working With Pull Requests

Use branches for non-trivial changes:

```bash
git switch main
git pull --ff-only origin main
git switch -c <type>/<description>
```

Before opening a PR:

- keep the diff focused;
- run the relevant validation commands;
- mention any manual Discord, MongoDB, GitHub or hosting setting needed after
  merge;
- do not claim a check passed unless it was executed.

