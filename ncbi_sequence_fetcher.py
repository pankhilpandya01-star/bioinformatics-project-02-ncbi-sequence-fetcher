"""Download one nucleotide or protein sequence from NCBI.

This project uses only modules included with Python. The functions are kept
small and commented so that each step of an NCBI E-utilities request is easy
to follow.
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


# NCBI asks programs using E-utilities to send a tool name and user email.
TOOL_NAME = "beginner_ncbi_sequence_fetcher"
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MAX_ATTEMPTS = 3


def choose_database(choice):
    """Convert the user's menu choice into an NCBI database name."""
    if choice == "1":
        return "nuccore", "Nucleotide"
    if choice == "2":
        return "protein", "Protein"
    return None, None


def valid_accession(accession):
    """Check for an accession containing letters, numbers, and a version."""
    pattern = r"^[A-Za-z][A-Za-z0-9_]*[0-9]+\.[0-9]+$"
    return re.fullmatch(pattern, accession) is not None


def valid_email(email):
    """Perform a small, beginner-friendly email format check."""
    return (
        email.count("@") == 1
        and "." in email.split("@")[-1]
        and " " not in email
        and not email.startswith("@")
        and not email.endswith("@")
    )


def build_url(endpoint, parameters):
    """Build an E-utilities URL while safely encoding its parameters."""
    return f"{EUTILS_BASE}/{endpoint}?{urlencode(parameters)}"


def download_text(url, description):
    """Download text, retrying temporary NCBI or connection problems."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urlopen(url, timeout=20) as response:
                return response.read().decode("utf-8")

        except HTTPError as error:
            # Status 429 means too many requests. Status 500 to 599 means
            # the server has a temporary problem.
            temporary_error = error.code == 429 or 500 <= error.code <= 599

            if not temporary_error:
                print(f"NCBI could not find the requested {description}.")
                return None

            if attempt == MAX_ATTEMPTS:
                print(f"NCBI is temporarily unable to provide the {description}.")
                return None

        except (URLError, TimeoutError):
            if attempt == MAX_ATTEMPTS:
                print("Unable to connect to NCBI. Check your internet connection.")
                return None

        # Wait longer before each retry so repeated requests remain polite.
        wait_seconds = attempt * 2
        print(f"Temporary connection problem. Retrying in {wait_seconds} seconds...")
        time.sleep(wait_seconds)

    return None


def parse_metadata(xml_text):
    """Extract a few useful fields from an NCBI GenBank XML record."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    record = root.find(".//GBSeq")
    if record is None:
        return None

    def field(name, default="Not available"):
        element = record.find(name)
        if element is not None and element.text:
            return element.text.strip()
        return default

    return {
        "accession": field("GBSeq_accession-version"),
        "title": field("GBSeq_definition"),
        "organism": field("GBSeq_organism"),
        "length": field("GBSeq_length"),
        "updated": field("GBSeq_update-date"),
    }


def valid_fasta(fasta_text):
    """Confirm that the downloaded text looks like a FASTA record."""
    lines = [line.strip() for line in fasta_text.splitlines() if line.strip()]
    return len(lines) >= 2 and lines[0].startswith(">")


def source_url(database, accession):
    """Create a public NCBI record link that does not contain the user's email."""
    page = "nuccore" if database == "nuccore" else "protein"
    return f"https://www.ncbi.nlm.nih.gov/{page}/{accession}"


def output_paths(accession):
    """Return the two filenames used for a downloaded record."""
    return Path(f"{accession}.fasta"), Path(f"{accession}_metadata.txt")


def permission_to_overwrite(paths):
    """Ask before replacing output files that already exist."""
    existing = [path.name for path in paths if path.exists()]
    if not existing:
        return True

    print("\nThe following output file(s) already exist:")
    for filename in existing:
        print(f"- {filename}")

    answer = input("Replace them? (yes/no): ").strip().lower()
    return answer in ("yes", "y")


