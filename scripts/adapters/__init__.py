"""Explicit tool registry shared by interactive and batch investigations."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Tool:
    name: str
    kind: str
    arguments: Callable
    parse: Callable
    parser_version: int = 1
    report_name: Callable | None = None


from . import holehe, ignorant, maigret, phoneinfoga, sherlock

TOOLS = {module.NAME: Tool(module.NAME, module.KIND, module.arguments, module.parse,
                          report_name=getattr(module, 'report_name', None))
         for module in (maigret, sherlock, holehe, phoneinfoga, ignorant)}
