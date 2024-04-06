import json
import re
import socket
import string
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union
from urllib.error import HTTPError, URLError

from attrdict import AttrDict
from dateutil.parser import parse as parse_date
from sumeval.metrics.rouge import RougeCalculator
from tqdm import tqdm


class NoPaperFoundException(Exception):
    def __init__(self, msg: str):
        self.__msg = msg

    def __repr__(self) -> str:
        return f"NO PAPER FUND EXCEPTION: {self.__msg}"

    def __str__(self) -> str:
        return f"NO PAPER FUND EXCEPTION: {self.__msg}"


@dataclass
class Api(object):
    search_by_title: str = "https://api.semanticscholar.org/graph/v1/paper/search?{QUERY}"
    search_by_id: str = "https://api.semanticscholar.org/graph/v1/paper/{PAPER_ID}?{PARAMS}"
    search_by_author_id: str = "https://api.semanticscholar.org/graph/v1/author/{AUTHOR_ID}?{PARAMS}"
    search_references: str = "https://api.semanticscholar.org/graph/v1/paper/{PAPER_ID}/references?{PARAMS}"


class SemanticScholar(object):
    CACHE_PATH: Path = Path("__cache__/papers.pickle")

    def __init__(self, threshold: float = 0.95, silent: bool = True, max_retry_count: int = 5):
        self.__api: Api = Api()
        self.__rouge: RougeCalculator = RougeCalculator(
            stopwords=True, stemming=False, word_limit=-1, length_limit=-1, lang="en"
        )
        self.__threshold: float = threshold
        self.__silent: bool = silent
        self.__max_retry_count: int = max_retry_count

    @property
    def threshold(self) -> float:
        return self.__threshold

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
            it = (
                tqdm(range(60, 0, -1), desc="Error with code -3: Waiting for 1 min")
                if self.__silent
                else range(60, 0, -1)
            )
            for _ in it:
                time.sleep(1.0)
        elif isinstance(ex, HTTPError) and ex.code == 429:
            it = (
                tqdm(range(60, 0, -1), desc="API Limit Exceeded: Waiting for 1 min")
                if self.__silent
                else range(60, 0, -1)
            )
            for _ in it:
                time.sleep(1.0)
        else:
            time.sleep(5.0)
        return retry

    def get_paper_id_from_title(self, title: str, api_timeout: float = 5.0) -> str:
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
                time.sleep(3.0)
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

    def get_paper_detail(self, paper_id: str, api_timeout: float = 5.0) -> dict[str, Any]:
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
                    self.__api.search_by_id.format(PAPER_ID=paper_id, PARAMS=params), timeout=api_timeout
                )
                time.sleep(3.0)
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

    def get_author_detail(self, author_id: str, api_timeout: float = 5.0) -> dict[str, Any]:
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
                    self.__api.search_by_author_id.format(AUTHOR_ID=author_id, PARAMS=params), timeout=api_timeout
                )
                time.sleep(3.0)
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

    def get_paper_references(self, paper_id: str, api_timeout: float = 5.0) -> list[dict[str, Any]]:
        retry = 0
        while retry < self.__max_retry_count:
            try:
                fields = [
                    "contexts",
                    "intents",
                    "contextsWithIntent",
                    "isInfluential",
                    "paperId",
                    "corpusId",
                    "url",
                    "title",
                    "venue",
                    "publicationVenue",
                    "year",
                    "authors",
                    "externalIds",
                    "abstract",
                    "referenceCount",
                    "citationCount",
                    "influentialCitationCount",
                    "isOpenAccess",
                    "openAccessPdf",
                    "fieldsOfStudy",
                    "s2FieldsOfStudy",
                    "publicationTypes",
                    "publicationDate",
                    "journal",
                    "citationStyles",
                ]
                params = f'fields={",".join(fields)}'
                response = urllib.request.urlopen(
                    self.__api.search_references.format(PAPER_ID=paper_id, PARAMS=params), timeout=api_timeout
                )
                time.sleep(3.0)
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

        data = json.loads(response.read().decode("utf-8"))

        references = []
        for p in data["data"]:
            content = p["citedPaper"]
            dict_data = {}
            dict_data["paper_id"] = self.__clean(content, "paperId", "")

            if dict_data["paper_id"] == "":
                continue

            dict_data["contexts"] = self.__clean(content, "contexts", [])
            dict_data["intents"] = self.__clean(content, "intents", "")
            dict_data["contexts_with_intent"] = self.__clean(content, "contextsWithIntent", "")
            dict_data["is_influential"] = self.__clean(content, "isInfluential", False)
            dict_data["corpus_id"] = self.__clean(content, "corpusId", "")
            dict_data["url"] = self.__clean(content, "url", "")
            dict_data["title"] = self.__clean(content, "title", "")
            dict_data["venue"] = self.__clean(content, "venue", "")
            dict_data["publication_venue"] = self.__clean(content, "publicationVenue", "")
            dict_data["year"] = self.__clean(content, "year", 0)
            dict_data["authors"] = self.__clean(content, "authors", [])
            dict_data["external_ids"] = self.__clean(content, "externalIds", {})
            dict_data["abstract"] = self.__clean(content, "abstract", "")
            dict_data["reference_count"] = self.__clean(content, "referenceCount", 0)
            dict_data["citation_count"] = self.__clean(content, "citationCount", 0)
            dict_data["influential_citation_count"] = self.__clean(content, "influentialCitationCount", 0)
            dict_data["is_open_access"] = self.__clean(content, "isOpenAccess", False)
            dict_data["open_access_pdf"] = self.__clean(content, "openAccessPdf", {}).get("url", "")
            dict_data["fields_of_study"] = self.__clean(content, "fieldsOfStudy", [])
            dict_data["s2_fields_of_study"] = self.__clean(content, "s2FieldsOfStudy", [])
            dict_data["publication_types"] = self.__clean(content, "publicationTypes", [])
            dict_data["publication_date"] = self.__clean(content, "publicationDate", "")
            if dict_data["publication_date"]:
                dict_data["publication_date"] = parse_date(dict_data["publication_date"])
            dict_data["journal"] = self.__clean(content, "journal", "")
            references.append(dict_data)

        return references
