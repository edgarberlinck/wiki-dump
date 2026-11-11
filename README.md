# wiki-dump

**Turn a Wikipedia subject and its linked articles into one readable PDF.**

Built for collecting reference material for chatbot knowledge bases, retrieval-
augmented generation (RAG), and responsibly curated training datasets. Pick a
subject, choose how far to follow its links, and let Gotenberg assemble the PDF.

> **Responsible use only.** Do not use this project for piracy, copyright
> infringement, bypassing access controls, or any illegal or unethical purpose.
> Publicly accessible content is not automatically free of obligations.

## What it does

- Searches English Wikipedia for your subject and retrieves full article text.
- Follows existing article links breadth-first, keeping the starting article first.
- Includes each resolved article once, avoiding cycles and duplicate redirects.
- Limits traversal by depth and total article count.
- Creates a UTF-8 PDF through Gotenberg, with a contents list, source attribution,
  and internal links between included articles.

Images, audio, video, and other remote assets are omitted. Links are not filtered
for topical relevance: a band article can lead to places, genres, people, and
much more.

## Quick start

You need **Docker with Docker Compose** and **make**.

```sh
git clone git@github.com:edgarberlinck/wiki-dump.git
cd wiki-dump
make dump
```

That's it. The image builds, Gotenberg starts, and the exporter waits for it to
be healthy. The default subject is **The Ramones**, and the PDF is written to
`out/The_Ramones.pdf` in the project directory. The output directory is created
automatically.

Choose a subject and traversal limits:

```sh
make dump subject="The Ramones" depth=2 max_articles=1000
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `subject` | `The Ramones` | Subject to search on English Wikipedia |
| `depth` | `2` | Number of link levels to follow |
| `max_articles` | `100` | Maximum articles, including the starting article |
| `ARGS` | Empty | Additional Python CLI options |

Depth `0` includes only the starting article. Depth `1` also includes its direct
links. Depth `2` also follows links from those articles.

**The article cap takes precedence over depth.** A page with hundreds of direct
links may fill the entire budget before deeper links are followed. A warning is
printed when the article limit truncates traversal. Increase it deliberately:
recursive Wikipedia exports can grow very large.

To collect the starting article and up to 999 directly linked articles:

```sh
make dump subject="The Ramones" depth=1 max_articles=1000
```

Choose an output filename:

```sh
make dump subject="Punk rock" ARGS="--output out/punk-rock.pdf"
```

Gotenberg stays running for subsequent exports. Stop it when you're done:

```sh
docker compose down
```

Generated PDFs and local environments are excluded from Git. Everything in
`out/` is ignored except the `.gitkeep` placeholder.

## Using the output for chatbots

The PDF is a **collection artifact**, not a ready-to-train dataset. Extract and
clean its text before ingestion or training, retain source references, and
review the material for relevance, accuracy, duplication, and sensitive content.
For RAG, split the text into useful chunks and preserve article-level source
metadata so answers can cite their references.

Wikipedia can contain errors, biased language, vandalism, and personal
information. Do not treat it as verified ground truth or assume that public
availability makes every downstream use appropriate.

## Responsible use and content licensing

Use this project only with content you are authorized to collect and use.

- **No piracy or infringement:** do not use it to obtain or distribute content
  unlawfully, remove attribution, or evade licensing obligations.
- **Respect the source:** follow Wikipedia's terms, API policies, and applicable
  rate limits. Keep traversal bounded; do not launch abusive bulk crawling.
- **Respect people:** do not use collected material for harassment, deception,
  privacy violations, or other harmful or unethical applications.
- **Keep provenance:** retain source links and applicable license notices when
  building datasets or sharing collected text.
- **Review downstream use:** verify that your chatbot, training pipeline, and
  dataset distribution comply with applicable law and content licenses.

Wikipedia text is generally available under
[Creative Commons Attribution-ShareAlike 4.0](https://creativecommons.org/licenses/by-sa/4.0/),
subject to applicable terms and exceptions. Consult each source page and
[Wikipedia's reuse guidance](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content)
for attribution, share-alike, and other requirements. The PDF includes source
links and a license notice; these do not replace your own compliance review.

Using content for AI training does **not** automatically waive copyright,
privacy, or licensing obligations. This tool provides no additional rights to
Wikipedia content and does not determine the legality of a particular use.

## Local Python

To run Python locally while keeping Gotenberg in Docker:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
docker compose up -d --wait gotenberg
make dump-local PYTHON=.venv/bin/python subject="The Ramones" \
  depth=1 max_articles=1000
```

For an existing Gotenberg instance, set `GOTENBERG_URL` or pass
`--gotenberg-url http://host:port` through `ARGS`. Local runs default to
`http://127.0.0.1:3000`; Compose uses `http://gotenberg:3000`.

See all CLI options:

```sh
.venv/bin/python dump.py --help
```

## Development

Run the focused tests after installing the Python requirements:

```sh
.venv/bin/python -m unittest -v
```

The tests cover traversal limits, cycles, redirects, full article retrieval,
HTML assembly, and the Gotenberg request.
