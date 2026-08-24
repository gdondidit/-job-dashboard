"""
Job scraper — pulls listings from Indeed, LinkedIn, ZipRecruiter, Glassdoor,
and Google Jobs using the JobSpy library, then saves everything to
docs/jobs.json for the dashboard to read.

This script is meant to be run automatically by GitHub Actions on a
schedule. It deliberately casts a fairly WIDE net (broad search terms,
generous results_wanted) because the dashboard itself does the fine-grained
filtering — that way you never have to edit this file to change what you
see, you just adjust filters in the webpage.
"""

import json
import time
import random
import datetime
from jobspy import scrape_jobs

# Category: Implementation & Onboarding (SaaS, healthcare, fintech, and general).
# Feel free to add more terms here later — each one runs as its own search.
SEARCH_TERMS = [
    "implementation",
    "onboarding",
    "client onboarding specialist",
    "customer onboarding specialist",
    "senior onboarding specialist",
    "implementation specialist",
    "implementation consultant",
    "healthcare implementation consultant",
    "EMR implementation specialist",
    "EHR implementation specialist",
    "clinical systems analyst",
    "health information management analyst",
    "customer training specialist",
    "escalation specialist",
    "deployment specialist",
    "rollout specialist",
]

SITES = ["indeed", "linkedin", "zip_recruiter", "glassdoor", "google"]

RESULTS_PER_SEARCH = 40  # per term, per site (JobSpy dedupes internally per call)
MAX_RETRIES = 2
BASE_DELAY_SECONDS = 8  # delay between search terms, helps avoid rate limiting/blocking

# Phrases that signal a degree is a hard requirement vs. just preferred/nice-to-have.
# Order matters: "required" patterns are checked first since a posting can contain
# both a "preferred" phrase elsewhere (e.g. "MBA preferred") alongside a hard requirement.
REQUIRED_PATTERNS = [
    "bachelor's degree required",
    "bachelor degree required",
    "requires a bachelor",
    "must have a bachelor",
    "minimum of a bachelor",
    "bachelor's degree is required",
    "4-year degree required",
    "four-year degree required",
]
PREFERRED_PATTERNS = [
    "bachelor's degree preferred",
    "bachelor degree preferred",
    "bachelor's preferred",
    "degree preferred",
    "or equivalent experience",
    "or equivalent work experience",
]
MENTIONED_PATTERNS = [
    "bachelor's degree",
    "bachelor degree",
    "b.a.",
    "b.s.",
    "college degree",
    "4-year degree",
    "four-year degree",
]


def classify_degree_requirement(description: str) -> str:
    """Scan a job description and return one of:
    'Not mentioned', 'Degree preferred', 'Degree required', 'Unknown' (no description available)
    This is a simple keyword scan, not a guarantee — always read the actual posting.
    """
    if not description:
        return "Unknown"
    text = description.lower()

    if any(p in text for p in REQUIRED_PATTERNS):
        return "Degree required"
    if any(p in text for p in PREFERRED_PATTERNS):
        return "Degree preferred"
    if any(p in text for p in MENTIONED_PATTERNS):
        # Degree is mentioned but without clear required/preferred language —
        # safest to treat as "preferred" rather than assume it's a hard requirement.
        return "Degree preferred"
    return "Not mentioned"


def run():
    all_jobs = []
    run_log = []  # per-term result counts, so failures are visible instead of silent

    for i, term in enumerate(SEARCH_TERMS):
        print(f"[{i+1}/{len(SEARCH_TERMS)}] Searching: {term}")
        term_result = {"term": term, "count": 0, "error": None}

        for attempt in range(1, MAX_RETRIES + 2):  # e.g. 1 initial + 2 retries = 3 tries
            try:
                jobs = scrape_jobs(
                    site_name=SITES,
                    search_term=term,
                    google_search_term=f"{term} jobs remote",
                    location="United States",
                    results_wanted=RESULTS_PER_SEARCH,
                    hours_old=72,  # only recent postings
                    is_remote=True,
                    country_indeed="USA",
                )
                count = len(jobs) if jobs is not None else 0
                print(f"    -> {count} results (attempt {attempt})")
                if jobs is not None and count > 0:
                    all_jobs.append(jobs)
                term_result["count"] = count
                break  # success (even if 0 results, that's a real answer, not an error)
            except Exception as e:
                print(f"    !! attempt {attempt} failed: {e}")
                term_result["error"] = str(e)
                if attempt <= MAX_RETRIES:
                    backoff = BASE_DELAY_SECONDS * attempt
                    print(f"    retrying in {backoff}s...")
                    time.sleep(backoff)

        run_log.append(term_result)
        # Small randomized delay between terms to reduce chances of being rate-limited/blocked
        time.sleep(BASE_DELAY_SECONDS + random.uniform(0, 4))

    if not all_jobs:
        print("No jobs found this run.")
        combined = []
    else:
        import pandas as pd

        df = pd.concat(all_jobs, ignore_index=True)
        # De-duplicate on job_url (same job can appear across search terms)
        df = df.drop_duplicates(subset=["job_url"])
        df = df.where(pd.notnull(df), None)
        combined = df.to_dict(orient="records")

    for job in combined:
        job["degree_requirement"] = classify_degree_requirement(job.get("description"))

    output = {
        "last_updated": datetime.datetime.utcnow().isoformat() + "Z",
        "count": len(combined),
        "jobs": combined,
    }

    with open("docs/jobs.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    # Diagnostic file: shows per-term result counts and any errors, so if the
    # dashboard ever shows 0 jobs again, this file explains exactly why.
    with open("docs/run_log.json", "w") as f:
        json.dump(
            {
                "last_run": output["last_updated"],
                "total_jobs_saved": len(combined),
                "per_term_results": run_log,
            },
            f,
            indent=2,
        )

    print(f"Saved {len(combined)} jobs to docs/jobs.json")
    zero_result_terms = [r["term"] for r in run_log if r["count"] == 0]
    if zero_result_terms:
        print(f"NOTE: these terms returned 0 results this run: {zero_result_terms}")


if __name__ == "__main__":
    run()
