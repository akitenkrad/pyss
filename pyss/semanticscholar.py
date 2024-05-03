from __future__ import annotations

import json
import re
import socket
import string
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import Any, Optional, Union
from urllib.error import HTTPError, URLError

from dateutil.parser import parse as parse_date
from sumeval.metrics.rouge import RougeCalculator
from tqdm import tqdm


class NoAuthorFoundException(Exception):
    def __init__(self, msg: str):
        self.__msg = msg

    def __repr__(self) -> str:
        return f"NO AUTHOR FOUND EXCEPTION: {self.__msg}"

    def __str__(self) -> str:
        return f"NO AUTHOR FOUND EXCEPTION: {self.__msg}"


class NoPaperFoundException(Exception):
    def __init__(self, msg: str):
        self.__msg = msg

    def __repr__(self) -> str:
        return f"NO PAPER FOUND EXCEPTION: {self.__msg}"

    def __str__(self) -> str:
        return f"NO PAPER FOUND EXCEPTION: {self.__msg}"


class ExceedMaxRetryCountException(Exception):
    def __init__(self, msg: str):
        self.__msg = msg

    def __repr__(self) -> str:
        return f"EXCEED MAX RETRY COUNT: {self.__msg}"

    def __str__(self) -> str:
        return f"EXCEED MAX RETRY COUNT: {self.__msg}"


@dataclass
class Api(object):
    search_by_title: str = "https://api.semanticscholar.org/graph/v1/paper/search?{QUERY}"
    search_by_id: str = "https://api.semanticscholar.org/graph/v1/paper/{PAPER_ID}?{PARAMS}"
    search_by_author_id: str = "https://api.semanticscholar.org/graph/v1/author/{AUTHOR_ID}?{PARAMS}"
    search_by_author_name: str = "https://api.semanticscholar.org/graph/v1/author/search?query={QUERY}&{PARAMS}"
    search_references: str = "https://api.semanticscholar.org/graph/v1/paper/{PAPER_ID}/references?{PARAMS}"


@dataclass()
class Author(object):
    author_id: str
    author_name: str
    url: str
    affiliations: list[str]
    paper_count: int
    citation_count: int
    hindex: int

    def __eq__(self, other: object) -> bool:
        return self.author_id == other.author_id

    def __hash__(self) -> int:
        return hash(self.author_id)

    def __lt__(self, other: Author) -> bool:
        return self.author_id < other.author_id

    def exact_match(self, other: Author):
        return (
            self.author_id == other.author_id
            and self.author_name == other.author_name
            and self.affiliations == other.affiliations
            and self.paper_count == other.paper_count
            and self.citation_count == other.citation_count
            and self.hindex == other.hindex
        )


@dataclass
class Paper(object):
    paper_id: str
    title: str
    abstract: str
    authors: list[Author]
    url: str
    venue: str
    publication_date: datetime
    reference_count: int
    citation_count: int
    influential_citation_count: int
    is_open_access: bool
    fields_of_study: list[str]
    citations: list[Paper]
    references: list[Paper]

    @property
    def year(self) -> int:
        return self.publication_date.year

    def __eq__(self, other: object) -> bool:
        return self.paper_id == other.paper_id

    def __hash__(self) -> int:
        return hash(self.ss_id)

    def __lt__(self, other: Paper) -> bool:
        return self.paper_id < other.paper_id

    def exact_match(self, other: Paper):
        return (
            self.title == other.title
            and self.abstract == other.abstract
            and self.venue == other.venue
            and self.year == other.year
            and self.url == other.url
            and self.publication_date == other.publication_date
            and self.reference_count == other.reference_count
            and self.citation_count == other.citation_count
            and self.influential_citation_count == other.influential_citation_count
            and self.is_open_access == other.is_open_access
            and self.fields_of_study == other.fields_of_study
            and all([a.exact_match(b) for a, b in zip(sorted(self.authors), sorted(other.authors))])
            and all([c.exact_match(d) for c, d in zip(sorted(self.citations), sorted(other.citations))])
            and all([r.exact_match(s) for r, s in zip(sorted(self.references), sorted(other.references))])
        )


