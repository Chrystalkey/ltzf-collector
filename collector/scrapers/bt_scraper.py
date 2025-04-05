import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta, timezone
import uuid
import aiohttp
import json
import re
import openapi_client.models as models
from collector.interface import Scraper
from collector.document import Document


logger = logging.getLogger(__name__)


class BundestagAPIScraper(Scraper):
    CURRENT_WP = 21
    BT_API_KEY = "I9FKdCn.hbfefNWCY336dL6x62vfwNKpoN2RZ1gp21"

    def __init__(self, config, session: aiohttp.ClientSession):
        listing_urls = ["https://search.dip.bundestag.de/api/v1"]
        super().__init__(config, uuid.uuid4(), listing_urls, session)
        # Add headers for API key authentication
        self.session.headers.update({
            'api-key': config.api_key
        })
        self.vorgaenge = {}  # Dictionary zum Speichern der Vorgangsdaten
        self.positionen = {} # Dictionary zum Speichern der Vorgangspositionen
    
    async def listing_page_extractor(self, url) -> list[str]:
        """
        Holt Gesetzesvorhaben von der Bundestags-API
        """
        tage = 5
        if self.config.testing_mode:
            startdatum = datetime(2025, 2, 3)
        else:
            startdatum = datetime.today() - timedelta(days=tage)
        startdatum = startdatum.strftime("%Y-%m-%dT00:00:00")
        if self.config.testing_mode:
            enddatum = datetime(2025, 2, 3)
        else:
            enddatum = datetime.today()
        enddatum = enddatum.strftime("%Y-%m-%dT23:59:59")
        endpoint = f"{self.listing_urls[0]}/vorgang"
        params = {
            "apikey": self.BT_API_KEY,
            "f.aktualisiert.start" : startdatum,
            "f.aktualisiert.end" : enddatum,
            "f.vorgangstyp" : "Gesetzgebung",
            "f.wahlperiode" : self.CURRENT_WP
        }
        
        async with self.session.get(endpoint, params=params) as response:
            if response.status == 200:
                data = await response.json()
                num = data['numFound']
                logger.info(f"{num} Vorgang gefunden für Zeitraum {startdatum} - {enddatum}")
                documents = data.get("documents", [])
                for doc in documents:
                    self.vorgaenge[str(doc.get("id"))] = doc
                return list(self.vorgaenge.keys())
            else:
                logger.debug(f"Error while fetching listing page: {await response.text()}")
                return []
        
    async def item_extractor(self, vorgang_id: str) -> models.Vorgang:
        """
        Transformiert die Bundestags-API-Daten in das Format der OpenAPI-Spezifikation
        """
        if vorgang_id not in self.vorgaenge:
            logger.error(f"Vorgang {vorgang_id} nicht in gespeicherten Daten gefunden")
            return None
            
        vorgang = self.vorgaenge[vorgang_id]
        positionen = await self._get_vorgangspositionen(vorgang_id)

        # Basis-Gesetzesvorhaben erstellen
        gsvh = models.Vorgang.from_dict({
            "api_id": str(uuid.uuid4()),
            "titel": vorgang.get("titel", ""),
            "verfassungsaendernd": "Änderung des Grundgesetzes" in vorgang.get("titel", ""),
            "trojaner": False,  
            "initiatoren": self._extract_initiatoren(vorgang), 
            "typ": self._get_vorgangstyp(vorgang),
            "wahlperiode": self.CURRENT_WP,  
            "ids": [
                models.VgIdent.from_dict({
                    "typ": "vorgnr",
                    "id": str(vorgang.get("id"))
                }),
                models.VgIdent.from_dict({
                    "typ": "initdrucks",
                    "id": self._get_initdrucks_nummer(positionen)
                })
            ],
            "links": [self._create_dip_url(vorgang.get("id"), vorgang.get("titel"))], 
            "stationen": await self._extract_stationen(positionen) 
        })
        
        #logger.info(gsvh.to_dict()) #Kann weg, wenn's läuft
        return gsvh

    async def _get_vorgangspositionen(self, vorgang_id: str) -> List[Dict]:
        """
        Holt die Vorgangspositionen zum Vorgang
        """
        endpoint = f"{self.listing_urls[0]}/vorgangsposition"
        params = {
            "apikey": self.BT_API_KEY,
            "f.vorgang" : vorgang_id,
            "f.wahlperiode" : self.CURRENT_WP
        }

        async with self.session.get(endpoint, params=params) as response:
            if response.status == 200:
                data = await response.json()
                position = data.get("documents", [0])
                return position
            else:
                logger.debug(f"Error while fetching vorgangspositionen: {await response.text()}")
                return []

    def _get_initdrucks_nummer(self, positionen: List[Dict]) -> str:
        """
        Extrahiert die Dokumentennummer aus der Fundstelle für Vorgangspositionen vom Typ 'Gesetzentwurf'        
        """
        for pos in positionen:
            if pos.get("vorgangsposition") == "Gesetzentwurf":
                return pos.get("fundstelle", {}).get("dokumentnummer", "")
        return ""

    def _get_vorgangstyp(self, vorgang: Dict) -> str:
        """Erkennung Zustimmung/Einspruchsgesetz"""
        zustimmungen = vorgang.get("zustimmungsbeduerftigkeit", [])
        
        if not zustimmungen:
            return "sonstig"
            
        gefundene_typen = set()
        
        for item in zustimmungen:
            if item.startswith("Nein"):
                gefundene_typen.add("gg-einspruch")
            elif item.startswith("Ja"):
                gefundene_typen.add("gg-zustimmung")
        
        # Wenn mehrere unterschiedliche Typen gefunden wurden oder kein Typ erkannt wurde
        if len(gefundene_typen) != 1:
            return "sonstig"
            
        # Ansonsten den einzigen gefundenen Typ zurückgeben
        return gefundene_typen.pop()
    
    def _extract_initiatoren(self, vorgang: Dict) -> List[Dict]:
        """Extrahiert die Initiatoren aus den Vorgangsdaten und erstellt Autor-Modelle"""
        initiatoren = []
        if vorgang.get("initiative"):
            for initiator in vorgang["initiative"]:
                autor = models.Autor.from_dict({
                    "organisation": initiator
                }).to_dict()
                initiatoren.append(autor)
        return initiatoren
    
    def _extract_autoren(self, position: Dict) -> List[Dict]:
        """Extrahiert die Autoren aus den Vorgangsdaten und erstellt Autor-Modelle"""
        autoren = []
        if position.get("fundstelle", {}).get("urheber", {}):
            for urheber in position["fundstelle"]["urheber"]:
                autor = models.Autor.from_dict({
                    "organisation": urheber
                }).to_dict()
                autoren.append(autor)
        return autoren

    async def _extract_stationen(self, positionen: List[Dict]) -> List[models.Station]:
        """Extrahiert die Station aus den Vorgangsdaten"""
        stationen = []
        
        for position in positionen:
            station = await self._create_station_from_position(position)
            if station:
                stationen.append(station)
        
        return stationen

    async def _create_station_from_position(self, position: Dict) -> Optional[models.Station]:
        """Erstellt eine Station aus einer Vorgangsaktivität"""
        station_mapping = {
            "Gesetzentwurf": models.Stationstyp.PARL_MINUS_INITIATIV,
            "1. Beratung": models.Stationstyp.PARL_MINUS_AUSSCHBER,
            "1. Durchgang": models.Stationstyp.PARL_MINUS_AUSSCHBER,
            "Beschlussempfehlung und Bericht": models.Stationstyp.PARL_MINUS_BERABGESCHL,
            "Beschlussempfehlung": models.Stationstyp.PARL_MINUS_BERABGESCHL,
            "Empfehlungen der Ausschüsse": models.Stationstyp.PARL_MINUS_BERABGESCHL,
            "Bericht gemäß § 96 Geschäftsordnung BT": models.Stationstyp.PARL_MINUS_VERZOEGERT,
            "2. Beratung": "Abstimmung",
            "3. Beratung": "Abstimmung",
            "2. Durchgang": "Abstimmung",
            "Durchgang": "Abstimmung",       
        }
        
        beschluss_mapping = {
            "Annahme in Ausschussfassung": models.Stationstyp.PARL_MINUS_AKZEPTANZ,
            "Annahme der Vorlage": models.Stationstyp.PARL_MINUS_AKZEPTANZ,
            "Versagung der Zustimmung": models.Stationstyp.PARL_MINUS_ABLEHNUNG,
            "Ablehnung": models.Stationstyp.PARL_MINUS_ABLEHNUNG,
            "Zustimmung": models.Stationstyp.PARL_MINUS_AKZEPTANZ,
            "kein Antrag auf Einberufung des Vermittlungsausschusses": models.Stationstyp.PARL_MINUS_AKZEPTANZ,
            "Anrufung des Vermittlungsausschusses": models.Stationstyp.PARL_MINUS_ABLEHNUNG,
        }
        
        typ = station_mapping.get(position.get("vorgangsposition"))
        if typ == "Abstimmung":
            beschluss = position.get("beschlussfassung", [{}])[0].get("beschlusstenor", "")   
            # Prüfe zuerst auf exakte Übereinstimmung
            typ = beschluss_mapping.get(beschluss)
            # Falls keine exakte Übereinstimmung, prüfe auf gemeinsamen Anfang
            if not typ and beschluss.startswith("kein Antrag auf Einberufung des Vermittlungsausschusses"):
                typ = models.Stationstyp.PARL_MINUS_AKZEPTANZ
            if not typ and beschluss.startswith("Anrufung des Vermittlungsausschusses"):
                typ = models.Stationstyp.PARL_MINUS_ABLEHNUNG
        
        #Wenn gar nichts passt, setze auf Sonstig
        if not typ:
            typ = models.Stationstyp.SONSTIG
         
        #Ermittle die zugehörigen Dokumente
        dokumente = await self._extract_dokumente(position, typ)
        
        # Stelle sicher, dass das Datum korrekt gesetzt wird
        datum = position.get("datum")
        if not datum:
            logger.warning(f"Kein Datum gefunden für Position {position.get('titel', '')}, verwende aktuelles Datum")
            datum = datetime.now().isoformat()
        
        #Erstelle die Station
        return models.Station.from_dict({
            "zp_start": self._parse_date(datum),
            "dokumente": dokumente,             
            "parlament": position.get("zuordnung"),
            "typ": typ,
        })
    
        

    async def _extract_dokumente(self, position: Dict, typ: models.Stationstyp) -> List[Dict]:
        """Extrahiert Dokumente zu einem Vorgang und gibt sie als serialisierbares Dictionary zurück"""
        if not position:
            return []

        #Ermittle die korrekten Typen
        if typ == models.Stationstyp.PARL_MINUS_INITIATIV:
            dokument_typ = models.Doktyp.ENTWURF  # Gesetzesentwurf auf einer Drucksache
        elif typ == models.Stationstyp.PARL_MINUS_BERABGESCHL:
            dokument_typ = models.Doktyp.BESCHLUSSEMPF  # Beschlussempfehlung von Ausschüssen
        else:
            dokument_typ = models.Doktyp.SONSTIG  # Für alle anderen Stationstypen

        btapi_doctyp = position.get("fundstelle", {}).get("drucksachetyp", "")
        drsnr = position.get("fundstelle", {}).get("dokumentnummer", "")

        #Hole Volltext aus API
        endpoint = f"{self.listing_urls[0]}/drucksache-text"    
        params = {
            "apikey": self.BT_API_KEY,
            "f.dokumentnummer" : drsnr,
            "f.wahlperiode" : self.CURRENT_WP,
            "f.drucksachetyp" : btapi_doctyp
        }

        async with self.session.get(endpoint, params=params) as response:
            if response.status == 200:
                data = await response.json()
                volltext = data.get("documents", [{}])[0].get("text", "")
            else:
                volltext = ""
        
        if volltext != "":
            zusammenfassung = await self._get_zusammenfassung(volltext)
        else:
            zusammenfassung = ""
            volltext = ""
        
        logger.info(f"Dokument: {drsnr}, {btapi_doctyp}, Zusammenfassung: {zusammenfassung}")  

        # Erzeuge ein serialisierbares Dictionary für das Dokument
        return [{
            "titel": position.get("titel", ""),
            "zp_modifiziert": self._parse_date(datetime.now().isoformat()),
            "zp_referenz": self._parse_date(position.get("fundstelle", {}).get("datum", "")),
            "link": position.get("fundstelle", {}).get("pdf_url", ""),
            "hash": "",  # Muss noch implementiert werden
            "typ": dokument_typ,
            "zusammenfassung": zusammenfassung,
            "schlagworte": [],
            "drucksnr": drsnr,
            "volltext": volltext,
            "autoren": self._extract_autoren(position)
        }]
    

    async def _get_zusammenfassung(self, volltext: str) -> str:
        """Holt Zusammenfassung von OpenAI"""
        if not volltext:
            return ""
        
        #TODO: Zusammenfassung von OpenAI holen
        
        
        return "Zusammenfassung erstellt"
        
    def _create_dip_url(self, vorgangid, titel):
        #Bildet die URL zum Bundestags DIP aus dem Gesetzestitel
        cleantitle = re.sub(r"[^a-zA-Z0-9]", "-", titel)
        cleantitle = re.sub(r"--", "-", cleantitle)
        cleantitle = cleantitle.lower()
        cleantitle = cleantitle[:100]
        
        url = "https://dip.bundestag.de/vorgang/" + cleantitle + "/" + str(vorgangid)
        return url
    

    def _parse_date(self, date_str: str) -> str:
        """Konvertiert ein Datum-String in das erwartete ISO-Format mit Zeitzone"""
        if not date_str:
            return datetime.now().astimezone().isoformat()
        
        # Liste der möglichen Datumsformate
        date_formats = [
            "%Y-%m-%dT%H:%M:%S.%f",  # ISO mit Millisekunden
            "%Y-%m-%dT%H:%M:%S%z",   # ISO 8601 mit Zeitzone
            "%Y-%m-%dT%H:%M:%S",     # ISO 8601 ohne Zeitzone
            "%Y-%m-%dT00:00:00+00:00",  # Spezifisches Format aus der API
            "%Y-%m-%d"               # Einfaches Datum
        ]
        
        for date_format in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, date_format)
                # Stelle sicher, dass die Zeitzone gesetzt ist
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                return parsed_date.isoformat()
            except ValueError:
                continue
        
        # Falls kein Format passt, gebe das aktuelle Datum zurück
        logger.warning(f"Konnte Datum '{date_str}' nicht parsen, verwende aktuelles Datum")
        return datetime.now().astimezone().isoformat()