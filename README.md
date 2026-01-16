# Collector

## Setting up for development
### Required software
- poetry    # for the project itself
- jre >= 17 # for the oapi generator
- maven     # for the oapi generator

### Environment Configuration
The configuration is done via environment variables. 
The project uses the dotenv module and .env files are in the .gitignore, so that might be a convenient way to set them reliably on each run.

You need to set these env variables:
- `LTZF_API_KEY`: The Api Key with which you connect to the
  LTZF-Backend. Ask the admin of the backend you want to connect to.
- `LTZF_API_URL`: The URL of the Backend you want to connect to
- `COLLECTOR_ID`: The ID with which this Collector will be identified to
  the backend
- `OPENAI_API_KEY`: The Key with which the document extraction works

Place the .env file next to this README.md.

### Steps required for setup
- run `sh oapigen.sh`
- run `poetry install`
- set up your environment

### Further Actions

To execute the collector in the correct environment, run `poetry run python -m collector`
To format the code (please do before committing), run `poetry run black .`
To test your code you might want to run `poetry run pytest`

## Setting up for Deployment
Please use the Docker file. For an example configuration refer to the
docker-compose.yml in
[the meta repo](https://github.com/chrystalkey/landtagszusammenfasser).

## Structure
The python package collector is a superstructure for the actual scrapers. 
One collector instance bundles some common tasks scrapers have to do anyways such as sending, caching, error handling, document extraction, connecting to a llm etc.
It also offers a "main loop", that runs all loaded scrapers in a regular interval.

The actual scrapers are found by file name in the subdirectory `scrapers/`. All files called `*_scraper.py` containing a class inheriting from either `VorgangsScraper` or `SitzungsScraper` are loaded and executed as a scraper.

Some points of contact you might want to familiarize yourself with:
- `config.py`: The spot in which environment variables are loaded per-collector and the program is configured
- `__main__.py`: Contains the main loop in which you can set the sleep timeout
- `interface.py`: The class defining abstract classes base classes for scrapers
- `document.py`: Document extraction class. Tries to bundle the common tasks in extracting pdf documents

