# Collector

## Usage

The configuration is largely described in the `example-config.toml`.

However there are a few cli-only options you should be aware of:
`--dump-config`  : reads the current configuration of the program as it
would be if started now, prints it out and exits.

`--linearize`    : forces the program to extract single-threaded. Useful
for debugging, testing, and just in general checking out how it works.
Be aware that there is some rate-limiting done program-internally, but
this rate limits only the requests per second, not the tokens per
second that openai uses. So you might run into trouble by running the
scrapers in parallel. The quickest "fix" is then to pass `--linearize`.

`--run [scraper]`: run only the scrapers described in there. This does a
case-insensitive starts-with match on the class name of the scraper.
This means `bylts` matches `ByltSitzungsScraper` and `ByltScraper`,
`byltsc` only matches the second one. Check beforehand which scrapers
are available.

In general the Configuration is taken from three places: 
1. the config file              _is overridden by_
2. the environment variables    _is overridden by_
3. the command line arguments

which iteratively override each others values. This means e.g. if the
config file configures `linearize=false` and the cli arg `--linearize`
is passed, `linearize` is in effect.
Check the configuration and its origin by running the collector with
`--dump-config`

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

