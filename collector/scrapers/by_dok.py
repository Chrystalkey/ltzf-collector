import re
from collector.document_builder import *
import logging
import datetime
import hashlib
import os
import uuid
from kreuzberg import ExtractionConfig, extract_file, TesseractConfig, PSMMode
import toml

logger = logging.getLogger(__name__)


def schlagwort_format(x: list[str]) -> list:
    return dedup([s.strip().lower() for s in x])


def dedup(x: list) -> list:
    out = []
    for val in x:
        if not val in out:
            out.append(val)
    return out


def pretransform_standard():
    input_dictionary = toml.load(
        os.path.join(os.path.dirname(__file__), "bylt_standardization.toml")
    )
    matches = {}
    for matchentry in input_dictionary["org"]["match"]:
        for match in matchentry["match"]:
            matches[match] = matchentry["replace_with"]
    output = {
        "org": {"regex": input_dictionary["org"]["regex"], "match": matches},
    }
    return output


standard_dictionary = pretransform_standard()


def sanitize_orga(word: str) -> str:
    global standard_dictionary

    torgs = standard_dictionary["org"]
    regex = torgs["regex"]
    mrep = torgs["match"]

    replaced = word.strip()
    modified = False
    for rx in regex:
        if rx.get("partial"):
            if re.search(rx["partial"], replaced):
                modified = True
                replaced = re.sub(rx["partial"], rx["replace_with"], replaced)
        elif rx.get("full"):
            if re.fullmatch(rx["full"], replaced):
                modified = True
                replaced = rx["replace_with"]
        else:
            raise Exception(
                "Expected one of `partial`,`full` in regex entry of standardization dictionary"
            )
    if modified:
        word = replaced
    replmatch_prep = word.lower().strip()
    if replmatch_prep in mrep.keys():
        return mrep[replmatch_prep]
    else:
        return word


def sanitize_author(a: models.Autor) -> models.Autor:
    a.organisation = sanitize_orga(a.organisation)
    return a


def sanitize_authors(l: list) -> list:
    return dedup([sanitize_author(a) for a in l])


class BayernDokument(DocumentBuilder):
    def __init__(self, typehint: models.Doktyp, url, session, config):
        self.full_text = None
        self.hash = None
        self.zp_erstellt = None
        self.zp_modifiziert = None
        self.fileid = uuid.uuid4()
        self.trojanergefahr = None
        self.tops = None
        super().__init__(typehint, url, session, config)

    async def extract_metadata(self):
        try:
            doc_hash = None
            with open(f"{self.fileid}.pdf", "rb") as f:
                # Calculate file hash for document identification
                f.seek(0)
                doc_hash = hashlib.file_digest(f, "sha256").hexdigest()

            # Extract text from all pages
            try:
                extract = await extract_file(
                    f"{self.fileid}.pdf",
                    config=ExtractionConfig(
                        ocr_config=TesseractConfig(
                            language="deu", psm=PSMMode.SINGLE_BLOCK
                        )
                    ),
                )
            except Exception as e:
                logger.warning(
                    f"No text extracted from PDF or extraction failed for document: {self.url}"
                )
                logger.warning(f"Failed with Error: {e}")
                raise
            created = (
                extract.metadata.get("created_at")
                if extract.metadata.get("created_at")
                else datetime.datetime.now(datetime.UTC).isoformat()
            )
            if created.startswith("D:"):
                if created[17:19] != "":
                    created = f"{created[2:6]}-{created[6:8]}-{created[8:10]}T{created[10:12]}:{created[12:14]}:{created[14:16]}+{created[17:19]}:{created[20:22]}"
                else:
                    created = f"{created[2:6]}-{created[6:8]}-{created[8:10]}T{created[10:12]}:{created[12:14]}:{created[14:16]}+00:00"
            modified = (
                extract.metadata.get("modified_at")
                if extract.metadata.get("modified_at")
                else datetime.datetime.now(datetime.UTC).isoformat()
            )
            if modified.startswith("D:"):
                if modified[17:19] != "":
                    modified = f"{modified[2:6]}-{modified[6:8]}-{modified[8:10]}T{modified[10:12]}:{modified[12:14]}:{modified[14:16]}+{modified[17:19]}:{modified[20:22]}"
                else:
                    modified = f"{modified[2:6]}-{modified[6:8]}-{modified[8:10]}T{modified[10:12]}:{modified[12:14]}:{modified[14:16]}+00:00"

            self.hash = doc_hash
            self.titel = extract.metadata.get("title") or "Ohne Titel"
            self.zp_erstellt = created
            self.zp_modifiziert = modified
            self.full_text = extract.content

        except Exception as e:
            logger.error(f"Error extracting metadata from PDF: {e}")
        finally:
            self.cleanup_files()

    def __del__(self):
        self.cleanup_files()

    def cleanup_files(self):
        """Clean up any temporary files created during document processing"""
        try:
            if self.fileid and os.path.exists(f"{self.fileid}.pdf"):
                os.remove(f"{self.fileid}.pdf")
        except Exception as e:
            logger.warning(
                f"Failed to remove temporary PDF file. Exception ignored: {e}"
            )

    def to_dict(self) -> dict:
        dic = super().to_dict()
        dic.update(
            {
                "fileid": str(self.fileid),
                "trojanergefahr": self.trojanergefahr,
                "tops": self.tops,
            }
        )
        return dic

    @classmethod
    def from_dict(cls, dic):
        inst = super().from_dict(dic)
        inst.fileid = uuid.UUID(dic["fileid"])
        inst.trojanergefahr = dic["trojanergefahr"]
        inst.tops = dic["tops"]
        return inst


