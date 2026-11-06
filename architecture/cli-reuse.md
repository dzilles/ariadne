# Reusing the terminal interface

The next frontend will reuse the Textual CLI/TUI from [dzilles/ariadne on main](https://github.com/dzilles/ariadne/tree/main/src/ariadne/ui).

The initial inspection used the local checkout's cached `origin/main` at `e093e5143fb493afbeda19c50baf2d40ba2f1efb`. Refresh from GitHub before importing the interface; the current remote revision could not be verified from this environment. The older local checkout has additional commits and uncommitted changes, which were left untouched.

Reuse the chat layout, message rendering, multiline input, input history, command suggestions, and keyboard bindings from `src/ariadne/ui/`. Connect them to the new backend through a small adapter:

| UI action or display | New backend API |
| --- | --- |
| Start or restore a session | `Application.create_conversation()` / `conversation(id)` |
| Send a message | `app.submit(session_id, {"type": "send_message", "text": ...})` |
| Display replies and activity | Subscribe to `app.interface` and consume its structured events. |
| Escape / cancel | Submit `cancel_run` with the active run ID. |
| Restore chat history | Load the saved conversation's public `view()`. |
| Display task facts | Read current task records; keep automatic recording in backend modules. |
| Exit | Close the subscription and application. |

The old launcher and agent adapters depend on its previous agents, runtime, LangGraph, configuration, and per-agent history. Replace those connections with the application adapter. Keep conversation persistence in the new orchestrator store and configuration in the configuration module.

Start with orchestrator chat. Add worker selection and approval dialogs when their backend handlers exist. Keep Textual dependencies in an optional frontend installation extra so the headless modules remain usable independently.

Import and adapt the interface after publishing the Python foundation on `development`. Verify message streaming, cancellation, reconnecting to a saved conversation, and keyboard behavior with Textual's headless test support.
