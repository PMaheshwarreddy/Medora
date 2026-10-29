"""Knowledge ingestion: an ETL pipeline where the AI plans and code executes.

  sniff      what format is this file really, and what does a sample look like
  planner    AI reads the sample and returns a declarative Plan (or a verdict
             that the file is junk / not data)
  articles   AI extraction for free-text articles, checked against the text
  records    streams records out of CSV, JSON and OBO files of any size
  transform  applies the Plan to every record: clean, validate, de-duplicate
  load       writes the staged result in one transaction, idempotently
  pipeline   ties it together and keeps the run history

The AI never touches rows of structured files: it sees a sample and decides
the mapping, which is then applied deterministically. That keeps large files
cheap, repeatable and reviewable before anything is written.
"""