def format_metadata(metadata, database_label, retrieved, record_url):
    """Create the plain-text metadata report saved beside the FASTA file."""
    return (
        "NCBI Sequence Fetcher Metadata\n"
        "==============================\n"
        f"Database: {database_label}\n"
        f"Accession: {metadata['accession']}\n"
        f"Title: {metadata['title']}\n"
        f"Organism: {metadata['organism']}\n"
        f"Sequence length: {metadata['length']}\n"
        f"NCBI record updated: {metadata['updated']}\n"
        f"Retrieved (UTC): {retrieved}\n"
        f"Source: {record_url}\n"
    )


def save_outputs(fasta_path, metadata_path, fasta_text, metadata_text):
    """Save validated FASTA and metadata text to the current folder."""
    try:
        fasta_path.write_text(fasta_text.rstrip() + "\n", encoding="utf-8")
        metadata_path.write_text(metadata_text, encoding="utf-8")
        return True
    except OSError:
        print("The output files could not be saved. Check folder permissions.")
        return False


def main():
    """Collect input, contact NCBI, show metadata, and save both files."""
    print("====================================")
    print("       NCBI Sequence Fetcher")
    print("====================================")
    print("1. Nucleotide sequence")
    print("2. Protein sequence")

    choice = input("\nChoose a database (1 or 2): ").strip()
    database, database_label = choose_database(choice)
    if database is None:
        print("Invalid choice. Enter 1 for nucleotide or 2 for protein.")
        return

    accession = input("Enter an accession with its version: ").strip().upper()
    if not accession:
        print("An accession number is required.")
        return
    if not valid_accession(accession):
        print("Invalid accession format. Example: J01859.1 or NP_000537.3")
        return

    # NCBI recommends identifying E-utilities requests with the user's email.
    # The address is used only to build the request and is never written to a file.
    email = input("Enter your email for NCBI (not saved): ").strip()
    if not valid_email(email):
        print("Enter a valid email address. It will not be saved.")
        return

    common_parameters = {
        "db": database,
        "id": accession,
        "tool": TOOL_NAME,
        "email": email,
    }

    # GenBank XML contains consistent metadata fields for both databases.
    metadata_parameters = common_parameters.copy()
    metadata_parameters["rettype"] = "gb" if database == "nuccore" else "gp"
    metadata_parameters["retmode"] = "xml"
    metadata_url = build_url("efetch.fcgi", metadata_parameters)

    print("\nRetrieving metadata from NCBI...")
    metadata_xml = download_text(metadata_url, "metadata record")
    if metadata_xml is None:
        return

    metadata = parse_metadata(metadata_xml)
    if metadata is None or metadata["accession"] == "Not available":
        print("No matching record was found in the selected database.")
        return

    # Use the accession returned by NCBI so the exact record version is kept.
    exact_accession = metadata["accession"]
    fasta_path, metadata_path = output_paths(exact_accession)
    if not permission_to_overwrite((fasta_path, metadata_path)):
        print("Download cancelled. Existing files were not changed.")
        return

    # Wait between the metadata and FASTA requests to respect NCBI limits.
    time.sleep(0.5)

    fasta_parameters = common_parameters.copy()
    fasta_parameters["rettype"] = "fasta"
    fasta_parameters["retmode"] = "text"
    fasta_url = build_url("efetch.fcgi", fasta_parameters)

    print("Retrieving the FASTA sequence...")
    fasta_text = download_text(fasta_url, "FASTA sequence")
    if fasta_text is None:
        return
    if not valid_fasta(fasta_text):
        print("NCBI returned an unexpected response instead of FASTA data.")
        return

    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    record_url = source_url(database, exact_accession)
    metadata_text = format_metadata(
        metadata, database_label, retrieved, record_url
    )

    if not save_outputs(
        fasta_path, metadata_path, fasta_text, metadata_text
    ):
        return

    print("\nRecord retrieved successfully")
    print("-----------------------------")
    print(f"Database: {database_label}")
    print(f"Accession: {exact_accession}")
    print(f"Title: {metadata['title']}")
    print(f"Organism: {metadata['organism']}")
    print(f"Sequence length: {metadata['length']}")
    print(f"Retrieved (UTC): {retrieved}")
    print(f"Source: {record_url}")
    print(f"\nFASTA saved as: {fasta_path.name}")
    print(f"Metadata saved as: {metadata_path.name}")


if __name__ == "__main__":
    main()
