"""wikitrends: Wikipedia pageview research toolkit behind the
``wikipedia-interest-trends`` agent skill.

The core (fetching, caching, statistics, text output) uses only the Python
standard library. Charts and PDF reports need matplotlib and reportlab, which
``scripts/wt.py`` installs on first use from the pinned lock file.
"""

__version__ = "1.0.0"
