# pyss

Semantic Scholar API Wrapper

## Usage

```python
from pyss import SemanticScholar

ss = SemanticScholar()
paper_id = ss.get_paper_id_from_title("Attention Is All You Need")
paper = ss.get_paper_detail(paper_id=paper_id)
```
