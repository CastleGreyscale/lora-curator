"""
Caption analyzer for LoRA training datasets.

Scans every *.txt sidecar caption in <project>/dataset/, strips the trigger
word (first whitespace token, which is how pipeline.py writes captions), and
produces frequency + document-frequency stats for unigrams, bigrams, and
trigrams. Output goes to the project root as caption_analysis.json /
caption_analysis.md so downstream tools (e.g. an LLM prompt-expansion system)
can consume either format.

Post-training only — not invoked from the pipeline.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pipeline

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "in", "on",
    "at", "to", "for", "from", "by", "with", "without", "into", "onto", "over",
    "under", "between", "among", "as", "is", "are", "was", "were", "be", "been",
    "being", "am", "do", "does", "did", "doing", "have", "has", "had", "having",
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "there", "here", "which", "who", "whom", "whose", "what", "when", "where",
    "why", "how", "while", "so", "than", "too", "very", "just", "also", "such",
    "some", "any", "all", "each", "every", "no", "nor", "not", "only", "own",
    "same", "more", "most", "other", "another", "much", "many", "few", "several",
    "one", "two", "three", "both", "either", "neither",
    "he", "she", "his", "her", "him", "hers", "i", "me", "my", "mine", "we",
    "us", "our", "ours", "you", "your", "yours",
    "can", "could", "would", "should", "may", "might", "must", "shall", "will",
    "about", "against", "through", "during", "before", "after", "above", "below",
    "up", "down", "out", "off", "again", "further", "now",
    "appears", "appear", "seems", "seem", "looks", "look", "feels", "feel",
    "image", "scene", "photo", "picture", "shot", "frame", "view",
    "creates", "create", "creating", "providing", "provides", "showing", "shown",
    "features", "featuring", "including", "includes", "evoking", "evokes",
    "overall", "elements", "element", "quality", "qualities",
}

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")


def _read_caption(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _strip_trigger(text: str, trigger_word: str | None) -> str:
    """Drop the trigger word from the start of a caption.

    The pipeline writes captions as "<trigger> <body…>", so the first
    whitespace-separated token is the trigger. We still accept an explicit
    trigger_word and only strip it when it actually matches, to be safe on
    captions that were edited by hand.
    """
    text = text.lstrip()
    if not text:
        return ""
    head, _, rest = text.partition(" " if " " in text else "\t")
    head_norm = head.strip().strip(",.;:").lower()
    if trigger_word and head_norm == trigger_word.strip().lower():
        return rest.lstrip()
    # No explicit trigger given — fall back to dropping the first token
    # only if it looks like a single bare identifier (no spaces, alpha+_-).
    if not trigger_word and re.fullmatch(r"[A-Za-z0-9_\-]+", head_norm or ""):
        return rest.lstrip()
    return text


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in WORD_RE.finditer(text)]


def _ngrams(tokens: list[str], n: int) -> Iterable[tuple[str, ...]]:
    if n <= 0 or len(tokens) < n:
        return ()
    return (tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def _ngram_ok(ng: tuple[str, ...]) -> bool:
    # Drop n-grams that are pure stopword padding or start/end with one.
    if ng[0] in STOPWORDS or ng[-1] in STOPWORDS:
        return False
    if all(t in STOPWORDS for t in ng):
        return False
    return True


def analyze_captions(
    project_dir: str | Path,
    trigger_word: str | None = None,
    top_n: int = 200,
) -> dict:
    """Analyze every caption in <project_dir>/dataset/ and return stats."""
    project_dir = Path(project_dir)
    dataset_dir = project_dir / "dataset"
    if not dataset_dir.exists():
        raise FileNotFoundError(f"dataset dir not found: {dataset_dir}")

    if trigger_word is None:
        try:
            cfg = pipeline._read_toml(project_dir / "project.toml")
            trigger_word = cfg.get("tagging", {}).get("trigger_word", "") or None
        except Exception:
            trigger_word = None

    txts = sorted(dataset_dir.glob("*.txt"))
    if not txts:
        raise FileNotFoundError(f"no .txt captions in {dataset_dir}")

    uni_tf: Counter[str] = Counter()
    bi_tf: Counter[tuple[str, ...]] = Counter()
    tri_tf: Counter[tuple[str, ...]] = Counter()
    uni_df: Counter[str] = Counter()
    bi_df: Counter[tuple[str, ...]] = Counter()
    tri_df: Counter[tuple[str, ...]] = Counter()

    total_tokens = 0
    docs = 0

    for path in txts:
        text = _read_caption(path)
        if not text.strip():
            continue
        text = _strip_trigger(text, trigger_word)
        tokens = _tokenize(text)
        if not tokens:
            continue
        docs += 1
        total_tokens += len(tokens)

        content = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
        uni_tf.update(content)
        uni_df.update(set(content))

        bis = [b for b in _ngrams(tokens, 2) if _ngram_ok(b)]
        tris = [t for t in _ngrams(tokens, 3) if _ngram_ok(t)]
        bi_tf.update(bis)
        tri_tf.update(tris)
        bi_df.update(set(bis))
        tri_df.update(set(tris))

    def _fmt_uni(counter: Counter[str], df: Counter[str]):
        return [
            {"term": term, "count": int(count), "doc_freq": int(df[term])}
            for term, count in counter.most_common(top_n)
        ]

    def _fmt_ngram(counter: Counter[tuple[str, ...]], df: Counter[tuple[str, ...]]):
        return [
            {"term": " ".join(term), "count": int(count), "doc_freq": int(df[term])}
            for term, count in counter.most_common(top_n)
        ]

    return {
        "project_dir": str(project_dir),
        "dataset_dir": str(dataset_dir),
        "trigger_word": trigger_word,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "captions_total": len(txts),
        "captions_analyzed": docs,
        "total_tokens": total_tokens,
        "top_n": top_n,
        "unigrams": _fmt_uni(uni_tf, uni_df),
        "bigrams": _fmt_ngram(bi_tf, bi_df),
        "trigrams": _fmt_ngram(tri_tf, tri_df),
    }


def _md_table(rows: list[dict], docs: int) -> str:
    if not rows:
        return "_none_\n"
    out = ["| Term | Count | Docs | Coverage |", "| --- | ---: | ---: | ---: |"]
    for r in rows:
        pct = (r["doc_freq"] / docs * 100) if docs else 0
        out.append(f"| {r['term']} | {r['count']} | {r['doc_freq']} | {pct:.0f}% |")
    return "\n".join(out) + "\n"


def write_report(project_dir: str | Path, stats: dict, md_top: int = 60) -> dict:
    """Write caption_analysis.json + caption_analysis.md to the project root."""
    project_dir = Path(project_dir)
    json_path = project_dir / "caption_analysis.json"
    md_path = project_dir / "caption_analysis.md"

    json_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    docs = stats["captions_analyzed"]
    lines = [
        f"# Caption analysis — {project_dir.name}",
        "",
        f"- Generated: `{stats['generated_at']}`",
        f"- Trigger word stripped: `{stats['trigger_word'] or '(auto: first token)'}`",
        f"- Captions: **{stats['captions_analyzed']}** analyzed / {stats['captions_total']} total",
        f"- Tokens: **{stats['total_tokens']:,}**",
        "",
        f"Counts sorted by frequency; `Docs` is the number of captions containing the term, "
        f"`Coverage` is `Docs / {docs}`. High-coverage terms are the shared vocabulary across "
        "the dataset — best signal for prompt expansion.",
        "",
        "## Unigrams",
        "",
        _md_table(stats["unigrams"][:md_top], docs),
        "## Bigrams",
        "",
        _md_table(stats["bigrams"][:md_top], docs),
        "## Trigrams",
        "",
        _md_table(stats["trigrams"][:md_top], docs),
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return {"json": str(json_path), "md": str(md_path)}


def analyze_and_write(project_dir: str | Path, trigger_word: str | None = None,
                      top_n: int = 200) -> dict:
    stats = analyze_captions(project_dir, trigger_word=trigger_word, top_n=top_n)
    paths = write_report(project_dir, stats)
    return {"stats": stats, "paths": paths}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Analyze LoRA caption corpus.")
    p.add_argument("project_dir", help="LoRA project root (containing dataset/)")
    p.add_argument("--trigger", default=None, help="Trigger word to strip (default: from project.toml)")
    p.add_argument("--top", type=int, default=200, help="Top-N terms per category")
    args = p.parse_args()
    result = analyze_and_write(args.project_dir, trigger_word=args.trigger, top_n=args.top)
    print(f"Wrote: {result['paths']['json']}")
    print(f"Wrote: {result['paths']['md']}")
    print(f"Captions analyzed: {result['stats']['captions_analyzed']}")
