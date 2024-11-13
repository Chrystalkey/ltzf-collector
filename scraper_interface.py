from abc import ABC, abstractmethod
from typing import Any

'''
The abstract base class for the implementation of a scraper. It will make sure the scrapers all 
define these methods. They can then be called by the scraper manager or simply provide a better overview
when creating new scrapers.
'''

class Scraper(ABC):
    list_urls = []

    @abstractmethod
    def __init__(self, db_connector: Any, llm_connector: Any, list_urls: list[str] = []):
        """
        Initialize the Scraper with a database connector and an llm connector.

        Parameters:
        -----------
        db_connector : Any
            The database connector to interact with the database.
        llm_connector : Any
            The database connector to interact with the llm.
        """
        self.db_connector = db_connector
        self.llm_connector = llm_connector
        self.list_urls = list_urls

    @abstractmethod
    def fetch_content(self, callback: function[int[int, int]]) -> str:
        pass

    @abstractmethod
    def parse_content(self):
        pass

    @abstractmethod
    def send_data(self, data: dict, server_url: str):
        pass
