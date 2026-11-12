# Synthra feedback

The feedback commands save one JSON object per line:

- `/good` records the last request and response as approved positive feedback.
- `/bad` asks what was wrong, then records the response and explanation for
  review. Bad examples are not approved for training by default.
- `/save-example` asks for confirmation, saves the last interaction as positive
  feedback, and converts approved feedback into training examples.

The command and `save_training_example.py` write only inside the current
project. Review feedback before using it for any future training workflow.
