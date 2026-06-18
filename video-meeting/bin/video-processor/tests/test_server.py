import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from video_processor.server import create_app


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.video = os.path.join(self.tmp.name, "meeting.mp4")
        with open(self.video, "wb") as fh:
            fh.write(b"0123456789")  # tiny fake media bytes
        self.app = create_app(self.video)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_state_no_frames(self):
        data = self.client.get("/api/state").get_json()
        self.assertTrue(data["has_video"])
        self.assertEqual(data["video_name"], "meeting.mp4")
        self.assertEqual(data["frames"], [])

    def test_save_and_load_roundtrip(self):
        payload = {"frames": [
            {"timestamp_s": 130.5, "label": "b"},
            {"timestamp_s": 70.0, "label": "a"},
        ]}
        resp = self.client.post("/api/frames", json=payload)
        self.assertEqual(resp.status_code, 200)
        fr = resp.get_json()["frames"]
        self.assertEqual([f["timestamp_s"] for f in fr], [70.0, 130.5])
        self.assertEqual(fr[0]["timestamp"], "01:10")
        self.assertEqual(fr[0]["label"], "a")

        fp = os.path.join(self.tmp.name, "meeting-frames.json")
        self.assertTrue(os.path.exists(fp))
        with open(fp) as fh:
            disk = json.load(fh)
        self.assertEqual(disk["video"], "meeting.mp4")
        self.assertEqual(len(disk["frames"]), 2)

        data = self.client.get("/api/state").get_json()
        self.assertEqual(len(data["frames"]), 2)

    def test_load_recomputes_timestamp_s_from_string(self):
        fp = os.path.join(self.tmp.name, "meeting-frames.json")
        with open(fp, "w") as fh:
            json.dump({"video": "meeting.mp4",
                       "frames": [{"timestamp": "01:10", "label": "x"}]}, fh)
        data = self.client.get("/api/state").get_json()
        self.assertEqual(data["frames"][0]["timestamp_s"], 70.0)

    def test_browse_lists_video_and_json_and_dirs(self):
        open(os.path.join(self.tmp.name, "notes.json"), "w").close()
        os.mkdir(os.path.join(self.tmp.name, "sub"))
        data = self.client.get(
            "/api/browse?path=%s" % self.tmp.name).get_json()
        self.assertIn("meeting.mp4", data["files"])
        self.assertIn("notes.json", data["files"])
        self.assertIn("sub", data["dirs"])
        self.assertEqual(data["path"], self.tmp.name)

    def test_browse_bad_path(self):
        resp = self.client.get("/api/browse?path=/no/such/dir/xyz123")
        self.assertEqual(resp.status_code, 400)

    def test_open_switches_video(self):
        other = os.path.join(self.tmp.name, "other.mp4")
        with open(other, "wb") as fh:
            fh.write(b"xx")
        data = self.client.post("/api/open", json={"path": other}).get_json()
        self.assertEqual(data["video_name"], "other.mp4")

    def test_open_missing_path(self):
        resp = self.client.post("/api/open", json={"path": "/nope/x.mp4"})
        self.assertEqual(resp.status_code, 400)

    def test_video_range_returns_206(self):
        resp = self.client.get("/api/video", headers={"Range": "bytes=0-3"})
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp.data, b"0123")

    def test_corrupt_frames_file_degrades_to_empty(self):
        fp = os.path.join(self.tmp.name, "meeting-frames.json")
        with open(fp, "w") as fh:
            fh.write("{ this is not valid json ")
        data = self.client.get("/api/state").get_json()
        self.assertEqual(data["frames"], [])


if __name__ == "__main__":
    unittest.main()