HEADER_PROMPT = """Extrahiere aus dem folgenden Auszug aus einem Gesetzentwurf folgende Eckdaten als JSON:
        {"titel": "Offizieller Titel des Dokuments", "kurztitel": "zusammenfassung des titels in einfacher Sprache", 
        "date": "datum auf das sich das Dokument bezieht im ISO-Format YYYY-mm-DDTHH:MM:SSZ und Zeitzone UTC",
         "autoren": [{"person": "name einer person", organisation: "name der organisation der die person angehört"}], 
         "institutionen": ["liste von institutionen von denen das dokument stammt"]}
         Sollten sich einige Informationen nicht extrahieren lassen, füge einfach standardwerte (autor/institution = leere Liste) oder füge "Unbekannt" ein. Halluziniere unter keinen Umständen nicht vorhandene Informationen.
          Antworte mit nichts anderem als den gefragen Informationen, formatiere sie nicht gesondert. END PROMPT\n
        """
HEADER_SCHEMA = {
    "type": "object",
    "properties": {
        "titel": {"type": "string"},
        "kurztitel": {"type": "string"},
        "date": {
            "type": "string",
            "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(.\d*)?(Z|([+-]\d{2}:\d{2}))",
        },
        "autoren": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "person": {"type": "string"},
                    "organisation": {"type": "string"},
                },
                "required": ["person", "organisation"],
            },
        },
        "institutionen": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titel", "kurztitel", "date", "autoren", "institutionen"],
}


class ByGesetzentwurf(BayernDokument):
    def __init__(self, typehint, url, drucksnr, session, config):
        self.drucksnr = drucksnr
        self.trojanergefahr = None
        return super().__init__(typehint, url, session, config)

    async def extract_semantics(self):
        global HEADER_PROMPT, HEADER_SCHEMA
        body_prompt = """Extrahiere aus dem gesamttext des folgenden Gesetzes eine Liste an schlagworten, die inhaltlich bedeutsam sind sowie eine Zusammenfassung in 150-250 Worten. 
        Gib außerdem eine "Trojanergefahr" an, also einen Wert zwischen 1 und 10, der angibt wie wahrscheinlich es ist, dass die vorgeschlagenen Änderungen einem anderen Zweck dienen als es den Anschein hat.
        Formatiere sie als JSON wie folgt:
        {"schlagworte": [], summary: "150-250 Worte", "troja": <int>}
          Antworte mit nichts anderem als den gefragen Informationen, formatiere sie nicht gesondert. END PROMPT
          """
        body_schema = {
            "type": "object",
            "properties": {
                "schlagworte": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
                "troja": {"type": "integer"},
            },
            "required": ["schlagworte", "summary", "troja"],
        }

        try:
            hdr = await self.config.llm_connector.extract_info(
                self.full_text[0 : min(3000, len(self.full_text))],
                HEADER_PROMPT,
                HEADER_SCHEMA,
                f"hdr-entwurf:{self.url}",
                self.config.cache,
            )
            bdy = await self.config.llm_connector.extract_info(
                self.full_text,
                body_prompt,
                body_schema,
                f"bdy-entwurf:{self.url}",
                self.config.cache,
            )
            autoren = [
                models.Autor.from_dict(
                    {"person": a["person"], "organisation": a["organisation"]}
                )
                for a in hdr["autoren"]
            ]
            autoren.extend(
                [
                    models.Autor.from_dict({"organisation": a})
                    for a in hdr["institutionen"]
                ]
            )
            autoren = sanitize_authors(autoren)

            zp_referenz = datetime.datetime.fromisoformat(hdr["date"]).astimezone(
                tz=datetime.UTC
            )
            self.trojanergefahr = int(bdy["troja"])
            self.output = models.Dokument.from_dict(
                {
                    "typ": self.typehint,
                    "titel": hdr["titel"],
                    "drucksnr": self.drucksnr,
                    "volltext": self.full_text,
                    "autoren": autoren,
                    "schlagworte": schlagwort_format(bdy["schlagworte"]),
                    "hash": self.hash,
                    "zp_modifiziert": self.zp_modifiziert,
                    "zp_created": self.zp_erstellt,
                    "zp_referenz": zp_referenz,
                    "link": self.url,
                    "zusammenfassung": bdy["summary"],
                }
            )
        except Exception as e:
            logger.error(f"Error extracting semantics: {e}")
            logger.error(
                f"LLM Response was inadequate or contained ill-formatted fields even after retry"
            )
            self.corrupted = True
            raise


