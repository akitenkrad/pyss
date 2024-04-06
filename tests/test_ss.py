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
    ss = SemanticScholar(max_retry_count=15, silent=True, threshold=0.95)
    paper_id = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"
    paper_detail = {}
    try:
        paper_detail = ss.get_paper_detail(paper_id)
    except Exception as e:
        print(e)
    assert paper_detail.get("abstract", "") != ""


def test_get_paper_detail():
    ss = SemanticScholar(max_retry_count=15, silent=True, threshold=0.95)
    author_id = "40348417"
    author_detail = {}
    try:
        author_detail = ss.get_author_detail(author_id)
    except Exception as e:
        print(e)
    assert author_detail.get("name", "") != ""


def test_get_paper_references():
    ss = SemanticScholar(max_retry_count=15, silent=True, threshold=0.95)
    paper_id = "204e3073870fae3d05bcbc2f6a8e263d9b72e776"
    references = []
    try:
        references = ss.get_paper_references(paper_id)
    except Exception as e:
        print(e)
    assert len(references) > 0
    assert references[0]["title"] != ""
