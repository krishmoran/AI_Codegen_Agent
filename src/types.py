from dataclasses import dataclass
from typing import Optional, Dict, List, Union

@dataclass
class Range:
    start: Dict[str, int]  # line and character
    end: Dict[str, int]    # line and character

@dataclass
class Chunk:
    filepath: str
    content: str
    range: Optional[Range] = None
    repo: str = ""  # Add repo field
    branch: str = ""  # Add branch field

@dataclass
class ContextItem:
    name: str
    description: str
    content: str
    uri: Dict[str, str]  # type and value

@dataclass
class FileChange:
    file: str
    content: str

@dataclass
class GenerationResult:
    changes: List[FileChange]
    description: str 