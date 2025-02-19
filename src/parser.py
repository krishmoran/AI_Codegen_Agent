import os
from pathlib import Path
from typing import Dict, List, Optional, Union
import tree_sitter
from tree_sitter import Language, Parser, Query, Node
from llama_index.core.node_parser import CodeSplitter
from .types import Chunk, Range

class CodeParser:
    def __init__(self, parser_dir: str = None):
        """
        Initialize the code parser with tree-sitter and llama-index CodeSplitter.
        
        Args:
            parser_dir: Directory containing tree-sitter language libraries
        """
        if parser_dir is None:
            parser_dir = os.path.join(os.path.dirname(__file__), "tree_sitter_libs")
        self.parser_dir = parser_dir
        self.parsers: Dict[str, Parser] = {}
        self.languages: Dict[str, Language] = {}
        self.queries: Dict[str, Query] = {}
        
        # Map file extensions to language names
        self.extension_map = {
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".py": "python",
            ".rb": "ruby",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".cs": "c_sharp",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".php": "php",
            ".el": "elisp",
            ".ex": "elixir",
            ".exs": "elixir",
            ".elm": "elm",
            ".ml": "ocaml",
            ".mli": "ocaml",
            ".ql": "ql",
            ".swift": "swift"
        }
        
        # Map file extensions to llama-index language names
        self.llama_lang_map = {
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".py": "python",
            ".rb": "ruby",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".cs": "csharp",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".php": "php",
            ".swift": "swift"
        }

    async def initialize(self) -> None:
        """Initialize parsers for all supported languages."""
        # Build and load languages for symbol extraction
        for ext, lang in self.extension_map.items():
            if lang not in self.languages:
                lang_path = os.path.join(self.parser_dir, f"{lang}.so")
                print(f"Looking for language library: {lang_path}")  # Debug log
                if os.path.exists(lang_path):
                    print(f"Found language library for {lang}")  # Debug log
                    try:
                        self.languages[lang] = Language(lang_path, str(lang))
                        parser = Parser()
                        parser.set_language(self.languages[lang])
                        self.parsers[lang] = parser
                        print(f"Successfully loaded parser for {lang}")  # Debug log
                        
                        # Load query file if it exists
                        query_path = os.path.join(
                            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),  # Go up to root
                            "tree_sitter_queries",
                            f"tree-sitter-{lang}-tags.scm"
                        )
                        if os.path.exists(query_path):
                            with open(query_path) as f:
                                self.queries[lang] = Query(self.languages[lang], f.read())
                                print(f"Loaded query file for {lang}")  # Debug log
                    except Exception as e:
                        print(f"Error loading parser for {lang}: {e}")  # Debug log
                else:
                    print(f"No language library found for {lang}")  # Debug log

    def get_language_for_file(self, filepath: str) -> Optional[str]:
        """Get the language name for a given file path."""
        ext = Path(filepath).suffix.lower()
        if ext in {'.tsx', '.jsx'}:
            return 'typescript' if ext == '.tsx' else 'javascript'  # Use appropriate parser for each
        return self.extension_map.get(ext)

    def get_llama_language_for_file(self, filepath: str) -> Optional[str]:
        """Get the llama-index language name for a given file path."""
        ext = Path(filepath).suffix.lower()
        return self.llama_lang_map.get(ext)

    async def parse_file(self, filepath: str, content: str) -> Optional[tree_sitter.Tree]:
        """Parse a file's content using the appropriate parser."""
        lang = self.get_language_for_file(filepath)
        if not lang or lang not in self.parsers:
            print(f"No parser found for {filepath} (language: {lang})")
            return None
        
        try:
            parser = self.parsers[lang]
            tree = parser.parse(bytes(content, "utf8"))
            if not tree:
                print(f"Failed to parse {filepath}")
            return tree
        except Exception as e:
            print(f"Error parsing {filepath}: {e}")
            return None

    async def get_symbols(self, filepath: str, content: str) -> List[Dict]:
        """Extract symbols (functions, classes, etc.) from code."""
        tree = await self.parse_file(filepath, content)
        if not tree:
            return []

        lang = self.get_language_for_file(filepath)
        if not lang or lang not in self.queries:
            return []

        query = self.queries[lang]
        captures = query.captures(tree.root_node)
        
        symbols = []
        for node, tag in captures:
            if tag.endswith('.definition'):
                symbol = {
                    'type': tag.split('.')[1],
                    'name': node.text.decode('utf8'),
                    'range': {
                        'start': {'line': node.start_point[0], 'character': node.start_point[1]},
                        'end': {'line': node.end_point[0], 'character': node.end_point[1]}
                    }
                }
                symbols.append(symbol)

        return symbols

    async def chunk_code(self, filepath: str, content: str) -> List[Chunk]:
        """Split code into chunks using llama-index CodeSplitter."""
        # Get the appropriate language for llama-index
        lang = self.get_llama_language_for_file(filepath)
        if not lang:
            print(f"Info: No llama-index language support for {filepath}, using single chunk")
            return [Chunk(filepath=filepath, content=content)]

        try:
            # Initialize CodeSplitter with appropriate settings
            splitter = CodeSplitter.from_defaults(
                language=lang,
                chunk_lines=40,  # Number of lines per chunk
                chunk_lines_overlap=15,  # Overlap between chunks
                max_chars=1500  # Max chars per chunk
            )

            # Split the code
            text_chunks = splitter.split_text(content)
            if not text_chunks:
                return [Chunk(filepath=filepath, content=content)]
            
            # Convert to our Chunk format
            chunks = []
            lines = content.splitlines()
            current_line = 0
            
            for text_chunk in text_chunks:
                chunk_lines = text_chunk.splitlines()
                
                # Find where this chunk starts in the original file
                chunk_start = current_line
                chunk_end = min(chunk_start + len(chunk_lines), len(lines))
                
                # Create chunk with correct line range
                chunk = Chunk(
                    filepath=filepath,
                    content=text_chunk,
                    range=Range(
                        start={'line': chunk_start, 'character': 0},
                        end={'line': chunk_end - 1, 'character': 0}
                    )
                )
                chunks.append(chunk)
                
                # Move to next chunk position, accounting for overlap
                current_line = chunk_start + max(1, len(chunk_lines) - 15)  # -15 for overlap
            
            return chunks
            
        except Exception as e:
            print(f"Error chunking {filepath}: {e}")
            return [Chunk(filepath=filepath, content=content)] 