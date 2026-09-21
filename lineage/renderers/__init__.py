"""Renderers — the seam the assignment asks about, shipped rather than described.

THE CLAIM: "a PPT or a PDF is a natural next step, not a rewrite"
    A claim like that is worth nothing as a paragraph, so this package makes it checkable. A
    renderer is ONE function:

        render(answers: list[Answer], **opts) -> str | bytes

    It receives finished Answer objects — the claim, the executed rows, the cell provenance,
    the abstention if there was one — and it may not compute anything. There is no query, no
    store and no model behind this line: everything a renderer could need has already been
    computed and verified.

    ⇒ Adding a deck generator is adding ONE FILE to this directory. It is not a rewrite
      because the pipeline does not know renderers exist: `pipeline.answer()` returns Answers
      and stops. Two renderers are shipped (text, markdown) so the seam is exercised by more
      than one consumer, which is the only way to know a seam is real. `slides.py` is a third:
      it builds the full deck STRUCTURE — one slide per answer, with title, bullets, table and
      a sources footnote — and stops one call short of python-pptx, so the remaining work is
      visible and small rather than asserted to be.

    ⛔ The rule that keeps it true: a renderer that needs a number the Answer does not carry
      must extend the PIPELINE, never reach past it. The moment a renderer opens the store,
      the seam is gone and the next output format is a rewrite again.
"""
from .text import render as render_text
from .markdown import render as render_markdown
from .slides import render as render_slides

REGISTRY = {
    "text": render_text,
    "markdown": render_markdown,
    "slides": render_slides,
}

__all__ = ["render_text", "render_markdown", "render_slides", "REGISTRY"]
