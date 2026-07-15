# arXiv submission checklist

1. Upload `arxiv_source.zip`; arXiv should select `main.tex` as the top-level file.
2. Primary category: `q-fin.TR`. Suggested cross-list: `cs.PF`.
3. Copy the ASCII-only title, author, abstract, and comments from `metadata.txt`.
4. Select the license yourself during submission. This package does not make that legal choice.
5. Confirm that `Godzilla Foundation` is a current and accurate affiliation before submission.
6. Preview the arXiv-generated PDF and compare it with `main.pdf`.
7. Before a later revision, correct the repository inconsistency between the 50,000 ns and 100,000 ns spin settings.
8. For a materially stronger v2, add strict causal event IDs, at least 30 measured repetitions, longer and burst workloads, complete compiler/CPU configuration, and an immutable artifact DOI.

The source archive intentionally uses standard pdfLaTeX-compatible packages and includes all figures. No XeLaTeX, shell escape, external fonts, or omitted figure dependencies are required.
