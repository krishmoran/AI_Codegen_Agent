# Codebase Understanding

A tool for understanding codebases and generating code changes using AI. Features include:
- Semantic code search
- Code generation from natural language descriptions
- Automated PR creation
- Impact analysis of changes

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment:

Create a config file at `~/.codebase_understanding/config.yml`:
```yaml
github_token: your-github-token
openai_api_key: your-openai-key
github_owner: repository-owner
github_repo: repository-name
db_path: ~/.codebase_understanding/index
completion_model: gpt-4o
```

Or set environment variables:
```bash
export GITHUB_TOKEN=your-github-token
export OPENAI_API_KEY=your-openai-key
export GITHUB_OWNER=repository-owner
export GITHUB_REPO=repository-name
export PARSER_DIR=/path/to/tree-sitter/parsers  # Optional
export DB_PATH=/path/to/vector/db  # Optional
```


## Usage

### Index Repository
```bash
python -m codebase_understanding.src.main index [--branch BRANCH] [--include "*.ts,*.py"] [--exclude "node_modules/**"]
```

### Search Code
```bash
python -m codebase_understanding.src.main search "query" [--limit 10] [--directory src/]
```

### Create PR from Description
```bash
python -m codebase_understanding.src.main pr "Add login functionality" --context-query "auth flow" --base-branch main
```

## Example

1. Index your repository:
```bash
python -m codebase_understanding.src.main index
```

2. Search for relevant code:
```bash
python -m codebase_understanding.src.main search "user authentication implementation"
```

3. Create a PR with new features:
```bash
python -m codebase_understanding.src.main pr "Add password reset functionality with email verification" --context-query "user authentication flow"
```

The tool will:
1. Search for relevant code context
2. Generate an implementation plan
3. Create necessary code changes
4. Analyze the impact
5. Create a PR with detailed description

## Configuration

### Models
- Default embeddings model: `text-embedding-ada-002`
- Default completion model: `gpt-4o`

You can change these in config.yml:
```yaml
embeddings_model: text-embedding-ada-002
completion_model: gpt-4o
```

### File Patterns
Default include patterns:
- `**/*.ts`
- `**/*.tsx`
- `**/*.js`
- `**/*.jsx`
- `**/*.py`
- `**/*.spec.ts`
- `**/*.swift`
- `**/*.kt`
- `**/*.java`
- `**/*.c`
- `**/*.h`
- `**/*.cpp`
- `**/*.hpp`

Default exclude patterns:
- `**/node_modules/**`
- `**/dist/**`
- `**/.git/**`

Override these using command line arguments or in your config file. 