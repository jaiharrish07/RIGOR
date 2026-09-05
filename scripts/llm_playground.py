"""Experiment with claim extraction on real papers."""
from app.llm.client import get_default_client
from app.ingest.pdf_parser import parse_pdf


def test_claim_extraction(pdf_path: str):
    """Parse a paper, then extract claims from its abstract using the LLM."""
    with open(pdf_path, "rb") as f:
        tei_xml = parse_pdf(f.read())

    from lxml import etree
    root = etree.fromstring(tei_xml.encode("utf-8"))
    TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}
    abstract_el = root.find(".//tei:profileDesc/tei:abstract", TEI_NS)
    abstract = " ".join(t for t in abstract_el.itertext() if t.strip()) if abstract_el is not None else ""

    if not abstract:
        print("No abstract found")
        return

    print("Abstract found:", abstract[:200], "...\n")

    client = get_default_client()

    system = """You extract quantitative performance claims from ML paper abstracts.
You MUST NOT invent claims. Every claim must have a verbatim evidence quote from the text."""

    user = f"Abstract:\n{abstract}\n\nExtract every quantitative claim about model performance."

    tool_schema = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "metric_name": {"type": "string"},
                        "value": {"type": "string"},
                        "dataset": {"type": "string"},
                        "evidence_quote": {"type": "string"},
                    },
                    "required": ["metric_name", "value", "dataset", "evidence_quote"],
                },
            }
        },
        "required": ["claims"],
    }

    result = client.call_structured(
        system=system,
        user=user,
        tool_name="extract_claims",
        tool_schema=tool_schema,
    )

    print(f"\nFound {len(result['claims'])} claims:")
    for c in result["claims"]:
        print(f"  - {c['metric_name']} = {c['value']} on {c['dataset']}")
        print(f"    Quote: \"{c['evidence_quote']}\"")


if __name__ == "__main__":
    import sys
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "demo_papers/demo_01_gold_transformer.pdf"
    test_claim_extraction(pdf_path)