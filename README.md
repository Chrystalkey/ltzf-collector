# Collector

## Setting up development

The configuration is done via environment variables. 
The project uses the dotenv module and .env files are in the .gitignore, so that might be a convenient way to set them reliably on each run.

Required for an actual run are the `LTZF_API_KEY` and the `OPENAI_API_KEY` variables, without which the collector will not start.

- To execute the collector in the correct environment, run `poetry run python -m collector`
- To format the code (please do before committing), run `poetry run black .`
- To test your code you might want to run `poetry run pytest`

## Structure
The python package collector is a superstructure for the actual scrapers. 
One collector instance bundles some common tasks scrapers have to do anyways such as sending, caching, error handling, document extraction, connecting to a llm etc.
It also offers a "main loop", that runs all loaded scrapers in a regular interval.

The actual scrapers are found by file name in the subdirectory `scrapers/`. All files called `*_scraper.py` containing a class inheriting from either `VorgangsScraper` or `SitzungsScraper` are loaded and executed as a scraper.

Some points of contact you might want to familiarize yourself with:
- `config.py`: The spot in which environment variables are loaded per-collector and the program is configured
- `main.py`: Contains the main loop in which you can set the sleep timeout
- `interface.py`: The class defining abstract classes base classes for scrapers
- `document.py`: Document extraction class. Tries to bundle the common tasks in extracting pdf documents
