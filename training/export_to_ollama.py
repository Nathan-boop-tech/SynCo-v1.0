"""Generate a local Ollama Modelfile for a merged Synthra LoRA model."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MERGED_MODEL = "./models/synthra-merged-placeholder"
SYSTEM_PROMPT = """You are Synthra, a specialized local coding assistant.
Inspect the project and detect its language before making changes.
Make a concise plan and ask for approval before writing files or running commands.
Use safe, focused changes, run relevant tests, read errors, and fix mistakes.
Never reveal secrets or claim actions succeeded without evidence.
Adapt to the supplied project examples and knowledge, but do not claim to be more
capable than general frontier models. Explain limitations honestly."""


def generate_modelfile(merged_model: str = DEFAULT_MERGED_MODEL) -> str:
    """Return a Modelfile that refers to an already merged local model directory."""
    base = merged_model.strip()
    if not base or "\n" in base or "\r" in base or '"' in base:
        raise ValueError("Merged model path must be a non-empty single-line path.")
    return (
        f"FROM {base}\n\n"
        f'SYSTEM """\n{SYSTEM_PROMPT}\n"""\n\n'
        "PARAMETER temperature 0.2\n"
        "PARAMETER num_ctx 8192\n"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--merged-model",
        default=DEFAULT_MERGED_MODEL,
        help="path to the merged model directory (replace the placeholder after merging)",
    )
    parser.add_argument("--modelfile", type=Path, default=ROOT / "Modelfile")
    arguments = parser.parse_args(argv)
    content = generate_modelfile(arguments.merged_model)
    arguments.modelfile.write_text(content, encoding="utf-8")
    print(f"Generated {arguments.modelfile}")
    print(
        "\nMerge the trained PEFT adapter into its original base model first. "
        "For example, load AutoModelForCausalLM from BASE_MODEL, wrap it with "
        "PeftModel.from_pretrained(model, 'adapters/synthra-lora'), call "
        "merge_and_unload(), then save_pretrained('./models/synthra-merged'). "
        "Install that merged model in an Ollama-compatible format and replace "
        "the Modelfile FROM placeholder with its local path.\n"
        "Then run: ollama create synthra-custom -f Modelfile\n"
        "Select it with: export SYNTHRA_MODEL=synthra-custom\n"
        "This script only writes the Modelfile; it does not merge weights or run Ollama."
    )


if __name__ == "__main__":
    main()
