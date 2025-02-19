import os
from typing import List, Dict, Optional, Callable
from pathlib import Path
import asyncio
from github.Repository import Repository
from .types import Chunk, ContextItem, FileChange, Range
from .parser import CodeParser
from .indexing import CodebaseIndex
from .github_service import GitHubService
from tqdm import tqdm

class CodebaseUnderstanding:
    def __init__(
        self,
        github_token: str,
        github_owner: str,
        github_repo: str,
        embeddings_provider: Callable[[List[str]], List[List[float]]],
        parser_dir: str = None,
        db_path: str = None
    ):
        """
        Initialize the codebase understanding system.
        
        Args:
            github_token: GitHub personal access token
            github_owner: Repository owner
            github_repo: Repository name
            embeddings_provider: Function that generates embeddings for text
            parser_dir: Directory containing tree-sitter parsers
            db_path: Path to store the vector database
        """
        self.github = GitHubService(github_token)
        self.repo = self.github.get_repository(github_owner, github_repo)
        self.parser = CodeParser(parser_dir)
        self.index = CodebaseIndex(
            embeddings_provider=embeddings_provider,
            read_file=self.read_file,
            db_path=db_path
        )

    async def initialize(self) -> None:
        """Initialize the system."""
        await self.parser.initialize()

    async def read_file(self, filepath: str) -> str:
        """Read a file's contents from GitHub."""
        content = await self.github.get_file_content(self.repo, filepath)
        if content is None:
            raise FileNotFoundError(f"File not found: {filepath}")
        return content

    async def index_repository(
        self,
        branch: str = None,
        include_patterns: List[str] = None,
        exclude_patterns: List[str] = None,
        show_progress: bool = True
    ) -> None:
        """
        Index the entire repository.
        
        Args:
            branch: Branch to index (defaults to default branch)
            include_patterns: List of glob patterns to include
            exclude_patterns: List of glob patterns to exclude
            show_progress: Whether to show progress bars
        """
        if branch is None:
            branch = await self.github.get_default_branch(self.repo)

        # Set default patterns if none provided
        if include_patterns is None:
            include_patterns = [
                '**/*.ts', '**/*.tsx',  # TypeScript
                '**/*.js', '**/*.jsx',  # JavaScript
                '**/*.py',              # Python
                '**/*.rb',              # Ruby
                '**/*.rs',              # Rust
                '**/*.go',              # Go
                '**/*.java',            # Java
                '**/*.cs',              # C#
                '**/*.cpp', '**/*.hpp', # C++
                '**/*.c', '**/*.h',     # C
                '**/*.php',             # PHP
                '**/*.el',              # Elisp
                '**/*.ex', '**/*.exs',  # Elixir
                '**/*.elm',             # Elm
                '**/*.ml', '**/*.mli',  # OCaml
                '**/*.ql'               # QL
            ]
        
        if exclude_patterns is None:
            exclude_patterns = [
                '**/node_modules/**',
                '**/dist/**',
                '**/.git/**',
                '**/build/**',
                '**/target/**',
                '**/__pycache__/**',
                '**/*.min.js',
                '**/*.min.css'
            ]

        # Collect and process files
        chunks = []
        files_processed = 0
        total_files = 0
        
        # First, count total files for progress bar
        async for _ in self.github.list_files(
            self.repo,
            ref=branch,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns
        ):
            total_files += 1

        # Create progress bar for file processing
        with tqdm(
            total=total_files,
            desc="Processing files",
            disable=not show_progress
        ) as progress:
            async for file_path in self.github.list_files(
                self.repo,
                ref=branch,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns
            ):
                try:
                    content = await self.read_file(file_path)
                    if content:
                        # Use tree-sitter parser for semantic chunking
                        file_chunks = await self.parser.chunk_code(file_path, content)
                        if file_chunks:
                            # Add repo and branch info to chunks
                            for chunk in file_chunks:
                                chunk.repo = f"{self.repo.owner.login}/{self.repo.name}"
                                chunk.branch = branch
                            chunks.extend(file_chunks)
                            
                            # Update progress
                            files_processed += 1
                            progress.update(1)
                            progress.set_postfix({
                                "chunks": len(chunks),
                                "current": file_path
                            })
                except Exception as e:
                    if show_progress:
                        progress.write(f"Error processing {file_path}: {e}")
                    continue

        # Store chunks with progress tracking
        if chunks:
            await self.index.store(chunks, show_progress=show_progress)
        
        if show_progress:
            print(f"\nIndexing complete!")
            print(f"Files processed: {files_processed}/{total_files}")
            print(f"Total chunks: {len(chunks)}")

    async def search_similar_code(
        self,
        query: str,
        n_results: int = 10,
        filter_directory: str = None,
        language: str = None
    ) -> List[ContextItem]:
        """
        Search for code similar to the query.
        
        Args:
            query: Search query
            n_results: Number of results to return
            filter_directory: Optional directory to filter results
            language: Optional language to filter results
            
        Returns:
            List of relevant code snippets with context
        """
        chunks = await self.index.retrieve(
            query=query,
            n=n_results,
            tags=[{
                'directory': '',
                'branch': await self.github.get_default_branch(self.repo),
                'repo': f"{self.repo.owner.login}/{self.repo.name}"
            }],
            filter_directory=filter_directory,
            language=language
        )

        # Convert chunks to context items
        context_items = []
        for chunk in chunks:
            context_items.append(ContextItem(
                name=chunk.filepath,
                description=f"Code from {chunk.filepath} (lines {chunk.range.start['line']}-{chunk.range.end['line']})",
                content=chunk.content,
                uri={'type': 'file', 'value': chunk.filepath}
            ))

        return context_items

    async def get_file_symbols(self, filepath: str, ref: str = None) -> List[Dict]:
        """Get all symbols (functions, classes, etc.) in a file."""
        content = await self.read_file(filepath)
        return await self.parser.get_symbols(filepath, content)

    async def create_pull_request(
        self,
        title: str,
        description: str,
        changes: List[FileChange],
        base_branch: str = None
    ) -> Optional[int]:
        """
        Create a pull request with the specified changes.
        
        Args:
            title: PR title
            description: PR description
            changes: List of file changes
            base_branch: Base branch (defaults to default branch)
            
        Returns:
            PR number if successful
        """
        if base_branch is None:
            base_branch = await self.github.get_default_branch(self.repo)

        # Create a new branch for the changes
        head_branch = f"feature/{title.lower().replace(' ', '-')}-{int(asyncio.get_event_loop().time())}"

        # Convert changes to GitHub format
        github_changes = [
            {'path': change.file, 'content': change.content}
            for change in changes
        ]

        # Create pull request
        pr_number = await self.github.create_pull_request(
            repo=self.repo,
            title=title,
            body=description,
            head_branch=head_branch,
            base_branch=base_branch,
            changes=github_changes
        )

        return pr_number

    async def analyze_changes(self, changes: List[FileChange], ref: str = None) -> Dict:
        """
        Analyze a set of file changes.
        
        Args:
            changes: List of file changes
            ref: Git reference to compare against
            
        Returns:
            Analysis of the changes including affected symbols
        """
        analysis = {
            'affected_symbols': [],
            'new_symbols': [],
            'modified_symbols': []
        }

        for change in changes:
            # Get existing symbols
            old_symbols = []
            try:
                content = await self.github.get_file_content(self.repo, change.file, ref=ref)
                if content:
                    old_symbols = await self.parser.get_symbols(change.file, content)
            except:
                pass  # File might not exist

            # Get new symbols
            new_symbols = await self.parser.get_symbols(change.file, change.content)

            # Compare symbols
            old_symbol_names = {s['name'] for s in old_symbols}
            new_symbol_names = {s['name'] for s in new_symbols}

            analysis['new_symbols'].extend([
                s for s in new_symbols if s['name'] not in old_symbol_names
            ])
            analysis['modified_symbols'].extend([
                s for s in new_symbols if s['name'] in old_symbol_names
            ])
            analysis['affected_symbols'].extend(old_symbols)

        return analysis 