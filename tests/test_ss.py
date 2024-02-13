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
