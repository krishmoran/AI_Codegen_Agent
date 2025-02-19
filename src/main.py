import asyncio
import argparse
from typing import List, Optional
import numpy as np
from .config import ConfigManager, ServiceConfig
from .codebase import CodebaseUnderstanding
from .code_generator import CodeGenerator
import os
from pathlib import Path
import sys

async def get_embeddings(texts: List[str]) -> List[List[float]]:
    """Default embeddings provider using OpenAI."""
    from openai import AsyncOpenAI
    
    config = ConfigManager().load_config()
    client = AsyncOpenAI(api_key=config.openai_api_key)
    
    # Process in batches to handle rate limits
    batch_size = 100
    all_embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = await client.embeddings.create(
            model=config.embeddings_model,
            input=batch
        )
        all_embeddings.extend([r.embedding for r in response.data])
    
    return all_embeddings

async def setup_services(config: Optional[ServiceConfig] = None) -> tuple[CodebaseUnderstanding, CodeGenerator]:
    """Set up all required services."""
    if config is None:
        config = ConfigManager().load_config()
    
    # Initialize codebase understanding
    codebase = CodebaseUnderstanding(
        github_token=config.github_token,
        github_owner=config.github_owner,
        github_repo=config.github_repo,
        embeddings_provider=get_embeddings,
        parser_dir=config.parser_dir,
        db_path=config.db_path
    )
    await codebase.initialize()
    
    # Initialize code generator
    generator = CodeGenerator(config, codebase)
    
    return codebase, generator

async def index_repository(args):
    """Index the repository command."""
    config = ConfigManager().load_config()
    print(f"\nUsing database path: {config.db_path}")  # Debug print
    codebase, _ = await setup_services(config)
    
    # Show repository info
    print(f"\nRepository: {config.github_owner}/{config.github_repo}")
    print(f"Branch: {args.branch or 'default'}")
    
    # Show patterns
    include_patterns = args.include.split(',') if args.include else [
        '**/*.ts', '**/*.tsx',  # TypeScript
        '**/*.js', '**/*.jsx',  # JavaScript
        '**/*.py',              # Python
        '**/*.rb',              # Ruby
        '**/*.rs',              # Rust
        '**/*.go',              # Go
        '**/*.java',            # Java
    ]
    exclude_patterns = args.exclude.split(',') if args.exclude else [
        '**/node_modules/**',
        '**/dist/**',
        '**/.git/**',
    ]
    
    print("\nInclude patterns:", include_patterns)
    print("Exclude patterns:", exclude_patterns)
    
    # Clear existing index first
    print("\nClearing existing index...")
    await codebase.index.clear()
    print("Index cleared successfully")
    
    print("\nStarting indexing...")
    try:
        await codebase.index_repository(
            branch=args.branch,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            show_progress=True
        )
    except Exception as e:
        print(f"\n❌ Error during indexing: {e}")
        raise

async def search_code(args):
    """Search code command."""
    config = ConfigManager().load_config()
    print(f"\nUsing database path: {config.db_path}")  # Debug print
    codebase, _ = await setup_services(config)
    
    print(f"Searching for: {args.query}")
    results = await codebase.search_similar_code(
        query=args.query,
        n_results=args.limit,
        filter_directory=args.directory
    )
    
    for item in results:
        print(f"\nFile: {item.name}")
        print("-" * 80)
        print(item.content)
        print("-" * 80)

async def create_pr(args):
    """Create PR command."""
    config = ConfigManager().load_config()
    _, generator = await setup_services(config)
    
    print("Generating implementation from description...")
    pr_number = await generator.create_pr_from_description(
        description=args.description,
        context_query=args.context_query,
        base_branch=args.base_branch
    )
    
    if pr_number:
        print(f"Created PR #{pr_number}")
    else:
        print("Failed to create PR")

async def verify_setup() -> List[str]:
    """Verify all components are properly set up."""
    issues = []
    
    # Check configuration
    try:
        config = ConfigManager().load_config()
    except Exception as e:
        issues.append(f"Configuration error: {e}")
        return issues

    # Check query files
    query_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "tree_sitter_queries")
    if not os.path.exists(query_dir):
        issues.append(f"Query directory not found: {query_dir}")
    else:
        query_files = list(Path(query_dir).glob("tree-sitter-*-tags.scm"))
        if not query_files:
            issues.append(f"No tree-sitter query files found in {query_dir}")

    # Check language libraries
    lib_dir = os.path.join(os.path.dirname(__file__), "tree_sitter_libs")
    if not os.path.exists(lib_dir):
        issues.append(f"Language libraries not found. Run setup_languages.py first.")
    else:
        lib_files = list(Path(lib_dir).glob("*.so"))
        if not lib_files:
            issues.append(f"No language libraries found. Run setup_languages.py first.")

    return issues

def main():
    parser = argparse.ArgumentParser(description="Codebase understanding and generation tool")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify setup")
    
    # Index command
    index_parser = subparsers.add_parser("index", help="Index repository")
    index_parser.add_argument("--branch", help="Branch to index")
    index_parser.add_argument("--include", help="Comma-separated list of glob patterns to include")
    index_parser.add_argument("--exclude", help="Comma-separated list of glob patterns to exclude")
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search code")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=10, help="Number of results")
    search_parser.add_argument("--directory", help="Filter by directory")
    search_parser.add_argument("--language", help="Filter by language")
    
    # Create PR command
    pr_parser = subparsers.add_parser("pr", help="Create pull request")
    pr_parser.add_argument("description", help="PR description")
    pr_parser.add_argument("--context-query", help="Query to find relevant code context")
    pr_parser.add_argument("--base-branch", help="Base branch for PR")
    
    args = parser.parse_args()
    
    if args.command == "verify":
        issues = asyncio.run(verify_setup())
        if issues:
            print("\n❌ Setup issues found:")
            for issue in issues:
                print(f"  - {issue}")
            sys.exit(1)
        print("\n✅ Setup verified!")
    elif args.command == "index":
        asyncio.run(index_repository(args))
    elif args.command == "search":
        asyncio.run(search_code(args))
    elif args.command == "pr":
        asyncio.run(create_pr(args))
    else:
        parser.print_help()

if __name__ == "__main__":
    main() 