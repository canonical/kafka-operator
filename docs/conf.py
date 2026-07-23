"""Configuration for the Sphinx documentation builder."""

import datetime
import os
import textwrap

import yaml

# Configuration for the Sphinx documentation builder.
# All configuration specific to your project should be done in this file.
#
# If you're new to Sphinx and don't want any advanced or custom features,
# just go through the items marked 'TODO'.
#
# A complete list of built-in Sphinx configuration values:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
#
# The Sphinx Stack uses the Canonical Sphinx theme to keep all
# documentation consistent and on brand:
# https://github.com/canonical/canonical-sphinx


#######################
# Project information #
#######################

# Project name
project = "Charmed Apache Kafka"

# Author name; used in the default copyright statement in the page footer
author = "Canonical Ltd."

# The year in the copyright statement
copyright = f"{datetime.date.today().year}"

# Sidebar documentation title; best kept reasonably short.
# To disable the title, set it to an empty string.
html_title = project + " documentation"

# Documentation website URL
ogp_site_url = "https://canonical.com/data/kafka/docs/"

# Preview name of the documentation website
ogp_site_name = project

# Preview image URL
ogp_image = "https://assets.ubuntu.com/v1/cc828679-docs_illustration.svg"

# Product favicon; shown in bookmarks, browser tabs, etc.
# TODO: To customise the favicon, uncomment and update as needed.
# html_favicon = "_static/favicon.png"

# Dictionary of values to pass into the Sphinx context for all pages:
# https://www.sphinx-doc.org/en/master/usage/configuration.html#confval-html_context
html_context = {
    # Product page URL; can be different from product docs URL
    "product_page": "canonical.com/data/kafka",
    # Product tag image; the orange part of your logo, shown in the page header
    # TODO: To add a tag image, uncomment and update as needed.
    # 'product_tag': '_static/tag.png',
    # Your Discourse instance URL
    "discourse": "https://discourse.charmhub.io",
    # Your Mattermost channel URL
    "mattermost": "https://chat.canonical.com/canonical/channels/documentation",
    # Your Matrix channel URL
    "matrix": "https://matrix.to/#/#documentation:ubuntu.com",
    # Your documentation GitHub repository URL.
    # If set, links for viewing the documentation source files and creating
    # GitHub issues are added at the bottom of each page.
    "github_url": "https://github.com/canonical/kafka-operator",
    # Docs branch in the repo; used in links for viewing the source files
    "repo_default_branch": "main",
    # Docs location in the repo; used in links for viewing the source files
    "repo_folder": "/docs/",
    # To enable or disable the Previous / Next buttons at the bottom of pages
    # Valid options: none, prev, next, both
    "sequential_nav": "both",
    # To enable listing contributors on individual pages, set to True
    "display_contributors": False,
    # Required for feedback button
    "github_issues": "enabled",
    # Passes the top-level 'author' value to the theme
    "author": author,
    # Documentation license information
    "license": {
        "name": "CC-BY-SA",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
    },
}

# To enable the edit button on pages, uncomment and change the link to a
# public repository on GitHub or Launchpad. Any of the following link domains
# are accepted:
# - https://github.com/example-org/example"
# - https://launchpad.net/example
# - https://git.launchpad.net/example
html_theme_options = {
    "source_edit_link": "https://github.com/canonical/kafka-operator",
}

# Project slug; see https://meta.discourse.org/t/what-is-category-slug/87897
slug = "data/kafka/docs"

#######################
# Sitemap configuration: https://sphinx-sitemap.readthedocs.io/
#######################

# Base URL of RTD hosted project
html_baseurl = "https://canonical.com/data/kafka/docs/"

# sphinx-sitemap uses html_baseurl to generate the full URL for each page
sitemap_url_scheme = "{link}"

# Include `lastmod` dates in the sitemap
sitemap_show_lastmod = True

# Pages excluded from the sitemap
sitemap_excludes = [
    "404/",
    "genindex/",
    "search/",
]

################################
# Template and asset locations #
################################

html_static_path = [
    "_static",
]

templates_path = [
    "_templates",
]

#############
# Redirects #
#############

# To set up redirects using sphinx-reredirects:
# https://documatt.gitlab.io/sphinx-reredirects/usage.html
# For example: 'explanation/old-name.html': '../how-to/prettify.html',

# To set up redirects using sphinx-rerediraffe:
# https://sphinxext-rediraffe.readthedocs.io/en/latest/

# To set up redirects in the Read the Docs project dashboard:
# https://docs.readthedocs.io/en/stable/guides/redirects.html

