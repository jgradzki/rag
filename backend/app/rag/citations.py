"""Filtering the [n] citations in a streamed answer."""

import re
from collections.abc import AsyncIterator

CITATION = re.compile(r"(\s*)\[(\d+)\]")
# Held back at the end of the text until the next token: whatever may still become a
# citation ("[", "[1", whitespace) and trailing complete citations, so that dropping one
# can see whether another follows ("B [3]" + "[2]" -> "B [2]").
UNFINISHED_CITATION = re.compile(r"(?:\s*\[\d+\])*\s*(?:\[\d*)?$")
CODE_DELIMITER = re.compile(r"(```|`)")


async def drop_invalid_citations(tokens: AsyncIterator[str], sources: int) -> AsyncIterator[str]:
    """Remove [n] citations that point at no retrieved chunk (n outside 1..sources).

    Small models sometimes cite [1] even when nothing was retrieved. A citation can
    arrive split over several tokens ("[", "1", "]"), so a possibly unfinished one is
    held back until the next token completes or rules it out. Code is left as it is:
    "arr[5]" there is an index, not a citation. Empty tokens (reasoning models stream
    them while they think) are not passed on.
    """
    in_fence = in_inline = False

    def replace(m: re.Match[str]) -> str:
        space, number = m.groups()
        if 1 <= int(number) <= sources:
            return m.group(0)
        # "B [3][2]" -> "B [2]": keep the space when another citation follows
        return space if m.string.startswith("[", m.end()) else ""

    def clean(text: str) -> str:
        nonlocal in_fence, in_inline
        parts = CODE_DELIMITER.split(text)  # odd items are the delimiters
        for i, part in enumerate(parts):
            if i % 2 == 0:
                if not (in_fence or in_inline):
                    parts[i] = CITATION.sub(replace, part)
            elif part == "```" and not in_inline:
                in_fence = not in_fence
            elif part == "`" and not in_fence:
                in_inline = not in_inline
        return "".join(parts)

    pending = ""
    async for token in tokens:
        pending += token
        held = UNFINISHED_CITATION.search(pending).start()
        held = len(pending[:held].rstrip("`"))  # "``" may still become a fence: "``" + "`"
        ready, pending = clean(pending[:held]), pending[held:]
        if ready:
            yield ready
    if pending := clean(pending):
        yield pending
