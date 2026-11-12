"""Opt-in local LoRA fine-tuning with Hugging Face TRL and PEFT."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

if __package__:
    from . import prepare_dataset as dataset_utils
else:
    import prepare_dataset as dataset_utils

DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"


def _configured_path(variable: str, default: str) -> Path:
    value = os.environ.get(variable, default)
    path = Path(value)
    return path if path.is_absolute() else dataset_utils.ROOT / path


def training_settings() -> dict[str, Any]:
    """Read and validate supported trainer settings from the environment."""
    settings: dict[str, Any] = {
        "base_model": os.environ.get("BASE_MODEL", DEFAULT_BASE_MODEL),
        "train_file": _configured_path("TRAIN_FILE", "training/train.jsonl"),
        "validation_file": _configured_path(
            "VALIDATION_FILE", "training/validation.jsonl"
        ),
        "output_dir": _configured_path("OUTPUT_DIR", "adapters/synthra-lora"),
        "max_steps": int(os.environ.get("MAX_STEPS", "100")),
        "learning_rate": float(os.environ.get("LEARNING_RATE", "0.0002")),
        "batch_size": int(os.environ.get("BATCH_SIZE", "1")),
        "lora_rank": int(os.environ.get("LORA_RANK", "8")),
        "lora_alpha": int(os.environ.get("LORA_ALPHA", "16")),
        "lora_dropout": float(os.environ.get("LORA_DROPOUT", "0.05")),
    }
    if not settings["base_model"].strip():
        raise ValueError("BASE_MODEL must not be empty.")
    if settings["max_steps"] < 1:
        raise ValueError("MAX_STEPS must be at least 1.")
    if settings["learning_rate"] <= 0:
        raise ValueError("LEARNING_RATE must be greater than 0.")
    if settings["batch_size"] < 1:
        raise ValueError("BATCH_SIZE must be at least 1.")
    if settings["lora_rank"] < 1 or settings["lora_alpha"] < 1:
        raise ValueError("LORA_RANK and LORA_ALPHA must be at least 1.")
    if not 0 <= settings["lora_dropout"] < 1:
        raise ValueError("LORA_DROPOUT must be in the range [0, 1).")
    return settings


def _load_validated(path: Path, label: str) -> list[dict[str, str]]:
    records = dataset_utils.read_jsonl(path)
    if not records:
        raise ValueError(f"{label} dataset is empty: {path}")
    validated: list[dict[str, str]] = []
    for index, record in enumerate(records, start=1):
        if not dataset_utils.validate_example(record):
            raise ValueError(
                f"{label} example {index} must have non-empty instruction, input, and output strings."
            )
        if dataset_utils.contains_obvious_secret(json.dumps(record, ensure_ascii=False)):
            raise ValueError(f"{label} example {index} contains a recognizable secret.")
        example = {
            key: record[key].strip() for key in ("instruction", "input", "output")
        }
        validated.append(example)
    return validated


def _format_example(example: dict[str, str]) -> str:
    return (
        "### Instruction:\n"
        f"{example['instruction']}\n\n"
        "### Input:\n"
        f"{example['input']}\n\n"
        "### Response:\n"
        f"{example['output']}"
    )


def run_training(dry_run: bool = False) -> dict[str, Any]:
    """Validate training data and optionally run a local SFT LoRA job."""
    settings = training_settings()
    train_records = _load_validated(settings["train_file"], "Training")
    validation_records = _load_validated(settings["validation_file"], "Validation")
    summary = {
        "base_model": settings["base_model"],
        "training_examples": len(train_records),
        "validation_examples": len(validation_records),
        "max_steps": settings["max_steps"],
        "learning_rate": settings["learning_rate"],
        "batch_size": settings["batch_size"],
        "output_dir": str(settings["output_dir"]),
    }
    if dry_run:
        print("Dry run: dataset validated; no model was downloaded and no training was run.")
        print(f"Base model: {summary['base_model']}")
        print(f"Training examples: {summary['training_examples']}")
        print(f"Validation examples: {summary['validation_examples']}")
        print(f"Estimated settings: max_steps={summary['max_steps']}, "
              f"learning_rate={summary['learning_rate']}, batch_size={summary['batch_size']}")
        print(f"Adapter output: {summary['output_dir']}")
        return summary

    try:
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as error:
        raise RuntimeError(
            "Training dependencies are missing. Install the optional packages with "
            "`python -m pip install -r training/requirements.txt`."
        ) from error

    output_dir: Path = settings["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "training.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), file_handler],
        force=True,
    )
    logger = logging.getLogger("synthra.training")
    logger.info("Starting LoRA training for %s", settings["base_model"])
    logger.info("Dataset sizes: train=%d validation=%d", len(train_records), len(validation_records))

    tokenizer = AutoTokenizer.from_pretrained(
        settings["base_model"], trust_remote_code=False
    )
    model = AutoModelForCausalLM.from_pretrained(
        settings["base_model"], trust_remote_code=False
    )
    train_dataset = Dataset.from_list(
        [{"text": _format_example(item)} for item in train_records]
    )
    validation_dataset = Dataset.from_list(
        [{"text": _format_example(item)} for item in validation_records]
    )
    save_steps = min(50, settings["max_steps"])
    trainer = SFTTrainer(
        model=model,
        args=SFTConfig(
            output_dir=str(output_dir),
            learning_rate=settings["learning_rate"],
            per_device_train_batch_size=settings["batch_size"],
            per_device_eval_batch_size=settings["batch_size"],
            max_steps=settings["max_steps"],
            logging_steps=1,
            eval_strategy="steps",
            eval_steps=save_steps,
            save_strategy="steps",
            save_steps=save_steps,
            save_total_limit=2,
            dataset_text_field="text",
            max_length=1024,
            report_to=[],
        ),
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        peft_config=LoraConfig(
            r=settings["lora_rank"],
            lora_alpha=settings["lora_alpha"],
            lora_dropout=settings["lora_dropout"],
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            task_type="CAUSAL_LM",
        ),
        processing_class=tokenizer,
    )
    result = trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(output_dir)
    logger.info("Training finished: %s", result.metrics)
    logger.info("Saved adapter and training log under %s", output_dir)
    file_handler.close()
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate datasets and display settings without downloading or training a model",
    )
    arguments = parser.parse_args(argv)
    try:
        run_training(dry_run=arguments.dry_run)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"Training setup failed: {error}\n")


if __name__ == "__main__":
    main()
