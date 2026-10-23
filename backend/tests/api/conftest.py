import pytest

from tests.api.utils import make_client


@pytest.fixture
def client(tmp_path):
    # Fake embeddings are random, so relevance scores are meaningless - keep every chunk.
    with make_client(tmp_path, min_relevance=-1.0) as c:  # `with` runs the lifespan
        yield c
