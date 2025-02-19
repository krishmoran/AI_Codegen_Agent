import os
from pathlib import Path
from typing import List, Callable, Dict, Any, AsyncGenerator
import lancedb
import numpy as np
import pyarrow as pa
from tqdm import tqdm
from .types import Chunk, Range

class CodebaseIndex:
    def __init__(
        self,
        embeddings_provider: Callable[[List[str]], List[List[float]]],
        read_file: Callable[[str], str],
        db_path: str = None,
        max_chunk_size: int = 1500  # Roughly matches GPT-4's preferred chunk size
    ):
        """
        Initialize the codebase index.
        
        Args:
            embeddings_provider: Function that takes list of strings and returns embeddings
            read_file: Function that reads file content given a path
            db_path: Path to store the LanceDB database
            max_chunk_size: Maximum tokens per chunk
        """
        if db_path is None:
            db_path = os.path.join(os.path.expanduser("~"), ".codebase_understanding", "index")
        self.db_path = db_path
        self.embeddings_provider = embeddings_provider
        self.read_file = read_file
        self.max_chunk_size = max_chunk_size
        self.table_name = "chunks"
        
        # Create db directory if it doesn't exist
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async def get_connection(self):
        """Get or create LanceDB connection."""
        print(f"\nConnecting to database at: {self.db_path}")
        return lancedb.connect(self.db_path)

    async def get_table(self):
        """Get or create the table for storing embeddings."""
        db = await self.get_connection()
        
        # Try to get existing table first
        tables = db.table_names()
        print(f"Found tables: {tables}")
        
        if self.table_name in tables:
            print(f"Opening existing table: {self.table_name}")
            return db.open_table(self.table_name)
        
        # If table doesn't exist, create it with schema
        print(f"Creating new table: {self.table_name}")
        schema = pa.schema([
            ('id', pa.string()),
            ('content', pa.string()),
            ('embedding', pa.list_(pa.float32(), 1536)),  # OpenAI embedding dimension
            ('filepath', pa.string()),
            ('start_line', pa.int32()),
            ('end_line', pa.int32()),
            ('language', pa.string()),
            ('repo', pa.string()),
            ('branch', pa.string())
        ])
        
        # Create table with schema
        table = db.create_table(
            self.table_name,
            schema=schema,
            mode="create"  # Only create if it doesn't exist
        )
        print("Table created successfully")
        
        return table

    def get_language(self, filepath: str) -> str:
        """Determine language from file extension."""
        ext = Path(filepath).suffix.lower()
        return {
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.py': 'python',
            '.rb': 'ruby',
            '.rs': 'rust',
            '.go': 'go',
            '.java': 'java',
            '.cs': 'c_sharp',
            '.cpp': 'cpp',
            '.c': 'c',
            '.php': 'php',
            '.el': 'elisp',
            '.ex': 'elixir',
            '.elm': 'elm',
            '.ml': 'ocaml',
            '.ql': 'ql',
            '.swift': 'swift'  # Add Swift support
        }.get(ext, 'unknown')

    async def store(self, chunks: List[Chunk], show_progress: bool = True) -> None:
        """
        Store code chunks with their embeddings.
        
        Args:
            chunks: List of chunks from the parser with semantic boundaries
            show_progress: Whether to show progress bar
        """
        if not chunks:
            return

        table = await self.get_table()
        
        # Generate embeddings in batches
        batch_size = 100
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        
        progress = tqdm(
            total=len(chunks),
            desc="Indexing chunks",
            disable=not show_progress
        )

        all_rows = []  # Collect all rows before adding to table
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            
            # Update progress
            progress.set_postfix({"batch": f"{i//batch_size + 1}/{total_batches}"})
            
            try:
                # Get embeddings for the batch
                embeddings = await self.embeddings_provider([chunk.content for chunk in batch])

                # Create rows for this batch
                for chunk, embedding in zip(batch, embeddings):
                    # Ensure we have valid line numbers
                    start_line = chunk.range.start['line'] if chunk.range else 0
                    end_line = chunk.range.end['line'] if chunk.range else 0
                    
                    row = {
                        "id": f"{chunk.filepath}:{start_line}",
                        "filepath": chunk.filepath,
                        "content": chunk.content,
                        "embedding": embedding,
                        "start_line": start_line,
                        "end_line": end_line,
                        "language": self.get_language(chunk.filepath),
                        "repo": chunk.repo,  # Use repo from chunk
                        "branch": chunk.branch  # Use branch from chunk
                    }
                    all_rows.append(row)

                progress.update(len(batch))
            
            except Exception as e:
                progress.write(f"Error processing batch: {e}")
                continue

        progress.close()

        # Add all rows at once if we have any
        if all_rows:
            try:
                print(f"\nAttempting to add {len(all_rows)} rows to table")
                print("Sample row:", all_rows[0])
                
                # First add the data without an index
                table.add(all_rows)
                print("Successfully added rows")
                
                # Verify data was stored
                df = table.to_pandas()
                print(f"\nVerified {len(df)} rows in table")
                print("Table columns:", df.columns.tolist())
                
                # Now try to create an appropriate index based on dataset size
                try:
                    if len(all_rows) < 256:
                        print("Small dataset detected, using HNSW index")
                        table.create_index(
                            vector_column_name="embedding",
                            metric="cosine"  # Use HNSW for small datasets
                        )
                    else:
                        print("Large dataset detected, using IVF_PQ index")
                        table.create_index(
                            vector_column_name="embedding",
                            metric="cosine",
                            num_partitions=min(len(all_rows) // 20, 256),  # Scale partitions with data size
                            num_sub_vectors=96,
                            num_bits=8
                        )
                except Exception as e:
                    print(f"Error creating index: {e}")
                    print("Falling back to no index - data is still searchable")
                
            except Exception as e:
                print(f"Error adding rows to table: {e}")
                raise

    async def retrieve(
        self,
        query: str,
        n: int,
        tags: List[Dict[str, str]],
        filter_directory: str = None,
        language: str = None
    ) -> List[Chunk]:
        """
        Retrieve similar code chunks using vector similarity search.
        
        Args:
            query: Search query
            n: Number of results to return
            tags: List of directory and branch tags
            filter_directory: Optional directory to filter results
            language: Optional language to filter results
            
        Returns:
            List of relevant code chunks
        """
        table = await self.get_table()
        
        # Generate query embedding
        query_embedding = (await self.embeddings_provider([query]))[0]
        print(f"\nExecuting search with query: {query}")

        # Build filter conditions
        filter_conditions = []
        
        # Get repository and branch from tags
        repo_name = None
        branch_name = None
        if tags and len(tags) > 0:
            repo_name = tags[0].get('repo')
            branch_name = tags[0].get('branch')
            
        # Filter by repository and branch if specified
        if repo_name:
            print(f"\nFiltering by repository: {repo_name}")
            filter_conditions.append(f"repo = '{repo_name}'")
            if branch_name:
                print(f"Filtering by branch: {branch_name}")
                filter_conditions.append(f"branch = '{branch_name}'")
        
        # Filter by directory if specified
        if filter_directory:
            print(f"\nFiltering by directory: {filter_directory}")
            filter_conditions.append(f"filepath LIKE '{filter_directory}%'")
        elif tags:
            # Only use directory filters from tags if no specific directory filter
            dir_filters = []
            for tag in tags:
                if tag.get('directory'):
                    dir_filter = tag['directory'].replace('\\', '/')  # Normalize path separators
                    if dir_filter and dir_filter != '/':  # Skip root directory
                        dir_filters.append(f"filepath LIKE '{dir_filter}%'")
            if dir_filters:
                filter_conditions.append(f"({' OR '.join(dir_filters)})")
                print(f"\nFiltering by directories: {dir_filters}")
            
        # Filter by language if specified
        if language:
            print(f"\nFiltering by language: {language}")
            filter_conditions.append(f"language = '{language}'")

        # Combine all filters
        filter_str = " AND ".join(filter_conditions) if filter_conditions else None
        print(f"\nFinal filter conditions: {filter_str}")

        # Perform vector search
        print("\nExecuting vector search...")
        search_query = table.search(query_embedding, vector_column_name="embedding")
        if filter_str:
            search_query = search_query.where(filter_str)
            
        results = search_query.select([
            "filepath", "content", "start_line", "end_line", 
            "repo", "branch", "language"
        ]).limit(n).to_pandas()
        
        print(f"\nFound {len(results)} results")
        if len(results) == 0:
            print("\nNo results found. Table information:")
            df = table.to_pandas()
            print(f"Total rows in table: {len(df)}")
            if len(df) > 0:
                print("\nUnique repositories:", df['repo'].unique())
                print("Unique languages:", df['language'].unique())
                print("Sample filepaths:", df['filepath'].head().tolist())
            return []

        # Convert results to chunks
        chunks = []
        for _, row in results.iterrows():
            try:
                chunk = Chunk(
                    filepath=row.filepath,
                    content=row.content,
                    range=Range(
                        start={"line": row.start_line, "character": 0},
                        end={"line": row.end_line, "character": 0}
                    ),
                    repo=row.repo,
                    branch=row.branch
                )
                chunks.append(chunk)
                
                # Print result information
                print(f"\nFile: {row.filepath}")
                print(f"Repository: {row.repo}")
                print(f"Branch: {row.branch}")
                print(f"Language: {row.language}")
                print(f"Lines {row.start_line}-{row.end_line}")
                print("-" * 80)
                print(row.content)
                print("-" * 80)
            except Exception as e:
                print(f"Error processing row: {e}")
                print(f"Row data: {row}")
                continue

        print(f"\nSuccessfully converted {len(chunks)} results to chunks")
        return chunks

    async def clear(self) -> None:
        """Clear all stored chunks."""
        print("\nClearing database...")
        db = await self.get_connection()
        tables = db.table_names()
        
        if self.table_name in tables:
            print(f"Dropping table {self.table_name}")
            await db.drop_table(self.table_name)
            print("Table dropped successfully")
        
        # No need to close LanceDB connection
        print("Database table cleared") 