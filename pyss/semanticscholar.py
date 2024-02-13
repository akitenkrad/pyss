import json
import re
import socket
import string
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional, Union
from urllib.error import HTTPError, URLError

from attrdict import AttrDict
from sumeval.metrics.rouge import RougeCalculator
from tqdm import tqdm


class NoPaperFoundException(Exception):
    def __init__(self, msg: str):
        self.__msg = msg

    def __repr__(self) -> str:
        return f"NO PAPER FUND EXCEPTION: {self.__msg}"

    def __str__(self) -> str:
        return f"NO PAPER FUND EXCEPTION: {self.__msg}"


class SemanticScholar(object):
    API: dict[str, str] = {
        "search_by_title": "https://api.semanticscholar.org/graph/v1/paper/search?{QUERY}",
        "search_by_id": "https://api.semanticscholar.org/graph/v1/paper/{PAPER_ID}?{PARAMS}",
        "search_by_author_id": "https://api.semanticscholar.org/graph/v1/author/{AUTHOR_ID}?{PARAMS}",
    }
    CACHE_PATH: Path = Path("__cache__/papers.pickle")

    def __init__(self, threshold: float = 0.95, silent: bool = True, max_retry_count: int = 5):
        self.__api = AttrDict(self.API)
        self.__rouge = RougeCalculator(stopwords=True, stemming=False, word_limit=-1, length_limit=-1, lang="en")
        self.__threshold = threshold
        self.__silent = silent
        self.__max_retry_count = max_retry_count

    @property
    def threshold(self) -> float:
        return self.__threshold

    def __clean(self, dic: dict, key: str, default: Any) -> Any:
        if key in dic and dic[key] is not None and dic[key] != "" and dic[key] != [] and dic[key] != {}:
            res = dic[key]
        else:
            res = default
        return res

    def __retry_and_wait(self, msg: str, ex: Union[HTTPError, URLError, socket.timeout, Exception], retry: int) -> int:
        retry += 1
        if self.__max_retry_count < retry:
            raise ex
        if retry == 1:
            msg = "\n" + msg

        if not self.__silent:
            print(msg)

        if isinstance(ex, HTTPError) and ex.errno == -3:
            time.sleep(300.0)
        elif isinstance(ex, HTTPError) and ex.code == 429:
            if not self.__silent:
                for i in tqdm(range(60, 0, -1), desc="API Limit Exceeded: Waiting for 1 min"):
                    time.sleep(1.0)
        else:
            time.sleep(5.0)
        return retry

    def get_paper_id_from_title(self, title: str) -> str:
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
                    self.__api.search_by_title.format(QUERY=urllib.parse.urlencode(params)), timeout=5.0
                )
                content = json.loads(response.read().decode("utf-8"))
                time.sleep(3.5)
                break

            except HTTPError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry)
            except URLError as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry)
            except socket.timeout as ex:
                retry = self.__retry_and_wait(f"WARNING: API Timeout -> Retry: {retry}", ex, retry)
            except Exception as ex:
                retry = self.__retry_and_wait(f"WARNING: {str(ex)} -> Retry: {retry}", ex, retry)

            if self.__max_retry_count <= retry:
                raise NoPaperFoundException(f"Exceeded Max Retry Count @ {title}")

        for item in content["data"]:
            # remove punctuation
            ref_str = item["title"].lower()
            for punc in string.punctuation:
                ref_str = ref_str.replace(punc, " ")
            ref_str = re.sub(r"\s\s+", " ", ref_str, count=1000)

            score = self.__rouge.rouge_l(summary=title.lower(), references=ref_str)
            if score > self.threshold:
                return item["paperId"].strip()
        return ""

    def get_paper_detail(self, paper_id: str) -> Optional[dict]:
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
                    "authors",
                    "citations",
                    "references",
                ]
                params = f'fields={",".join(fields)}'
                response = urllib.request.urlopen(
                    self.__api.search_by_id.format(PAPER_ID=paper_id, PARAMS=params), timeout=5.0
                )
                time.sleep(3.5)
                break

            except HTTPError as ex:
                retry = self.__retry_and_wait(f"{str(ex)} -> Retry: {retry}", ex, retry)
            except URLError as ex:
                retry = self.__retry_and_wait(f"{str(ex)} -> Retry: {retry}", ex, retry)
            except socket.timeout as ex:
                retry = self.__retry_and_wait(f"API Timeout -> Retry: {retry}", ex, retry)
            except Exception as ex:
                retry = self.__retry_and_wait(f"{str(ex)} -> Retry: {retry}", ex, retry)

            if self.__max_retry_count <= retry:
                raise NoPaperFoundException(f"Exceeded Max Retry Count @ {paper_id}")

        content = json.loads(response.read().decode("utf-8"))

        dict_data = {}
        dict_data["paper_id"] = content["paperId"]
        dict_data["url"] = self.__clean(content, "url", "")
        dict_data["title"] = self.__clean(content, "title", "")
        dict_data["abstract"] = self.__clean(content, "abstract", "")
        dict_data["venue"] = self.__clean(content, "venue", "")
        dict_data["year"] = self.__clean(content, "year", 0)
        dict_data["reference_count"] = self.__clean(content, "referenceCount", 0)
        dict_data["citation_count"] = self.__clean(content, "citationCount", 0)
        dict_data["influential_citation_count"] = self.__clean(content, "influentialCitationCount", 0)
        dict_data["is_open_access"] = self.__clean(content, "isOpenAccess", False)
        dict_data["fields_of_study"] = self.__clean(content, "fieldsOfStudy", [])
        dict_data["authors"] = (
            [
                {"author_id": item["authorId"], "author_name": item["name"]}
                for item in content["authors"]
                if item["authorId"]
            ]
            if content["authors"]
            else []
        )
        dict_data["citations"] = (
            [{"paper_id": item["paperId"], "title": item["title"]} for item in content["citations"] if item["paperId"]]
            if content["citations"]
            else []
        )
        dict_data["references"] = (
            [{"paper_id": item["paperId"], "title": item["title"]} for item in content["references"] if item["paperId"]]
            if content["references"]
            else []
        )
        return dict_data

    def get_author_detail(self, author_id: str) -> Optional[dict]:
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
                    "papers",
                ]
                params = f'fields={",".join(fields)}'
                response = urllib.request.urlopen(
                    self.__api.search_by_author_id.format(AUTHOR_ID=author_id, PARAMS=params), timeout=5.0
                )
                time.sleep(3.5)
                break

            except HTTPError as ex:
                retry = self.__retry_and_wait(f"{str(ex)} -> Retry: {retry}", ex, retry)
            except URLError as ex:
                retry = self.__retry_and_wait(f"{str(ex)} -> Retry: {retry}", ex, retry)
            except socket.timeout as ex:
                retry = self.__retry_and_wait(f"API Timeout -> Retry: {retry}", ex, retry)
            except Exception as ex:
                retry = self.__retry_and_wait(f"{str(ex)} -> Retry: {retry}", ex, retry)

            if self.__max_retry_count <= retry:
                raise Exception(f"Exceeded Max Retry Count @ {author_id}")

        content = json.loads(response.read().decode("utf-8"))

        dict_data = {}
        dict_data["author_id"] = content["authorId"]
        dict_data["url"] = self.__clean(content, "url", "")
        dict_data["name"] = self.__clean(content, "name", "")
        dict_data["affiliations"] = self.__clean(content, "affiliations", [])
        dict_data["paper_count"] = self.__clean(content, "paperCount", 0)
        dict_data["citation_count"] = self.__clean(content, "citationCount", 0)
        dict_data["hindex"] = self.__clean(content, "hIndex", 0)
        dict_data["papers"] = content["papers"]

        return dict_data
