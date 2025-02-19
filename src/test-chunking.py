import os
from typing import List
from llama_index.core.node_parser import CodeSplitter
from pathlib import Path

def test_code_chunking():
    """Test code chunking using LlamaIndex CodeSplitter."""
    
    # Get example code from codebase.py
    codebase_path = os.path.join(os.path.dirname(__file__), "chunk.ts")
    with open(codebase_path, 'r') as f:
        code = f.read()

    # Initialize CodeSplitter for Python
    splitter = CodeSplitter.from_defaults(
        language="typescript",
        chunk_lines=40,  # Number of lines per chunk
        chunk_lines_overlap=15,  # Overlap between chunks
        max_chars=1500  # Max chars per chunk
    )

    # Split the code
    chunks = splitter.split_text(code)

    # Print chunk info
    print(f"\nSplit code into {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks):
        print(f"\nChunk {i+1}:")
        print(f"Length: {len(chunk)} chars")
        print(f"Lines: {len(chunk.splitlines())}")
        print("Preview:")
        print("---")
        print("\n".join(chunk.splitlines()[:5]))
        print("...")

if __name__ == "__main__":
    test_code_chunking()
