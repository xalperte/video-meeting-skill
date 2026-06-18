"use strict";

// --- timecode twin of video_processor/timecode.py ---
function parseTimecode(value) {
  let s = String(value).trim();
  if (!s) throw new Error("empty");
  if (s.toLowerCase().startsWith("sec")) {
    s = s.slice(3).trim();
    if (!s) throw new Error("empty");
  }
  const parts = s.split(":");
  if (parts.length > 3) throw new Error("too many ':'");
  const DECIMAL = /^[+-]?(\d+\.?\d*|\.\d+)$/;  // plain decimal only, like Python float()
  const nums = parts.map((p) => {
    const t = p.trim();
    if (!DECIMAL.test(t)) throw new Error("non-numeric");
    return Number(t);
  });
  if (nums.some((n) => n < 0)) throw new Error("negative");
  if (nums.length === 1) return nums[0];
  if (nums.length === 2) return nums[0] * 60 + nums[1];
  return nums[0] * 3600 + nums[1] * 60 + nums[2];
}

function formatTimecode(seconds) {
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

// --- state ---
let frames = [];

const video = document.getElementById("video");
const framesList = document.getElementById("frames-list");
const timeReadout = document.getElementById("time-readout");
const gotoError = document.getElementById("goto-error");
const saveStatus = document.getElementById("save-status");
const modal = document.getElementById("browse-modal");
const browseList = document.getElementById("browse-list");
const browsePath = document.getElementById("browse-path");

function renderFrames() {
  frames.sort((a, b) => a.timestamp_s - b.timestamp_s);
  framesList.innerHTML = "";
  frames.forEach((fr, idx) => {
    const li = document.createElement("li");

    const t = document.createElement("button");
    t.className = "frame-time";
    t.type = "button";
    t.textContent = formatTimecode(fr.timestamp_s);
    t.addEventListener("click", () => { video.currentTime = fr.timestamp_s; });

    const label = document.createElement("input");
    label.className = "frame-label";
    label.type = "text";
    label.value = fr.label || "";
    label.placeholder = "label…";
    label.addEventListener("input", () => { frames[idx].label = label.value; });

    const del = document.createElement("button");
    del.className = "frame-del";
    del.type = "button";
    del.textContent = "✕";
    del.addEventListener("click", () => { frames.splice(idx, 1); renderFrames(); });

    li.append(t, label, del);
    framesList.appendChild(li);
  });
}

function addFrame(seconds) {
  frames.push({ timestamp_s: seconds, timestamp: formatTimecode(seconds), label: "" });
  renderFrames();
}

video.addEventListener("timeupdate", () => {
  timeReadout.textContent =
    `${formatTimecode(video.currentTime)} (sec ${Math.floor(video.currentTime)})`;
});
video.addEventListener("click", () => {
  if (video.src) addFrame(video.currentTime);
});

document.getElementById("mark-btn").addEventListener("click", () => {
  if (video.src) addFrame(video.currentTime);
});

document.getElementById("goto-form").addEventListener("submit", (e) => {
  e.preventDefault();
  gotoError.textContent = "";
  try {
    video.currentTime = parseTimecode(document.getElementById("goto-input").value);
  } catch (err) {
    gotoError.textContent = "Invalid time";
  }
});

document.getElementById("save-btn").addEventListener("click", async () => {
  saveStatus.textContent = "Saving…";
  try {
    const resp = await fetch("/api/frames", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ frames }),
    });
    if (!resp.ok) throw new Error("save failed");
    const data = await resp.json();
    frames = data.frames;
    renderFrames();
    saveStatus.textContent = "Saved";
  } catch (err) {
    saveStatus.textContent = "Save failed";
  }
});

async function loadState() {
  const data = await (await fetch("/api/state")).json();
  document.getElementById("video-name").textContent =
    data.has_video ? data.video_name : "No video loaded";
  if (data.has_video) video.src = "/api/video?ts=" + Date.now();
  frames = data.frames || [];
  renderFrames();
}

// --- browse / open ---
async function browse(path) {
  const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : "/api/browse";
  const data = await (await fetch(url)).json();
  if (data.error) return;
  browsePath.textContent = data.path;
  browseList.innerHTML = "";

  const up = document.createElement("li");
  up.textContent = ".. (up)";
  up.className = "dir";
  up.addEventListener("click", () => browse(data.parent));
  browseList.appendChild(up);

  data.dirs.forEach((d) => {
    const li = document.createElement("li");
    li.textContent = d + "/";
    li.className = "dir";
    li.addEventListener("click", () => browse(data.path + "/" + d));
    browseList.appendChild(li);
  });
  data.files.forEach((f) => {
    const li = document.createElement("li");
    li.textContent = f;
    li.className = "file";
    li.addEventListener("click", () => openVideo(data.path + "/" + f));
    browseList.appendChild(li);
  });
}

async function openVideo(path) {
  if (!/\.(mp4|mkv|mov|avi|webm|m4v)$/i.test(path)) return; // only videos open
  const resp = await fetch("/api/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (resp.ok) {
    modal.classList.add("hidden");
    await loadState();
  }
}

document.getElementById("open-btn").addEventListener("click", () => {
  modal.classList.remove("hidden");
  browse(null);
});
document.getElementById("browse-close").addEventListener("click",
  () => modal.classList.add("hidden"));

loadState();
