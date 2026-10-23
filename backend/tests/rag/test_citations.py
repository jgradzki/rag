import asyncio

import pytest

from app.rag.citations import drop_invalid_citations


def run(tokens: list[str], sources: int) -> list[str]:
    async def gen():
        for t in tokens:
            yield t

    async def collect():
        return [t async for t in drop_invalid_citations(gen(), sources)]

    return asyncio.run(collect())


@pytest.mark.parametrize(
    ("tokens", "sources", "expected"),
    [
        # nothing retrieved -> every citation goes, with the space before it
        (["Not in the documents [1]."], 0, "Not in the documents."),
        # a citation split over tokens is still recognised
        (["Not found", " [", "1", "]", "."], 0, "Not found."),
        # valid citations stay, invalid ones in the same answer go
        (["A [1], B [3][2]."], 2, "A [1], B [2]."),
        # an invalid citation completed at a token boundary keeps the next one's space
        (["B [3]", "[2]."], 2, "B [2]."),
        # ids are 1-based: [0] never points at a source
        (["A [0]."], 2, "A."),
        (["A [0]."], 0, "A."),
        # not citations: Markdown link text, an unfinished bracket at the end
        (["See [docs](x) and [", "12"], 0, "See [docs](x) and [12"),
        # code is left alone, citations after it are filtered again
        (["Use `arr[5]` or `m[", "2]` [1] [5]."], 1, "Use `arr[5]` or `m[2]` [1]."),
        (["```py\nx = a[7]\n```\nSee [7]."], 1, "```py\nx = a[7]\n```\nSee."),
        # a fence split over tokens is still one fence, not three inline backticks
        (["``", "`\na[9]\n```\nEnd [9]."], 0, "```\na[9]\n```\nEnd."),
    ],
)
def test_drop_invalid_citations(tokens, sources, expected):
    assert "".join(run(tokens, sources)) == expected


def test_empty_tokens_are_not_passed_on():
    assert run(["", "", "Hi", "", " there", ""], 1) == ["Hi", " there"]