# NOTE: sphinx_reredirects is disabled when 'redirects' is empty.
# NOTE: Do not add sphinx_rerediraffe to extensions unless redirects are
#       configured — it emits a warning that breaks the build under
#       --fail-on-warning. Uncomment when redirects are needed:
# rediraffe_redirects = "redirects.txt"

redirects = {}


############################
# sphinx-llm configuration #
############################

# This description is included in llms.txt to provide some initial context for
# your product docs.
llms_txt_description = textwrap.dedent("""\
    This is the documentation for Charmed Apache Kafka, an automated
    deployment and management solution for Apache Kafka on Ubuntu.
    """)

# The base URL for references built by sphinx-markdown-builder.
if os.environ.get("READTHEDOCS"):
    markdown_http_base = html_baseurl

###########################
# Link checker exceptions #
###########################

# A regex list of URLs that are ignored by 'make linkcheck'
linkcheck_ignore = [
    "http://127.0.0.1:8000",
    "https://github.com/canonical/ACME/*",
    "https://matrix.to/#/#charmhub-data-platform:ubuntu.com",
    "https://us-east-1.console.aws.amazon.com/ec2/",
    "https://launchpad.net/soss",
    "https://cwiki.apache.org/*",
    "https://archive.apache.org/*",
    r"http://worker-\d+\.domain\.com.*",
]

# A regex list of URLs where anchors are ignored by 'make linkcheck'
linkcheck_anchors_ignore_for_url = [r"https://github\.com/.*"]

# How long the link checker will wait for a response for each request
# linkcheck_timeout = 30

# Give linkcheck multiple tries on failure
linkcheck_retries = 3

########################
# Configuration extras #
########################

# Custom MyST syntax extensions; see
# https://myst-parser.readthedocs.io/en/latest/syntax/optional.html
# NOTE: By default, the following MyST extensions are enabled:
#   - substitution
#   - deflist
#   - linkify
# myst_enable_extensions = set()

# Custom Sphinx extensions; see
# https://www.sphinx-doc.org/en/master/usage/extensions/index.html
extensions = [
    "canonical_sphinx",
    "notfound.extension",
    "sphinx_design",
    "sphinx_reredirects",
    "sphinx_tabs.tabs",
    "sphinxcontrib.jquery",
    "sphinxext.opengraph",
    "sphinx_config_options",
    "sphinx_contributor_listing",
    "sphinx_filtered_toctree",
    "sphinx_llm.txt",
    "sphinx_related_links",
    "sphinx_roles",
    "sphinx_terminal",
    "sphinx_ubuntu_images",
    "sphinx_youtube_links",
    "sphinxcontrib.cairosvgconverter",
    "sphinx_last_updated_by_git",
    "sphinx.ext.intersphinx",
    "sphinx_sitemap",
]

# Excludes files or directories from processing
exclude_patterns = [
    "doc-cheat-sheet*",
    "agents.md",
    ".venv*",
    "_dev",
]

# Adds custom CSS files, located under 'html_static_path'
html_css_files = [
    "cookie-banner.css",
]

# Adds custom JavaScript files, located under 'html_static_path'
html_js_files = [
    "bundle.js",
    "overwritelinks.js",
]

# Appends extra markup to the end of every document written in reST
rst_epilog = """
.. include:: /reuse/links.txt
.. include:: /reuse/substitutions.txt
"""

# Feedback button at the top; enabled by default
# TODO: Disable the button if your project is unsuitable for public feedback.
# disable_feedback_button = True

# Your manpage URL
# TODO: To enable manpage links, uncomment and replace {codename} with required
#       release, preferably an LTS release (e.g. noble). Do *not* substitute
#       {section} or {page}; these will be replaced by sphinx at build time
#
# NOTE: If set, adding ':manpage:' to an .rst file
#       adds a link to the corresponding man section at the bottom of the page.
# manpages_url = 'https://manpages.ubuntu.com/manpages/{codename}/en/' + \
#     'man{section}/{page}.{section}.html'

# Specifies a reST snippet to be prepended to each .rst file
# This defines a :center: role that centers table cell content.
# This defines a :h2: role that styles content for use with PDF generation.
rst_prolog = """
.. role:: center
   :class: align-center
.. role:: h2
    :class: hclass2
.. role:: woke-ignore
    :class: woke-ignore
.. role:: vale-ignore
    :class: vale-ignore
"""

# Workaround for https://github.com/canonical/canonical-sphinx/issues/34
if "discourse_prefix" not in html_context and "discourse" in html_context:
    html_context["discourse_prefix"] = html_context["discourse"] + "/t/"

# Workaround for substitutions.yaml
if os.path.exists("./reuse/substitutions.yaml"):
    with open("./reuse/substitutions.yaml", "r") as fd:
        myst_substitutions = yaml.safe_load(fd.read())