class SemanticScholar(object):
    """
    A class for interacting with the Semantic Scholar API to retrieve paper and author information.

    Args:
        threshold (float, optional): The threshold value for matching paper titles (default: 0.95).
        silent (bool, optional): Whether to suppress console output (default: True).
        max_retry_count (int, optional): The maximum number of retries for API requests (default: 5).
    """

    CACHE_PATH: Path = Path("__cache__/papers.pickle")

    def __init__(
        self, threshold: float = 0.95, silent: bool = False, max_retry_count: int = 5, logger: Optional[Logger] = None
    ):
        self.__api: Api = Api()
        self.__rouge: RougeCalculator = RougeCalculator(
            stopwords=True, stemming=False, word_limit=-1, length_limit=-1, lang="en"
        )
        self.__threshold: float = threshold
        self.__silent: bool = silent
        self.__max_retry_count: int = max_retry_count
        self.__logger = logger

    @property
    def threshold(self) -> float:
        return self.__threshold

    @property
    def max_retry_count(self) -> int:
        return self.__max_retry_count

    def __clean(self, dic: dict, key: str, default: Any) -> Any:
        res = default
        if key in dic:
            if isinstance(default, list) and isinstance(dic[key], list):
                res = dic[key]
            elif isinstance(default, dict) and isinstance(dic[key], dict):
                res = dic[key]
            elif isinstance(default, str) and isinstance(dic[key], str):
                res = dic[key]
            elif dic[key] and isinstance(default, datetime):
                res = parse_date(dic[key])
            elif isinstance(default, int) and isinstance(dic[key], int):
                res = dic[key]
            elif isinstance(default, float) and isinstance(dic[key], float):
                res = dic[key]

        return res

    def __retry_and_wait(
        self, msg: str, ex: Union[HTTPError, URLError, socket.timeout, Exception], retry: int, sleep: float = 3.0
    ) -> int:
        retry += 1
        if self.__max_retry_count < retry:
            raise ex

        if not self.__silent and self.__logger is not None:
            self.__logger.warning(msg)

        if isinstance(ex, HTTPError) and ex.errno == -3:
            it = (
                tqdm(range(30, 0, -1), desc="Error with code -3: Waiting for 30 sec", leave=False)
                if not self.__silent
                else range(30, 0, -1)
            )
            for _ in it:
                time.sleep(1.0)
        elif isinstance(ex, HTTPError) and ex.code == 429:
            it = (
                tqdm(range(30, 0, -1), desc="API Limit Exceeded: Waiting for 30 sec", leave=False)
                if not self.__silent
                else range(30, 0, -1)
            )
            for _ in it:
                time.sleep(1.0)
        elif isinstance(ex, HTTPError):
            raise ex
        else:
            time.sleep(sleep)
        return retry

    def is_match_title(self, title: str, ref_title: str) -> bool:
        """
        Check if the given title matches the reference title.

        Args:
            title (str): The title to check.
            ref_title (str): The reference title to match against.

        Returns:
            bool: True if the title matches the reference title, False otherwise.
        """
        # remove punctuation
        title = title.lower()
        ref_title = ref_title.lower()
        for punc in string.punctuation:
            title = title.replace(punc, " ")
            ref_title = ref_title.replace(punc, " ")
        title = re.sub(r"\s\s+", " ", title, count=1000)
        ref_title = re.sub(r"\s\s+", " ", ref_title, count=1000)

        score = self.__rouge.rouge_l(summary=title, references=ref_title)
        return score > self.threshold

    def get_paper_id_from_title(self, title: str, api_timeout: float = 5.0, sleep: float = 3.0) -> str:
        """
        Retrieves the paper ID from the given title using the Semantic Scholar API.

        Args:
            title (str): The title of the paper.
            api_timeout (float, optional): The timeout value for the API request. Defaults to 5.0.

        Returns:
            str: The paper ID if found, or an empty string if not found.
        """
        # remove punctuation
        title = title
        for punc in string.punctuation:
            title = title.replace(punc, " ")
        title = re.sub(r"\s\s+", " ", title, count=1000)

        retry = 0
        while retry < self.__max_retry_count:
            try:
                params = {
                    "query": title,
                    "fields": "title",
                    "offset": 0,
                    "limit": 100,
                }
                response = urllib.request.urlopen(
                    self.__api.search_by_title.format(QUERY=urllib.parse.urlencode(params)), timeout=api_timeout
                )
                content = json.loads(response.read().decode("utf-8"))
                time.sleep(sleep)
                break

            except HTTPError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)
            except URLError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)
            except socket.timeout as ex:
                retry = self.__retry_and_wait(f"WARNING: API Timeout -> Retry: {retry}", ex, retry, sleep)
            except Exception as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)

            if self.__max_retry_count <= retry:
                raise ExceedMaxRetryCountException(f"Exceeded Max Retry Count @ {title}")

        if "data" not in content:
            raise NoPaperFoundException(f"No Data Found @ {title}")

        for item in content["data"]:
            # remove punctuation
            ref_str = item["title"].lower()
            for punc in string.punctuation:
                ref_str = ref_str.replace(punc, " ")
            ref_str = re.sub(r"\s\s+", " ", ref_str, count=1000)

            if self.is_match_title(title, ref_str):
                return item["paperId"].strip()
        return ""

    def get_paper_detail(self, paper_id: str, api_timeout: float = 5.0, sleep: float = 3.0) -> Paper:
        """
        Retrieves detailed information about a paper from the Semantic Scholar API.

        Args:
            paper_id (str): The ID of the paper to retrieve information for.
            api_timeout (float, optional): The timeout value for the API request in seconds. Defaults to 5.0.

        Returns:
            dict[str, Any]: A dictionary containing the detailed information of the paper.
            Information in the dictionary includes:
            - paper_id: The ID of the paper.
            - url: The URL of the paper.
            - title: The title of the paper.
            - abstract: The abstract of the paper.
            - venue: The venue of the paper.
            - year: The year of the paper.
            - reference_count: The reference count of the paper.
            - citation_count: The citation count of the paper.
            - influential_citation_count: The influential citation count of the paper.
            - is_open_access: Whether the paper is open access.
            - fields_of_study: The fields of study of the paper.
            - authors: The authors of the paper.
            - citations: The citations of the paper.
            - references: The references of the paper.

        Raises:
            NoPaperFoundException: If the maximum retry count is exceeded and no paper is found.

        """
        retry = 0
        while retry < self.__max_retry_count:
            try:
                fields = [
                    "paperId",
                    "url",
                    "title",
                    "abstract",
                    "venue",
                    "year",
                    "referenceCount",
                    "citationCount",
                    "influentialCitationCount",
                    "isOpenAccess",
                    "fieldsOfStudy",
                    "publicationDate",
                    "authors.authorId",
                    "authors.name",
                    "authors.url",
                    "authors.affiliations",
                    "authors.hIndex",
                    "authors.paperCount",
                    "authors.citationCount",
                    "citations.paperId",
                    "citations.title",
                    "citations.year",
                    "citations.url",
                    "citations.abstract",
                    "citations.authors",
                    "citations.venue",
                    "citations.journal",
                    "citations.fieldsOfStudy",
                    "citations.publicationDate",
                    "citations.referenceCount",
                    "citations.citationCount",
                    "citations.influentialCitationCount",
                    "references.paperId",
                    "references.title",
                    "references.year",
                    "references.url",
                    "references.abstract",
                    "references.authors",
                    "references.venue",
                    "references.journal",
                    "references.fieldsOfStudy",
                    "references.publicationDate",
                    "references.referenceCount",
                    "references.citationCount",
                    "references.influentialCitationCount",
                ]
                params = f'fields={",".join(fields)}'
                response = urllib.request.urlopen(
                    self.__api.search_by_id.format(PAPER_ID=paper_id, PARAMS=params), timeout=api_timeout
                )
                time.sleep(sleep)
                break

            except HTTPError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)
            except URLError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)
            except socket.timeout as ex:
                retry = self.__retry_and_wait(f"WARNING: API Timeout -> Retry: {retry}", ex, retry, sleep)
            except Exception as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)

            if self.__max_retry_count <= retry:
                raise ExceedMaxRetryCountException(f"Exceeded Max Retry Count @ {paper_id}")

        content = json.loads(response.read().decode("utf-8"))

        paper = Paper(
            paper_id=self.__clean(content, "paperId", ""),
            title=self.__clean(content, "title", ""),
            abstract=self.__clean(content, "abstract", ""),
            authors=[
                Author(
                    author_id=self.__clean(item, "authorId", ""),
                    author_name=self.__clean(item, "name", ""),
                    url=self.__clean(item, "url", ""),
                    affiliations=self.__clean(item, "affiliations", []),
                    paper_count=self.__clean(item, "paperCount", 0),
                    citation_count=self.__clean(item, "citationCount", 0),
                    hindex=self.__clean(item, "hIndex", 0),
                )
                for item in self.__clean(content, "authors", [])
            ],
            venue=self.__clean(content, "venue", ""),
            url=self.__clean(content, "url", ""),
            publication_date=self.__clean(content, "publicationDate", datetime(1900, 1, 1)),
            reference_count=self.__clean(content, "referenceCount", 0),
            citation_count=self.__clean(content, "citationCount", 0),
            influential_citation_count=self.__clean(content, "influentialCitationCount", 0),
            is_open_access=self.__clean(content, "isOpenAccess", False),
            fields_of_study=self.__clean(content, "fieldsOfStudy", []),
            citations=[
                Paper(
                    paper_id=self.__clean(item, "paperId", ""),
                    title=self.__clean(item, "title", ""),
                    abstract=self.__clean(item, "abstract", ""),
                    authors=[
                        Author(
                            author_id=self.__clean(author_item, "authorId", ""),
                            author_name=self.__clean(author_item, "name", ""),
                            url=self.__clean(author_item, "url", ""),
                            affiliations=self.__clean(author_item, "affiliations", []),
                            paper_count=self.__clean(author_item, "paperCount", 0),
                            citation_count=self.__clean(author_item, "citationCount", 0),
                            hindex=self.__clean(author_item, "hIndex", 0),
                        )
                        for author_item in self.__clean(item, "authors", [])
                    ],
                    venue=self.__clean(item, "venue", ""),
                    url=self.__clean(item, "url", ""),
                    publication_date=self.__clean(item, "publicationDate", datetime(1900, 1, 1)),
                    reference_count=self.__clean(item, "referenceCount", 0),
                    citation_count=self.__clean(item, "citationCount", 0),
                    influential_citation_count=self.__clean(item, "influentialCitationCount", 0),
                    is_open_access=self.__clean(item, "isOpenAccess", False),
                    fields_of_study=self.__clean(item, "fieldsOfStudy", []),
                    citations=[],
                    references=[],
                )
                for item in self.__clean(content, "citations", [])
            ],
            references=[
                Paper(
                    paper_id=self.__clean(item, "paperId", ""),
                    title=self.__clean(item, "title", ""),
                    abstract=self.__clean(item, "abstract", ""),
                    authors=[
                        Author(
                            author_id=self.__clean(author_item, "authorId", ""),
                            author_name=self.__clean(author_item, "name", ""),
                            url=self.__clean(author_item, "url", ""),
                            affiliations=self.__clean(author_item, "affiliations", []),
                            paper_count=self.__clean(author_item, "paperCount", 0),
                            citation_count=self.__clean(author_item, "citationCount", 0),
                            hindex=self.__clean(author_item, "hIndex", 0),
                        )
                        for author_item in self.__clean(item, "authors", [])
                    ],
                    venue=self.__clean(item, "venue", ""),
                    url=self.__clean(item, "url", ""),
                    publication_date=self.__clean(item, "publicationDate", datetime(1900, 1, 1)),
                    reference_count=self.__clean(item, "referenceCount", 0),
                    citation_count=self.__clean(item, "citationCount", 0),
                    influential_citation_count=self.__clean(item, "influentialCitationCount", 0),
                    is_open_access=self.__clean(item, "isOpenAccess", False),
                    fields_of_study=self.__clean(item, "fieldsOfStudy", []),
                    citations=[],
                    references=[],
                )
                for item in self.__clean(content, "references", [])
            ],
        )

        return paper

    def get_author_detail_by_name(
        self, author_name: str, paper_id: str, api_timeout: float = 5.0, sleep: float = 3.0
    ) -> Author:
        retry = 0
        while retry < self.__max_retry_count:
            try:
                fields = [
                    "authorId",
                    "url",
                    "name",
                    "affiliations",
                    "paperCount",
                    "citationCount",
                    "hIndex",
                ]
                params = f'fields={",".join(fields)}'
                query = "+".join([urllib.parse.quote(s) for s in author_name.lower().split()])
                url = self.__api.search_by_author_name.format(QUERY=query, PARAMS=params)
                response = urllib.request.urlopen(url, timeout=api_timeout)
                time.sleep(sleep)
                break

            except HTTPError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)
            except URLError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)
            except socket.timeout as ex:
                retry = self.__retry_and_wait(f"WARNING: API Timeout -> Retry: {retry}", ex, retry, sleep)
            except Exception as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)

            if self.__max_retry_count <= retry:
                raise Exception(f"Exceeded Max Retry Count @ {author_name}")

        content = json.loads(response.read().decode("utf-8"))

        if "data" not in content:
            raise NoAuthorFoundException(f"No Data Found @ {author_name}")

        author = None
        if paper_id and len(content["data"]) > 0:
            for data in content["data"]:
                for paper in data["papers"]:
                    if paper["paperId"] == paper_id:
                        author = data
        elif len(content["data"]) > 0:
            author = content["data"][0]
        else:
            raise NoAuthorFoundException(f"No Author Found @ {author_name}")

        if author is None:
            raise NoAuthorFoundException(f"No Author Found @ {author_name}")

        author = Author(
            author_id=self.__clean(author, "authorId", ""),
            author_name=self.__clean(author, "name", ""),
            url=self.__clean(author, "url", ""),
            affiliations=self.__clean(author, "affiliations", []),
            paper_count=self.__clean(author, "paperCount", 0),
            citation_count=self.__clean(author, "citationCount", 0),
            hindex=self.__clean(author, "hIndex", 0),
        )
        return author

    def get_author_detail(self, author_id: str, api_timeout: float = 5.0, sleep: float = 3.0) -> Author:
        retry = 0
        while retry < self.__max_retry_count:
            try:
                fields = [
                    "authorId",
                    "url",
                    "name",
                    "affiliations",
                    "paperCount",
                    "citationCount",
                    "hIndex",
                ]
                params = f'fields={",".join(fields)}'
                response = urllib.request.urlopen(
                    self.__api.search_by_author_id.format(AUTHOR_ID=author_id, PARAMS=params), timeout=api_timeout
                )
                time.sleep(sleep)
                break

            except HTTPError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)
            except URLError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)
            except socket.timeout as ex:
                retry = self.__retry_and_wait(f"WARNING: API Timeout -> Retry: {retry}", ex, retry, sleep)
            except Exception as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry, sleep)

            if self.__max_retry_count <= retry:
                raise Exception(f"Exceeded Max Retry Count @ {author_id}")

        content = json.loads(response.read().decode("utf-8"))

        author = Author(
            author_id=self.__clean(content, "authorId", ""),
            author_name=self.__clean(content, "name", ""),
            url=self.__clean(content, "url", ""),
            affiliations=self.__clean(content, "affiliations", []),
            paper_count=self.__clean(content, "paperCount", 0),
            citation_count=self.__clean(content, "citationCount", 0),
            hindex=self.__clean(content, "hIndex", 0),
        )
        return author
