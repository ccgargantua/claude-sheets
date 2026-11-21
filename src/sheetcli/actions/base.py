from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Handler:
    """fn(doc, args) -> dict for document actions; fn(args) -> dict when free.
    fn None means not implemented. rich: unsupported on csv. free: opens its own session."""
    fn: Optional[Callable] = None
    mutates: bool = False
    rich: bool = False
    free: bool = False


def cmd(sub, name, positional=("file",)):
    sp = sub.add_parser(name)
    for pos in positional:
        sp.add_argument(pos)
    return sp


def with_sheet(sp):
    sp.add_argument("--sheet")
    return sp
