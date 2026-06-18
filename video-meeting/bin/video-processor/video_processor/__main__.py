"""CLI entry: parse optional video path, find a free port, launch, open browser."""
import argparse
import os
import socket
import threading
import webbrowser

from .server import create_app


def find_free_port(start=8000, end=8100):
    """Return the first bindable port on 127.0.0.1 in [start, end)."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port in range %d-%d" % (start, end))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="video-processor",
        description="Mark, label, and re-seek frames in a meeting video.")
    parser.add_argument("video", nargs="?",
                        help="path to a video file to open on launch")
    args = parser.parse_args(argv)

    video_path = os.path.abspath(args.video) if args.video else None
    app = create_app(video_path)
    port = find_free_port()
    url = "http://127.0.0.1:%d/" % port
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print("video-processor running at %s  (Ctrl-C to stop)" % url)
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
