# Android AI-chat system fixture

`fixtures/android-chat.sqlite` is the preserved task database from the Rust prototype. It contains 30 tasks, 64 dependency edges, and 66 indexed text sources for an Android chat app with multiple LLM connections, MCP servers, and internet search.

The task plan is in [android-chat-tasks.json](fixtures/android-chat-tasks.json). Completion states, usage, file references, Git hashes, and results are synthetic test data. No Android app has been implemented by this fixture.

Tests copy the database before opening it. Use a copy for manual queries too:

```sh
cp tests/system/fixtures/android-chat.sqlite /tmp/android-chat-demo.sqlite
echo '{"op":"search_tasks","project_id":"android-ai-chat","mode":"semantic","text":"internet search citations","tag":"search","limit":5}' |
  python3 -m ariadne task --db /tmp/android-chat-demo.sqlite
```

Regenerate a fresh database through the Python APIs:

```sh
python3 -m ariadne seed /tmp/android-chat-new.sqlite
python3 -m unittest tests.system.test_fixture -v
```

The output path must not exist. The seed command uses the checked-in plan by default; `--plan PATH` selects another plan. Generated IDs and timestamps differ between runs.

Vectors use the deterministic `demo-token-hash-v1` embedder. This exercises cosine search, filters, durable jobs, and index consistency; it does not measure the quality of learned semantic retrieval.
