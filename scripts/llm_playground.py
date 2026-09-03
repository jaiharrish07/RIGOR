"""Experiment with the LLM client. Run this to test that Groq works."""
from app.llm.client import get_default_client


def test_simple_call():
    """Ask the LLM to extract a fact from a short text."""
    client = get_default_client()

    system = "You extract structured facts from short text passages."
    user = """
    Text: "In our experiments, we used a learning rate of 3e-4 with the Adam
    optimizer and trained for 100 epochs on a batch size of 64."

    Extract the hyperparameters mentioned.
    """

    tool_schema = {
        "type": "object",
        "properties": {
            "learning_rate": {"type": "string"},
            "optimizer": {"type": "string"},
            "epochs": {"type": "integer"},
            "batch_size": {"type": "integer"},
        },
        "required": ["learning_rate", "optimizer", "epochs", "batch_size"],
    }

    result = client.call_structured(
        system=system,
        user=user,
        tool_name="extract_hyperparameters",
        tool_schema=tool_schema,
    )
    print("Extracted:", result)


if __name__ == "__main__":
    test_simple_call()