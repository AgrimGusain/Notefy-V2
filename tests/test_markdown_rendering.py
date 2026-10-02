"""Note rendering: fenced code, display/inline math and inline code, with block IDs kept in sync with rag/blocks.py.

Runs the real renderer (frontend/js/app.js) in node. KaTeX is not loaded here, so math is emitted as
pending TeX placeholders; typesetting itself is checked in the browser.
"""
import json, os, re, shutil, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import pytest
from rag.blocks import markdown_blocks

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node is required to run the frontend renderer")

# The content reported as rendering literally: display math, \( \) inline math, \times, and a fenced code block.
GRAPH_NOTE = r"""# Graphs

## Definition
A graph is $$ G=(V,E) $$ where \(V\) is a set of vertices and \(E \subseteq V \times V\) is a set of edges.

$$
|E| \le \frac{|V|(|V|-1)}{2}
$$

## Breadth-first search
```python
# visit neighbours level by level
def bfs(graph, start):
    seen = {start}  # *not* emphasis
    queue = [start]
```

- Running time is $O(|V| + |E|)$ with an adjacency list.
- Uses `collections.deque` for the queue.
"""

NORMAL_NOTE = r"""# Lecture 4: Linear algebra

Intro with **bold**, *italic* and a [link](https://example.com). Costs $5 and $10 stay text.

## Matrices
1. A matrix $A \in \mathbb{R}^{m \times n}$ has $m$ rows.
2. The product is $(AB)_{ij} = \sum_k A_{ik} B_{kj}$.

> Quote stays a quote.

---

\[ \det(A) = ad - bc \]

~~~js
const x = a * b * c;
~~~

| Col | Val |
| --- | --- |
| a   | 1   |
"""

SCRIPT = r"""
const fs=require('fs');const stub=new Proxy(function(){},{get:(t,k)=>k==='addEventListener'?()=>{}:stub,apply:()=>stub});
global.window={};global.document={getElementById:()=>stub,querySelectorAll:()=>[],addEventListener:()=>{},createElement:()=>stub,body:stub,head:stub};
try{eval(fs.readFileSync(process.argv[1],'utf8'));}catch(_){}
const md=fs.readFileSync(0,'utf8'),app=window.AudioNotes;
process.stdout.write(JSON.stringify({html:app.safeMarkdownToHTML(md),ids:app.markdownBlockIds(md.split('\n').map(l=>l.replace(/\r$/,'')))}));
"""


def render(markdown):
    result = subprocess.run(["node", "-e", SCRIPT, os.path.join(ROOT, "frontend", "js", "app.js")], input=markdown.encode("utf-8"), capture_output=True, check=True)
    return json.loads(result.stdout.decode("utf-8"))


def visible_text(html):
    """Text a reader sees before typesetting, minus the TeX held in math placeholders."""
    html = re.sub(r'<span class="math-pending"[^>]*>.*?</span>', " ", html)
    return re.sub(r"<[^>]+>", " ", html)


def test_problem_note_renders_math_and_code_not_syntax():
    out = render(GRAPH_NOTE)
    html = out["html"]
    # Display math on its own lines becomes one block; inline $$…$$, \(…\) and $…$ become inline math.
    assert html.count('class="math-display"') == 1 and r'data-tex="|E| \le \frac{|V|(|V|-1)}{2}"' in html
    inline = re.findall(r'<span class="math-pending" data-tex="([^"]*)" data-display="false">', html)
    assert inline == ["G=(V,E)", "V", r"E \subseteq V \times V", "O(|V| + |E|)"]
    # The fence is one code block; its "# comment" is code, not a heading, and "*not*" is not emphasised.
    code = re.search(r'<pre class="code-block"[^>]*data-language="python"><code>(.*?)</code></pre>', html, re.S).group(1)
    assert code.startswith("# visit neighbours") and "*not* emphasis" in code and "<em>" not in code and "```" not in html
    assert html.count("<h1") == 1 and html.count("<h2") == 2 and "level by level</h" not in html
    assert "<code>collections.deque</code>" in html and "<ul>" in html
    text = visible_text(html)
    assert "$$" not in text and "\\(" not in text and "\\times" not in text and "```" not in text


def test_normal_note_keeps_markdown_and_adds_code_and_math():
    html = render(NORMAL_NOTE)["html"]
    assert '<strong>bold</strong>' in html and '<em>italic</em>' in html and '<a href="https://example.com"' in html
    assert "Costs $5 and $10 stay text." in html  # currency is not math
    assert html.count("<li ") == 2 and "<ol>" in html and "<blockquote" in html
    assert r'data-tex="A \in \mathbb{R}^{m \times n}"' in html and r'data-tex="(AB)_{ij} = \sum_k A_{ik} B_{kj}"' in html  # "_" and "*" inside math untouched
    assert r'class="math-display"' in html and r'data-tex="\det(A) = ad - bc"' in html
    assert '<pre class="code-block"' in html and "const x = a * b * c;" in html and 'data-language="js"' in html
    assert "| Col | Val |" in html  # tables render exactly as before (as text lines)
    assert html.count("<hr ") == 1 and ">---<" not in html  # the rule is drawn, not printed


def test_unclosed_constructs_and_escaping_are_safe():
    html = render("Price: $$ unclosed\n\n<script>alert(1)</script> \\(x < y\\)\n\n```\nopen fence <b>\n")["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html and 'data-tex="x &lt; y"' in html
    assert "<p" in html and "$$ unclosed" in html  # an unmatched $$ stays text
    assert "open fence &lt;b&gt;" in html and html.rstrip().endswith("</code></pre>")  # an unclosed fence runs to the end, like CommonMark


@pytest.mark.parametrize("note", [GRAPH_NOTE, NORMAL_NOTE, "x\n```\n# not a heading\n```\n# Real heading\ny\n", "````\n```\n# still code\n````\n# H\n"])
def test_block_ids_match_backend_and_cover_every_line(note):
    out = render(note)
    python = {block.line: block.id for block in markdown_blocks(note)}
    js = {index + 1: block_id for index, block_id in enumerate(out["ids"]) if block_id}
    assert js == python
    # Every block ID is reachable on a rendered element (multi-line blocks list theirs in data-block-ids).
    rendered = set(re.findall(r'data-block-id="([^"]+)"', out["html"])) | {i for group in re.findall(r'data-block-ids="([^"]+)"', out["html"]) for i in group.split()}
    assert set(python.values()) <= rendered


def test_code_comment_is_not_a_backend_heading():
    ids = [block.id for block in markdown_blocks("# Real\n```python\n# comment\n```\n")]
    assert ids == ["real", "real--1", "real--2", "real--3"]
