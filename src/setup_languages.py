import os
import subprocess
from pathlib import Path
from tree_sitter import Language

# Order matters - some parsers depend on others (e.g., cpp depends on c)
LANGUAGES = [
    ('c', 'tree-sitter-c'),  # C must come before C++
    ('cpp', 'tree-sitter-cpp'),
    ('python', 'tree-sitter-python'),
    ('javascript', 'tree-sitter-javascript'),  # Use dedicated JavaScript parser
    ('typescript', 'tree-sitter-typescript'),  # TypeScript parser (includes TSX)
    ('ruby', 'tree-sitter-ruby'),
    ('rust', 'tree-sitter-rust'),
    ('go', 'tree-sitter-go'),
    ('java', 'tree-sitter-java'),
]

def setup_languages():
    """Build tree-sitter languages."""
    # Get the directory for language libraries
    lib_path = os.path.join(os.path.dirname(__file__), "tree_sitter_libs")
    os.makedirs(lib_path, exist_ok=True)
    
    # Clone and build each language
    for lang_name, repo_name in LANGUAGES:
        print(f"\nSetting up {lang_name}...")
        
        # Clone repository if needed
        repo_path = os.path.join(lib_path, repo_name)
        if not os.path.exists(repo_path):
            try:
                subprocess.run([
                    'git', 'clone',
                    f'https://github.com/tree-sitter/{repo_name}.git',
                    repo_path
                ], check=True)
            except subprocess.CalledProcessError as e:
                print(f"Failed to clone {repo_name}: {e}")
                continue
        
        try:
            # Special handling for TypeScript
            if lang_name == 'typescript':
                # Build TypeScript parser (includes TSX)
                Language.build_library(
                    os.path.join(lib_path, f"{lang_name}.so"),
                    [
                        os.path.join(repo_path, 'typescript'),  # TypeScript parser
                        os.path.join(repo_path, 'tsx')  # TSX parser
                    ]
                )
            else:
                # Build other language parsers normally
                Language.build_library(
                    os.path.join(lib_path, f"{lang_name}.so"),
                    [repo_path]
                )
            print(f"Successfully built {lang_name} parser")
        except Exception as e:
            print(f"Failed to build {lang_name} parser: {e}")
            continue
    
    print("\nLanguage setup complete!")

if __name__ == "__main__":
    setup_languages() 