class ByStellungnahme(BayernDokument):
    def __init__(self, typehint, url, session, config):
        self.trojanergefahr = None
        return super().__init__(typehint, url, session, config)

    async def extract_semantics(self):
        global HEADER_SCHEMA, HEADER_PROMPT

        body_prompt = """Extrahiere aus dem gesamttext des folgenden Gesetzes eine Liste an schlagworten, die inhaltlich bedeutsam sind sowie eine Zusammenfassung in 150-250 Worten. 
        Gib außerdem eine "Meinung" an als einen Wert zwischen 1(grundsätzlich ablehnend) und 5(lobend), der das Meinungsbild des Dokuments wiederspiegelt
        Formatiere sie als JSON wie folgt:
        {"schlagworte": [], summary: "150-250 Worte", "meinung": <int>}
          Antworte mit nichts anderem als den gefragen Informationen, formatiere sie nicht gesondert. END PROMPT
          """
        body_schema = {
            "type": "object",
            "properties": {
                "schlagworte": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
                "meinung": {"type": "integer"},
            },
            "required": ["schlagworte", "summary", "meinung"],
        }

        try:
            hdr = await self.config.llm_connector.extract_info(
                self.full_text[0 : min(3000, len(self.full_text))],
                HEADER_PROMPT,
                HEADER_SCHEMA,
                f"hdr-stln:{self.url}",
                self.config.cache,
            )
            bdy = await self.config.llm_connector.extract_info(
                self.full_text,
                body_prompt,
                body_schema,
                f"bdy-stln:{self.url}",
                self.config.cache,
            )
            autoren = [
                models.Autor.from_dict(
                    {"person": a["person"], "organisation": a["organisation"]}
                )
                for a in hdr["autoren"]
            ]
            autoren.extend(
                [
                    models.Autor.from_dict({"organisation": a})
                    for a in hdr["institutionen"]
                ]
            )
            autoren = sanitize_authors(autoren)
            zp_referenz = datetime.datetime.fromisoformat(hdr["date"]).astimezone(
                tz=datetime.UTC
            )
            self.output = models.Dokument.from_dict(
                {
                    "typ": self.typehint,
                    "titel": hdr["titel"],
                    "volltext": self.full_text,
                    "autoren": autoren,
                    "schlagworte": schlagwort_format(bdy["schlagworte"]),
                    "hash": self.hash,
                    "zp_modifiziert": self.zp_modifiziert,
                    "zp_created": self.zp_erstellt,
                    "zp_referenz": zp_referenz,
                    "meinung": int(bdy["meinung"]),
                    "link": self.url,
                    "zusammenfassung": bdy["summary"],
                }
            )
        except Exception as e:
            logger.error(f"Error extracting semantics: {e}")
            logger.error(
                f"LLM Response was inadequate or contained ill-formatted fields even after retry"
            )
            self.corrupted = True
            raise


