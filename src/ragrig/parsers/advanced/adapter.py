from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ragrig.parsers.advanced.models import AdvancedParseResult


class AdvancedParserAdapter(ABC):
    parser_name: str = "abstract"

    @abstractmethod
    def can_parse(self, path: Path) -> bool: ...

    @abstractmethod
    def parse(self, path: Path) -> AdvancedParseResult: ...

    @abstractmethod
    def check_dependencies(self) -> bool: ...

    def get_format(self) -> str:
        ext = self.parser_name.split(".")[-1]
        return ext

    @property
    def display_name(self) -> str:
        return self.parser_name.replace("_", " ").title()
