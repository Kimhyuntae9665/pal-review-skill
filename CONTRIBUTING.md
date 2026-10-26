# Contributing

Keep changes focused on a checkable review → critique → verification workflow.
Do not add automatic paid fallbacks, account rotation, unbounded retries, or
claims that agreement between models proves correctness.

1. Bootstrap the pinned runtime with `python scripts/bootstrap.py`.
2. Use synthetic fixtures and mocked HTTP for development.
3. Run the test suite with the repository's managed Python:

   ```powershell
   & ./.runtime/venv/Scripts/python.exe -m unittest discover -s tests -v
   ```

4. Update the relevant docs when changing setup, models, output contracts or limits.
5. Before a commit, inspect `git diff --cached` for secrets, personal paths,
   account identifiers and private review artifacts. Runtime files and local
   credentials must remain ignored.

Document authenticated model tests separately from offline tests. A real API
response proves that particular request path worked; it is not an accuracy
benchmark or a future availability promise. Do not add provider secrets to CI.

Original contributions are provided under this repository's Apache-2.0 license.