class ByBeschlussempfehlung(BayernDokument):
    def __init__(self, typehint, url, drucksnr, session, config):
        self.drucksnr = drucksnr
        self.trojanergefahr = None
        return super().__init__(typehint, url, session, config)

    async def extract_semantics(self):
        global HEADER_SCHEMA, HEADER_PROMPT

        body_prompt = """Extrahiere aus dem Gesamttext der folgenden Beschlussempfehlung eine Liste an Schlagworten, die inhaltlich bedeutsam sind sowie eine Zusammenfassung in 150-250 Worten. 
        Gib eine "Meinung" an als einen Wert zwischen 1(grundsätzlich ablehnend) und 5(lobend), der das Meinungsbild des Dokuments wiederspiegelt
        Gib schließlich eine "Trojanergefahr" an, also einen Wert zwischen 1 und 10, der angibt wie wahrscheinlich es ist, dass die vorgeschlagenen Änderungen einem anderen Zweck dienen als es den Anschein hat.
        Formatiere sie als JSON wie folgt:
        {"schlagworte": [], summary: "150-250 Worte", "meinung": <int>, "troja": <int>}
          Antworte mit nichts anderem als den gefragen Informationen, formatiere sie nicht gesondert. END PROMPT
          """
        body_schema = {
            "type": "object",
            "properties": {
                "schlagworte": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
                "troja": {"type": "integer"},
                "meinung": {"type": "integer"},
            },
            "required": ["schlagworte", "summary", "meinung", "troja"],
        }

        try:
            hdr = await self.config.llm_connector.extract_info(
                self.full_text[0 : min(3000, len(self.full_text))],
                HEADER_PROMPT,
                HEADER_SCHEMA,
                f"hdr-beschlempf:{self.url}",
                self.config.cache,
            )
            bdy = await self.config.llm_connector.extract_info(
                self.full_text,
                body_prompt,
                body_schema,
                f"bdy-beschlempf:{self.url}",
                self.config.cache,
            )
            autoren = [
                models.Autor.from_dict(
                    {"person": a["person"], "organisation": a["organisation"]}
                )
                for a in hdr["autoren"]
            ]
            autoren.extend(
                [
                    models.Autor.from_dict({"organisation": a})
                    for a in hdr["institutionen"]
                ]
            )
            autoren = sanitize_authors(autoren)
            zp_referenz = datetime.datetime.fromisoformat(hdr["date"]).astimezone(
                tz=datetime.UTC
            )
            logger.error(f"Body Object: {bdy}")
            self.trojanergefahr = int(bdy["troja"])
            self.output = models.Dokument.from_dict(
                {
                    "typ": self.typehint,
                    "drucksnr": self.drucksnr,
                    "titel": hdr["titel"],
                    "volltext": self.full_text,
                    "autoren": autoren,
                    "schlagworte": schlagwort_format(bdy["schlagworte"]),
                    "hash": self.hash,
                    "zp_modifiziert": self.zp_modifiziert,
                    "zp_created": self.zp_erstellt,
                    "zp_referenz": zp_referenz,
                    "meinung": int(bdy["meinung"]),
                    "link": self.url,
                    "zusammenfassung": bdy["summary"],
                }
            )
        except Exception as e:
            logger.error(f"Error extracting semantics: {e}")
            logger.error(
                f"LLM Response was inadequate or contained ill-formatted fields even after retry"
            )
            self.corrupted = True
            raise


