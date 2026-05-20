# Architecture

```text
candidate_profile.json
master_cv.json
master_qa_profile.json
        |
        v
Profile validation
        |
        v
Job intake: paste/file/url/rss/discover/free public APIs + optional free-key APIs
        |
        v
Normalizer: text -> structured JobListing
        |
        v
Fingerprint dedupe
        |
        v
Hard filters
        |
        v
Fit scorer
        |
        v
Packet generator
        |
        v
Markdown/HTML/PDF renderers + artifact hashes
        |
        v
assistant.html for manual final application
        |
        v
SQLite tracker
```

The system is intentionally local-first and manual-submit-only. It automates the safe parts: public job discovery, dedupe, scoring, packet creation, artifact hashing, and local assistant pages. It leaves irreversible submission and any logged-in platform interaction to the user.
