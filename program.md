# Research Lab Program

This file is the human-authored policy for literature search runs.

## Goal

Find the most relevant papers and articles for a research topic, given the user's current notes.

## Retrieval policy

1. Prefer structured scholarly sources before broad web search.
2. Favor papers with abstracts, stable identifiers, and enough metadata to judge relevance.
3. Use broad web results as supporting material when they strengthen an argument or point to non-indexed work.
4. Expand from the strongest early matches instead of blasting many weak queries.

## Ranking policy

Score candidates on:

- direct relevance to the topic
- overlap with the user's current direction
- whether the title actually matches the core claim, not just the abstract
- citations and venue quality as weak authority signals
- recency as a secondary signal
- whether the result appears in more than one source
- whether fetched full text contains evidence that helps the user's argument

Do not let citation count dominate topic relevance.

## Iteration policy

1. Start with topic-driven queries.
2. Rerank the initial pool.
3. Expand once or twice from the strongest papers using title terms, authors, and references.
4. Stop when later iterations mostly repeat what is already known.

## Output policy

The final report should contain:

- top matches with short reasons
- lower-confidence but interesting leads
- search queries that were tried
- gaps or subtopics that still look underexplored
