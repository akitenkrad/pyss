from datetime import datetime
from pathlib import Path

import dotenv

from pyss.semanticscholar import SemanticScholar


def test_semanticscholar():
    assert SemanticScholar() is not None


def test_get_paper_id_from_title():
    ss = SemanticScholar(max_retry_count=15, silent=True, threshold=0.95)

    paper_id = ""
    try:
        paper_id = ss.get_paper_id_from_title("Attention Is All You Need")
    except Exception as e:
        print(e)
    assert paper_id != ""


def test_get_paper_detail():
    # 1. Arrange
    ss = SemanticScholar(max_retry_count=15, silent=True, threshold=0.95)
    paper_id = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"

    # 2. Act
    paper = ss.get_paper_detail(paper_id)

    # 3. Assert
    assert paper.paper_id == paper_id
    assert paper.title.lower() == "attention is all you need"
    assert paper.abstract != ""
    assert paper.authors[0].author_id != ""
    assert paper.authors[0].author_name != ""
    assert paper.citation_count > 0
    assert paper.reference_count > 0
    assert paper.influential_citation_count > 0
    assert paper.publication_date == datetime(2017, 6, 12, 0, 0)
    assert paper.url != ""
    assert paper.year == 2017
    assert len(paper.references) > 0
    assert len(paper.citations) > 0


def test_get_author_detail():
    # 1. Arrange
    ss = SemanticScholar(max_retry_count=15, silent=True, threshold=0.95)
    author_id = "40348417"

    # 2. Act
    author = ss.get_author_detail(author_id)

    # 3. Assert
    assert author.author_id == author_id
    assert author.author_name != ""


def test_get_paper_id_from_title_with_api_key():

    api_key = dotenv.get_key(Path(__file__).parent.parent / ".env", "SEMANTIC_SCHOLAR_API_KEY")

    if not api_key:
        print("API key not found. Skipping the test.")
        return

    ss = SemanticScholar(api_key=api_key, max_retry_count=15, silent=True, threshold=0.95)

    paper_id = ""
    try:
        paper_id = ss.get_paper_id_from_title("Attention Is All You Need")
    except Exception as e:
        print(e)
    assert paper_id != ""


def test_get_paper_detail_with_api_key():
    # 1. Arrange
    api_key = dotenv.get_key(Path(__file__).parent.parent / ".env", "SEMANTIC_SCHOLAR_API_KEY")

    if not api_key:
        print("API key not found. Skipping the test.")
        return

    ss = SemanticScholar(api_key=api_key, max_retry_count=15, silent=True, threshold=0.95)
    paper_id = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"

    # 2. Act
    paper = ss.get_paper_detail(paper_id)

    # 3. Assert
    assert paper.paper_id == paper_id
    assert paper.title.lower() == "attention is all you need"
    assert paper.abstract != ""
    assert paper.authors[0].author_id != ""
    assert paper.authors[0].author_name != ""
    assert paper.citation_count > 0
    assert paper.reference_count > 0
    assert paper.influential_citation_count > 0
    assert paper.publication_date == datetime(2017, 6, 12, 0, 0)
    assert paper.url != ""
    assert paper.year == 2017
    assert len(paper.references) > 0
    assert len(paper.citations) > 0


def test_get_author_detail_with_api_key():
    # 1. Arrange
    api_key = dotenv.get_key(Path(__file__).parent.parent / ".env", "SEMANTIC_SCHOLAR_API_KEY")

    if not api_key:
        print("API key not found. Skipping the test.")
        return

    ss = SemanticScholar(api_key=api_key, max_retry_count=15, silent=True, threshold=0.95)
    author_id = "40348417"

    # 2. Act
    author = ss.get_author_detail(author_id)

    # 3. Assert
    assert author.author_id == author_id
    assert author.author_name != ""
