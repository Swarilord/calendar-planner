"""A local server that accepts connections and never replies: a stand-in for an
overloaded or silent Gemini, so timeout handling is tested without a key."""

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def silent_server() -> Iterator[str]:
    """Yield the server's URL; close it afterwards."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    held: list[object] = []  # keep connections open so the client keeps waiting

    def accept_and_never_reply() -> None:
        try:
            while True:
                held.append(server.accept())
        except OSError:
            pass  # the server was closed

    threading.Thread(target=accept_and_never_reply, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.getsockname()[1]}"
    finally:
        server.close()