class ByRedeprotokoll(BayernDokument):
    def __init__(self, typehint, url, session, config):
        return super().__init__(typehint, url, session, config)

    async def extract_semantics(self):
        global HEADER_SCHEMA, HEADER_PROMPT

        body_prompt = """Du wirst den Text eines Plenarprotokolls erhalten. Extrahiere eine Zusammenfassung der Diskussion und Schlagworte die das Besprochene beschreiben.
        Gib dein Ergebnis in JSON aus, wie folgt: {"schlagworte": [], "summary": "150-250 Worte"}
        Antworte mit nichts anderem als den gefragen Informationen, formatiere sie nicht gesondert.END PROMPT
        """
        body_schema = {
            "type": "object",
            "properties": {
                "schlagworte": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": ["schlagworte", "summary"],
        }

        try:
            hdr = await self.config.llm_connector.extract_info(
                self.full_text[0 : min(3000, len(self.full_text))],
                HEADER_PROMPT,
                HEADER_SCHEMA,
                f"hdr-rproto:{self.url}",
                self.config.cache,
            )
            bdy = await self.config.llm_connector.extract_info(
                self.full_text,
                body_prompt,
                body_schema,
                f"bdy-rproto:{self.url}",
                self.config.cache,
            )
            autoren = [
                models.Autor.from_dict(
                    {"person": a["person"], "organisation": a["organisation"]}
                )
                for a in hdr["autoren"]
            ]
            autoren.extend(
                [
                    models.Autor.from_dict({"organisation": a})
                    for a in hdr["institutionen"]
                ]
            )
            autoren = sanitize_authors(autoren)
            zp_referenz = datetime.datetime.fromisoformat(hdr["date"]).astimezone(
                tz=datetime.UTC
            )

            self.output = models.Dokument.from_dict(
                {
                    "typ": self.typehint,
                    "titel": hdr["titel"],
                    "volltext": self.full_text,
                    "autoren": autoren,
                    "schlagworte": schlagwort_format(bdy["schlagworte"]),
                    "hash": self.hash,
                    "zp_modifiziert": self.zp_modifiziert,
                    "zp_created": self.zp_erstellt,
                    "zp_referenz": zp_referenz,
                    "link": self.url,
                    "zusammenfassung": bdy["summary"],
                }
            )
        except Exception as e:
            logger.error(f"Error extracting semantics: {e}")
            logger.error(
                f"LLM Response was inadequate or contained ill-formatted fields even after retry"
            )
            self.corrupted = True
            raise


class ByMitteilung(BayernDokument):
    def __init__(self, typehint, url, drucksnr: str, session, config):
        self.trojanergefahr = None
        self.drucksnr = drucksnr
        return super().__init__(typehint, url, session, config)

    async def extract_semantics(self):
        global HEADER_SCHEMA, HEADER_PROMPT

        body_prompt = """Extrahiere aus dem folgenden Text Informationen: 
        Extrahiere eine Zusammenfassung des Dokuments und Schlagworte die das Dokument einordnen.
        Gib dein Ergebnis in JSON aus, wie folgt: {"schlagworte": [], "summary": "150-250 Worte"}
        Antworte mit nichts anderem als den gefragen Informationen, formatiere sie nicht gesondert.END PROMPT
          """
        body_schema = {
            "type": "object",
            "properties": {
                "schlagworte": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": ["schlagworte", "summary"],
        }

        try:
            hdr = await self.config.llm_connector.extract_info(
                self.full_text[0 : min(3000, len(self.full_text))],
                HEADER_PROMPT,
                HEADER_SCHEMA,
                f"hdr-mitt:{self.url}",
                self.config.cache,
            )
            bdy = await self.config.llm_connector.extract_info(
                self.full_text,
                body_prompt,
                body_schema,
                f"bdy-mitt:{self.url}",
                self.config.cache,
            )
            autoren = [
                models.Autor.from_dict(
                    {"person": a["person"], "organisation": a["organisation"]}
                )
                for a in hdr["autoren"]
            ]
            autoren.extend(
                [
                    models.Autor.from_dict({"organisation": a})
                    for a in hdr["institutionen"]
                ]
            )
            autoren = sanitize_authors(autoren)
            zp_referenz = datetime.datetime.fromisoformat(hdr["date"]).astimezone(
                tz=datetime.UTC
            )

            self.output = models.Dokument.from_dict(
                {
                    "typ": self.typehint,
                    "titel": hdr["titel"],
                    "drucksnr": self.drucksnr,
                    "volltext": self.full_text,
                    "autoren": autoren,
                    "schlagworte": schlagwort_format(bdy["schlagworte"]),
                    "hash": self.hash,
                    "zp_modifiziert": self.zp_modifiziert,
                    "zp_created": self.zp_erstellt,
                    "zp_referenz": zp_referenz,
                    "link": self.url,
                    "zusammenfassung": bdy["summary"],
                }
            )
        except Exception as e:
            logger.error(f"Error extracting semantics: {e}")
            logger.error(
                f"LLM Response was inadequate or contained ill-formatted fields even after retry"
            )
            self.corrupted = True
            raise


class ByTagesordnung(BayernDokument):
    def __init__(self, typehint, url, session, config):
        return super().__init__(typehint, url, session, config)

    async def extract_semantics(self):
        header_prompt = """Du wirst einen Auszug aus einer Ankündigung einer Sitzung erhalten. Extrahiere daraus die Daten, die in folgendem JSON-Pseudo Code beschrieben werden:
        {'titel': 'Titel des Dokuments', 'kurztitel': 'Zusammenfassung des Titels in einfacher Sprache', 'date': 'Datum auf das sich das Dokument bezieht als YYYY-MM-DD'
        'autoren': [{'person': 'name einer person', organisation: 'name der organisation der die person angehört'}], 'institutionen': ['liste von institutionen von denen das dokument stammt'], 
        'nummer': <Nummer der Sitzung als Integer>, 'public': <boolean ob die Sitzung öffentlich stattfindet>, }
        sollten sich einige Informationen nicht extrahieren lassen, füge einfach keinen Eintrag hinzu (autor/institution) oder füge 'Unbekannt' ein. Halluziniere unter keinen Umständen nicht vorhandene Informationen.
        Antworte mit nichts anderem als den gefragen Informationen, formatiere sie nicht gesondert.END PROMPT\n"""

        header_schema = {
            "type": "object",
            "properties": {
                "titel": {"type": "string"},
                "kurztitel": {"type": "string"},
                "date": {
                    "type": "string",
                    "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(.\d*)?(Z|([+-]\d{2}:\d{2}))",
                },
                "autoren": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "person": {"type": "string"},
                            "organisation": {"type": "string"},
                        },
                        "required": ["person", "organisation"],
                    },
                },
                "institutionen": {"type": "array", "items": {"type": "string"}},
                "nummer": {"type": "integer"},
                "public": {"type": "boolean"},
            },
            "required": ["titel", "kurztitel", "date", "autoren", "institutionen"],
        }

        body_prompt = """Du wirst den Text von Tagesordnungspunkten für eine Sitzung erhalten.
        Extrahiere die 
        Gib dein Ergebnis in JSON aus, wie folgt: {'schlagworte': [], 'summary': '150-250 Worte', 'tops': [{'titel': 'titel des TOPs', 'drucksachen': [<Liste an behandelten Drucksachennummern als string>]}]}
        Achte darauf, dass Tagesordnungspunkte auch mehrere Unterpunkte oder Anträge enthalten können - diese sollst du trotzdem nur zu dem Toplevel-TOP zuordnen.
        Antworte mit nichts anderem als den gefragen Informationen, formatiere sie nicht gesondert.END PROMPT
        """
        body_schema = {
            "type": "object",
            "properties": {
                "schlagworte": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
                "tops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "titel": {"type": "string"},
                            "drucksachen": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["schlagworte, summary", "tops"],
                    },
                },
            },
            "required": ["schlagworte", "summary", "tops"],
        }

        try:
            hdr = await self.config.llm_connector.extract_info(
                self.full_text[0 : min(3000, len(self.full_text))],
                header_prompt,
                header_schema,
                f"hdr-tops:{self.url}",
                self.config.cache,
            )
            bdy = await self.config.llm_connector.extract_info(
                self.full_text,
                body_prompt,
                body_schema,
                f"bdy-tops:{self.url}",
                self.config.cache,
            )
            autoren = [
                models.Autor.from_dict(
                    {"person": a["person"], "organisation": a["organisation"]}
                )
                for a in hdr["autoren"]
            ]
            autoren.extend(
                [
                    models.Autor.from_dict({"organisation": a})
                    for a in hdr["institutionen"]
                ]
            )
            autoren = sanitize_authors(autoren)
            zp_referenz = datetime.datetime.fromisoformat(hdr["date"]).astimezone(
                tz=datetime.UTC
            )
            self.tops = bdy["tops"]
            self.output = models.Dokument.from_dict(
                {
                    "typ": self.typehint,
                    "titel": hdr["titel"],
                    "volltext": self.full_text,
                    "autoren": autoren,
                    "schlagworte": schlagwort_format(bdy["schlagworte"]),
                    "hash": self.hash,
                    "zp_modifiziert": self.zp_modifiziert,
                    "zp_created": self.zp_erstellt,
                    "zp_referenz": zp_referenz,
                    "link": self.url,
                    "zusammenfassung": bdy["summary"],
                }
            )
        except Exception as e:
            logger.error(f"Error extracting semantics: {e}")
            logger.error(
                f"LLM Response was inadequate or contained ill-formatted fields even after retry"
            )
            self.corrupted = True
            raise
