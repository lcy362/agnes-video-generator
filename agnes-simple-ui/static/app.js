// agnes-simple-ui frontend logic.
// Talks directly to the Agnes backend (AGNES_BASE) for everything except
// cover text compositing, which is this project's own /api/cover/compose.

const AGNES_BASE = "http://localhost:8765";

const state = {
  lang: "ar",
  mode: "script",
  voiceCatalog: null, // full /api/voices response, cached
  manuscriptParagraphCount: 0,
  sceneCount: 5,
  sceneDurations: [8, 8, 8, 8, 8],
  polling: null,
  narrationShown: false,
  lastCoverImageBlob: null,
  currentTaskId: null,
  currentVideoPath: null,
  currentProjectId: null,
};

const $ = (id) => document.getElementById(id);

// ---------- Language & mode toggles ----------

function setLang(lang) {
  state.lang = lang;
  document.querySelectorAll("#lang-toggle button").forEach((b) => {
    b.classList.toggle("active", b.dataset.lang === lang);
  });
  const rtl = lang === "ar";
  $("manuscript-text").dir = rtl ? "rtl" : "ltr";
  $("topic-idea").dir = rtl ? "rtl" : "ltr";
  $("manuscript-text").placeholder = rtl ? "اكتب أو الصق النص الكامل هنا…" : "Paste your full script here…";
  $("topic-idea").placeholder = rtl ? "اكتب فكرتك هنا…" : "Type your topic here…";
  $("cover-title").placeholder = rtl ? "عنوان الفيديو" : "Video title";
  $("cover-title").dir = rtl ? "rtl" : "ltr";
  renderVoiceOptions();
  invalidateGenerate();
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll("#mode-toggle button").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
  $("script-panel").classList.toggle("hidden", mode !== "script");
  $("topic-panel").classList.toggle("hidden", mode !== "topic");
  invalidateGenerate();
}

document.querySelectorAll("#lang-toggle button").forEach((b) => {
  b.addEventListener("click", () => setLang(b.dataset.lang));
});
document.querySelectorAll("#mode-toggle button").forEach((b) => {
  b.addEventListener("click", () => setMode(b.dataset.mode));
});

$("subtitle-toggle").addEventListener("change", (e) => {
  $("subtitle-options").classList.toggle("hidden", !e.target.checked);
});

function invalidateGenerate() {
  $("btn-generate").disabled = true;
  $("split-result").classList.add("hidden");
  $("script-result").classList.add("hidden");
}

// ---------- Voices ----------

async function loadVoices() {
  const res = await fetch(`${AGNES_BASE}/api/voices`);
  state.voiceCatalog = await res.json();
  renderVoiceOptions();
}

function renderVoiceOptions() {
  const select = $("voice-select");
  select.innerHTML = "";
  if (!state.voiceCatalog) return;
  const langEntry = state.voiceCatalog.languages.find((l) => l.code === state.lang);
  if (!langEntry) return;

  const byRegion = {};
  for (const v of langEntry.voices) {
    const region = v.region || v.region_code || "other";
    (byRegion[region] = byRegion[region] || []).push(v);
  }
  for (const region of Object.keys(byRegion).sort()) {
    const group = document.createElement("optgroup");
    group.label = region;
    for (const v of byRegion[region]) {
      const opt = document.createElement("option");
      opt.value = v.id;
      opt.textContent = `${v.local_name || v.name} (${v.gender || ""})`;
      group.appendChild(opt);
    }
    select.appendChild(group);
  }
  $("voice-hint").textContent = `${langEntry.count} voices available`;
}

$("btn-voice-preview").addEventListener("click", () => {
  const voiceId = $("voice-select").value;
  if (!voiceId) return;
  const audio = $("voice-preview-audio");
  audio.src = `${AGNES_BASE}/api/voices/preview?voice=${encodeURIComponent(voiceId)}`;
  audio.classList.remove("hidden");
  audio.play().catch(() => {});
});

// ---------- Preview split (script mode) ----------

let splitAbort = null;

$("btn-preview-split").addEventListener("click", async () => {
  const text = $("manuscript-text").value.trim();
  if (!text) return;
  const btn = $("btn-preview-split");
  const cancelBtn = $("btn-cancel-split");
  btn.disabled = true;
  btn.textContent = "Splitting…";
  cancelBtn.classList.remove("hidden");
  splitAbort = new AbortController();
  try {
    const form = new FormData();
    form.append("manuscript_text", text);
    form.append("add_tashkeel", String(state.lang === "ar"));
    const res = await fetch(`${AGNES_BASE}/api/manuscript/preview-split`, {
      method: "POST", body: form, signal: splitAbort.signal,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "split failed");

    state.manuscriptParagraphCount = data.paragraphs.length;
    const box = $("split-result");
    box.innerHTML = `<div class="scene-item"><strong>${data.paragraphs.length} scenes, ~${data.total_duration_sec}s total</strong></div>` +
      data.paragraphs.map((p) => `
        <div class="scene-item">
          <div class="scene-meta">Scene ${p.index + 1} · ~${p.est_duration_sec}s</div>
          ${escapeHtml(p.text)}
        </div>`).join("");
    box.classList.remove("hidden");
    $("btn-generate").disabled = false;
  } catch (err) {
    if (err.name !== "AbortError") alert("Preview split failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Preview Split";
    cancelBtn.classList.add("hidden");
    splitAbort = null;
  }
});

$("btn-cancel-split").addEventListener("click", () => splitAbort && splitAbort.abort());

// ---------- Preview script (topic mode) ----------

function computeSceneDurations() {
  const count = Math.max(2, Math.min(10, parseInt($("scene-count").value, 10) || 5));
  const total = Math.max(10, parseInt($("total-duration").value, 10) || 40);
  const base = Math.floor(total / count);
  const durations = new Array(count).fill(base);
  durations[count - 1] += total - base * count; // put remainder on the last scene
  return durations;
}

let scriptAbort = null;

$("btn-preview-script").addEventListener("click", async () => {
  const idea = $("topic-idea").value.trim();
  if (!idea) return;
  const btn = $("btn-preview-script");
  const cancelBtn = $("btn-cancel-script");
  btn.disabled = true;
  btn.textContent = "Writing…";
  cancelBtn.classList.remove("hidden");
  scriptAbort = new AbortController();
  try {
    const durations = computeSceneDurations();
    state.sceneCount = durations.length;
    state.sceneDurations = durations;

    const form = new FormData();
    form.append("idea", idea);
    form.append("style", $("style-text").value);
    form.append("scene_count", String(durations.length));
    form.append("scene_durations_json", JSON.stringify(durations));
    form.append("content_lang", state.lang);
    form.append("add_tashkeel", String(state.lang === "ar"));
    const res = await fetch(`${AGNES_BASE}/api/creative/preview-script`, {
      method: "POST", body: form, signal: scriptAbort.signal,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "script generation failed");

    const box = $("script-result");
    const perScene = data.narration_by_scene || [];
    box.innerHTML = perScene.map((text, i) => `
        <div class="scene-item">
          <div class="scene-meta">Scene ${i + 1} · ~${durations[i]}s</div>
          ${escapeHtml(text)}
        </div>`).join("");
    box.classList.remove("hidden");
    $("btn-generate").disabled = false;
  } catch (err) {
    if (err.name !== "AbortError") alert("Preview script failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Preview Script";
    cancelBtn.classList.add("hidden");
    scriptAbort = null;
  }
});

$("btn-cancel-script").addEventListener("click", () => scriptAbort && scriptAbort.abort());

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

// ---------- Generate video ----------

$("btn-generate").addEventListener("click", async () => {
  $("btn-generate").disabled = true;
  $("generate-error").classList.add("hidden");
  $("video-result").classList.add("hidden");
  $("narration-preview").classList.add("hidden");
  state.narrationShown = false;
  $("progress-area").classList.remove("hidden");
  setProgress(0, "Submitting…");

  try {
    const taskId = state.mode === "script" ? await submitManuscript() : await submitCreative();
    state.currentTaskId = taskId;
    await saveProject({ task_id: taskId, last_status: "running" });
    pollTask(taskId);
  } catch (err) {
    showGenerateError(err.message);
  }
});

$("btn-cancel-generate").addEventListener("click", async () => {
  if (state.polling) {
    clearInterval(state.polling);
    state.polling = null;
  }
  const taskId = state.currentTaskId;
  state.currentTaskId = null;
  $("progress-area").classList.add("hidden");
  $("btn-generate").disabled = false;
  if (taskId) {
    try {
      await fetch(`${AGNES_BASE}/api/tasks/${taskId}/stop`, { method: "POST" });
    } catch (err) {
      // best-effort -- the task will still show as running on the backend
      // if this fails, but the UI has already stopped watching it.
    }
    saveProject({ last_status: "stopped" });
    renderProjects();
  }
});

async function submitManuscript() {
  const form = new FormData();
  form.append("manuscript_text", $("manuscript-text").value.trim());
  form.append("style", $("style-text").value);
  form.append("video_width", "768");
  form.append("video_height", "1152");
  form.append("video_duration", "8");
  appendAudioSubtitleFields(form);

  const refFiles = Array.from($("ref-image").files);
  if (refFiles.length && state.manuscriptParagraphCount > 0) {
    const allIndices = Array.from({ length: state.manuscriptParagraphCount }, (_, i) => i);
    // Every uploaded image is used for every paragraph -- the backend passes
    // the whole list as reference images for each paragraph's i2v call, so
    // this genuinely keeps a consistent look across all scenes.
    const map = refFiles.map(() => allIndices);
    refFiles.forEach((f) => form.append("reference_images", f));
    form.append("reference_images_map", JSON.stringify(map));
  }

  const res = await fetch(`${AGNES_BASE}/api/tasks/manuscript`, { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "task creation failed");
  return data.task_id;
}

const CONTENT_LANG_LABELS = { ar: "Arabic", en: "English" };

// The Screenwriter's own "match the input language" instruction is not fully
// reliable on its own (an English/Arabic idea can still come back written in
// Chinese) -- an explicit directive in the style field fixes this consistently.
// Only used for topic mode: script mode's narration is the user's own pasted
// text, so there's no LLM narration-language step to steer there.
function languageDirective() {
  const label = CONTENT_LANG_LABELS[state.lang] || "Arabic";
  return `IMPORTANT: Write the story and the narration text in ${label} only — ` +
    "do not use any other language. For scene visual prompts specifically, " +
    "still write in English instead (video generation models respond more " +
    "precisely to English prompts).\n\n";
}

async function submitCreative() {
  const durations = state.sceneDurations;
  const uniform = durations.every((d) => d === durations[0]);

  const form = new FormData();
  form.append("idea", $("topic-idea").value.trim());
  form.append("style", languageDirective() + $("style-text").value);
  form.append("chaining_mode", "keyframes");
  form.append("video_width", "768");
  form.append("video_height", "1152");
  form.append("duration_source", "manual");
  form.append("scene_count", String(state.sceneCount));
  form.append("uniform_duration", String(uniform));
  form.append("scene_durations_json", JSON.stringify(durations));
  appendAudioSubtitleFields(form);

  const refFiles = Array.from($("ref-image").files);
  if (refFiles.length) {
    // First image sets the overall look/character reference for the whole
    // video (the only field the backend uses across all scenes). Any extra
    // images are each pinned to one specific scene, in upload order.
    form.append("reference_image", refFiles[0]);
    refFiles.slice(1).forEach((f) => form.append("scene_reference_images", f));
  }

  const res = await fetch(`${AGNES_BASE}/api/tasks/creative`, { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "task creation failed");
  return data.task_id;
}

function appendAudioSubtitleFields(form) {
  const voiceId = $("voice-select").value;
  form.append("audio_enabled", "true");
  form.append("audio_voice", voiceId);
  form.append("audio_rate", "+0%");
  form.append("audio_lang", state.lang);
  // Arabic TTS reads noticeably more accurately with tashkeel (diacritics) --
  // the backend applies it safely (letter-preserving, verified) to whatever
  // text actually ends up being spoken, so this is always on for Arabic.
  form.append("audio_add_tashkeel", String(state.lang === "ar"));

  const subtitlesOn = $("subtitle-toggle").checked;
  form.append("subtitle_enabled", String(subtitlesOn));
  if (subtitlesOn) {
    form.append("subtitle_style_mode", "fixed");
    form.append("subtitle_color", $("subtitle-color").value);
    form.append("subtitle_position", $("subtitle-position").value);
    form.append("subtitle_fontsize", $("subtitle-fontsize").value);
  }
}

// The Agnes backend's progress messages are hardcoded Chinese strings (its own
// primary audience) -- these rules translate the common ones to English for
// this UI's status line. Any message that doesn't match a rule is shown as-is,
// so nothing breaks if the backend adds a new step/message later.
const STATUS_EXACT = {
  "开始简单视频生成...": "Starting video generation...",
  "正在提取角色描述并生成参考图...": "Extracting character description & generating reference image...",
  "正在生成角色参考图 (t2i)...": "Generating character reference image...",
  "角色参考图生成完成": "Character reference image done",
  "正在生成故事...": "Writing story...",
  "正在编写脚本...": "Writing script...",
  "正在生成尾帧提示词...": "Generating scene transition prompts...",
  "正在生成旁白文案...": "Writing narration...",
  "正在拼接视频...": "Merging final video...",
  "视频拼接完成": "Video merge done",
  "视频生成完成!": "Video generation complete!",
  "视频生成完成": "Video generation complete",
  "音频生成完成": "Audio generation done",
  "读稿音频生成完成": "Narration audio done",
  "字幕生成完成": "Subtitles done",
  "生成单段循环视频...": "Generating loop video...",
  "单段循环视频生成完成": "Loop video done",
  "循环拼接视频+音频+字幕...": "Merging video + audio + subtitles...",
  "主播形象生成完成": "Anchor avatar done",
  "动态描述生成完成": "Motion description done",
};

const STATUS_PATTERNS = [
  [/^故事生成完成/, "Story done"],
  [/^脚本完成，共 (\d+) 个场景/, "Script done — $1 scenes"],
  [/^尾帧提示词完成，共 (\d+) 个/, "Transition prompts done ($1)"],
  [/^图片分析完成/, "Image analysis done"],
  [/^生成配音 \((\d+) 字\)/, "Generating voiceover ($1 chars)"],
  [/^场景 (\d+)\/(\d+): 提交任务/, "Scene $1/$2: submitting..."],
  [/^场景 (\d+)\/(\d+): 等待生成中/, "Scene $1/$2: waiting..."],
  [/^场景 (\d+)\/(\d+): 完成/, "Scene $1/$2: done"],
  [/^场景 (\d+)\/(\d+): 已缓存/, "Scene $1/$2: cached"],
  [/^场景 (\d+)\/(\d+): 续传视频/, "Scene $1/$2: resuming..."],
  [/^场景 (\d+)\/(\d+): 使用自定义尾帧/, "Scene $1/$2: custom end frame"],
  [/^场景 (\d+)\/(\d+): 基于参考图生成尾帧/, "Scene $1/$2: generating end frame..."],
  [/^场景 (\d+)\/(\d+): 自动生成尾帧/, "Scene $1/$2: generating end frame..."],
  [/^提交视频 (\d+)\/(\d+)/, "Submitting video $1/$2"],
  [/^等待视频 (\d+)\/(\d+)/, "Waiting on video $1/$2..."],
  [/^生成场景描述 (\d+)\/(\d+)/, "Generating scene description $1/$2"],
  [/^提交 (\d+) 个视频任务/, "Submitting $1 video jobs..."],
  [/^等待 (\d+) 个视频生成完成/, "Waiting on $1 videos..."],
  [/^生成整段旁白/, "Generating narration audio..."],
  [/^生成整段字幕/, "Generating subtitles..."],
  [/^生成整段读稿/, "Generating narration audio..."],
];

function translateStatusMessage(msg) {
  if (!msg) return msg;
  if (STATUS_EXACT[msg]) return STATUS_EXACT[msg];
  for (const [pattern, replacement] of STATUS_PATTERNS) {
    if (pattern.test(msg)) return msg.replace(pattern, replacement);
  }
  return msg;
}

function setProgress(pct, msg) {
  $("progress-fill").style.width = `${Math.round(pct * 100)}%`;
  $("status-msg").textContent = translateStatusMessage(msg) || "";
}

function showGenerateError(msg) {
  $("progress-area").classList.add("hidden");
  const box = $("generate-error");
  box.textContent = msg;
  box.classList.remove("hidden");
  $("btn-generate").disabled = false;
}

function pollTask(taskId) {
  if (state.polling) clearInterval(state.polling);
  state.polling = setInterval(async () => {
    try {
      const res = await fetch(`${AGNES_BASE}/api/tasks/${taskId}`);
      const data = await res.json();
      setProgress(data.current_progress || 0, data.current_message || data.status);

      if (!state.narrationShown) {
        checkNarrationArtifact(taskId);
      }

      if (data.status === "completed") {
        clearInterval(state.polling);
        state.polling = null;
        state.currentTaskId = null;
        setProgress(1, "Done!");
        $("result-video").src = `${AGNES_BASE}/api/video/${taskId}`;
        $("video-download").href = `${AGNES_BASE}/api/video/${taskId}`;
        state.currentVideoPath = data.final_video_file || null;
        $("video-result").classList.remove("hidden");
        $("btn-generate").disabled = false;
        saveProject({ last_status: "completed", video_path: state.currentVideoPath });
        renderProjects();
      } else if (data.status === "failed" || data.status === "error") {
        clearInterval(state.polling);
        state.polling = null;
        state.currentTaskId = null;
        showGenerateError(data.current_message || "Generation failed");
        saveProject({ last_status: "failed" });
        renderProjects();
      }
    } catch (err) {
      // transient network hiccup -- keep polling
    }
  }, 4000);
}

$("btn-open-folder").addEventListener("click", async () => {
  if (!state.currentVideoPath) return;
  const btn = $("btn-open-folder");
  btn.disabled = true;
  try {
    const res = await fetch("/api/reveal-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.currentVideoPath }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "could not open folder");
  } catch (err) {
    alert("Couldn't open the folder: " + err.message);
  } finally {
    btn.disabled = false;
  }
});

async function checkNarrationArtifact(taskId) {
  try {
    const res = await fetch(`${AGNES_BASE}/api/tasks/${taskId}/artifacts`);
    const data = await res.json();
    const audioArtifact = (data.artifacts || []).find((a) => a.category === "audio" && a.exists);
    if (audioArtifact) {
      state.narrationShown = true;
      $("narration-audio").src = `${AGNES_BASE}${audioArtifact.preview_url}`;
      $("narration-preview").classList.remove("hidden");
    }
  } catch (err) {
    // ignore -- will retry next poll cycle
  }
}

// ---------- Cover generation ----------

let coverAbort = null;

$("btn-generate-cover").addEventListener("click", async () => {
  const prompt = $("cover-prompt").value.trim();
  const title = $("cover-title").value.trim();
  if (!prompt || !title) {
    alert(state.lang === "ar" ? "الرجاء إدخال الوصف والعنوان" : "Please fill in both the prompt and the title");
    return;
  }
  const btn = $("btn-generate-cover");
  const cancelBtn = $("btn-cancel-cover");
  btn.disabled = true;
  cancelBtn.classList.remove("hidden");
  $("cover-error").classList.add("hidden");
  $("cover-result").classList.add("hidden");
  $("cover-progress").classList.remove("hidden");
  coverAbort = new AbortController();

  try {
    // 1) generate a clean text-free background on the Agnes backend
    const genForm = new FormData();
    genForm.append("prompt", prompt);
    genForm.append("size", "1024x1792");
    const genRes = await fetch(`${AGNES_BASE}/api/image/generate`, {
      method: "POST", body: genForm, signal: coverAbort.signal,
    });
    const genData = await genRes.json();
    if (!genRes.ok) throw new Error(genData.detail || "image generation failed");

    // 2) fetch the raw PNG
    const imgRes = await fetch(`${AGNES_BASE}/api/image/${genData.task_id}`, { signal: coverAbort.signal });
    const imgBlob = await imgRes.blob();

    // 3) composite the title on top (always -- covers always carry the title)
    const composeForm = new FormData();
    composeForm.append("image", imgBlob, "background.png");
    composeForm.append("title_text", title);
    composeForm.append("lang", state.lang);
    composeForm.append("color", "white");
    composeForm.append("position", "bottom");
    const composeRes = await fetch("/api/cover/compose", {
      method: "POST", body: composeForm, signal: coverAbort.signal,
    });
    if (!composeRes.ok) {
      const errData = await composeRes.json();
      throw new Error(errData.error || "cover compositing failed");
    }
    const finalBlob = await composeRes.blob();
    const url = URL.createObjectURL(finalBlob);
    $("cover-img").src = url;
    $("cover-download").href = url;
    $("cover-result").classList.remove("hidden");
  } catch (err) {
    if (err.name !== "AbortError") {
      const box = $("cover-error");
      box.textContent = err.message;
      box.classList.remove("hidden");
    }
  } finally {
    btn.disabled = false;
    cancelBtn.classList.add("hidden");
    $("cover-progress").classList.add("hidden");
    coverAbort = null;
  }
});

$("btn-cancel-cover").addEventListener("click", () => coverAbort && coverAbort.abort());

// ---------- Projects (save/resume/recreate, stored as files on disk) ----------

function collectProjectFields() {
  const isTopic = state.mode === "topic";
  const rawText = isTopic ? $("topic-idea").value.trim() : $("manuscript-text").value.trim();
  const name = rawText ? (rawText.length > 48 ? rawText.slice(0, 48) + "…" : rawText) : "Untitled";
  return {
    name,
    lang: state.lang,
    mode: state.mode,
    topic_idea: $("topic-idea").value,
    manuscript_text: $("manuscript-text").value,
    scene_count: $("scene-count").value,
    total_duration: $("total-duration").value,
    style_text: $("style-text").value,
    subtitle_enabled: $("subtitle-toggle").checked,
    subtitle_color: $("subtitle-color").value,
    subtitle_position: $("subtitle-position").value,
    subtitle_fontsize: $("subtitle-fontsize").value,
    voice_id: $("voice-select").value,
  };
}

async function saveProject(extra) {
  const payload = { ...collectProjectFields(), ...(extra || {}) };
  if (state.currentProjectId) payload.id = state.currentProjectId;
  try {
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (res.ok && data.project) state.currentProjectId = data.project.id;
  } catch (err) {
    // best-effort -- don't block generation on project-save failures
  }
}

async function renderProjects() {
  try {
    const res = await fetch("/api/projects");
    const data = await res.json();
    const projects = data.projects || [];
    $("projects-count").textContent = projects.length;
    const list = $("projects-list");
    if (!projects.length) {
      list.innerHTML = '<div class="scene-meta">No saved projects yet — generate a video to save one automatically.</div>';
      return;
    }
    list.innerHTML = projects.map((p) => {
      const statusClass = p.last_status || "pending";
      const modeLabel = p.mode === "topic" ? "Topic" : "Script";
      const langLabel = p.lang === "ar" ? "AR" : "EN";
      const date = p.updated_at ? new Date(p.updated_at * 1000).toLocaleString() : "";
      return `
        <div class="project-item">
          <div class="project-info">
            <div class="project-name">${escapeHtml(p.name || "Untitled")}</div>
            <div class="project-meta">
              <span class="status-pill ${statusClass}">${statusClass}</span>
              ${modeLabel} · ${langLabel} · ${date}
            </div>
          </div>
          <div class="project-actions">
            <button class="secondary continue-btn" data-id="${p.id}">Continue</button>
            <button class="icon-btn delete-btn" data-id="${p.id}" title="Delete">🗑</button>
          </div>
        </div>`;
    }).join("");

    list.querySelectorAll(".continue-btn").forEach((btn) => {
      btn.addEventListener("click", () => continueProject(btn.dataset.id));
    });
    list.querySelectorAll(".delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await fetch(`/api/projects/${btn.dataset.id}`, { method: "DELETE" });
        renderProjects();
      });
    });
  } catch (err) {
    // ignore -- the projects list is a convenience feature, not core functionality
  }
}

async function continueProject(projectId) {
  const res = await fetch(`/api/projects/${projectId}`);
  const data = await res.json();
  if (!res.ok) {
    alert("Could not load that project.");
    return;
  }
  const p = data.project;

  setLang(p.lang || "ar");
  setMode(p.mode || "script");
  $("topic-idea").value = p.topic_idea || "";
  $("manuscript-text").value = p.manuscript_text || "";
  if (p.scene_count) $("scene-count").value = p.scene_count;
  if (p.total_duration) $("total-duration").value = p.total_duration;
  if (p.style_text) $("style-text").value = p.style_text;
  $("subtitle-toggle").checked = !!p.subtitle_enabled;
  $("subtitle-options").classList.toggle("hidden", !p.subtitle_enabled);
  if (p.subtitle_color) $("subtitle-color").value = p.subtitle_color;
  if (p.subtitle_position) $("subtitle-position").value = p.subtitle_position;
  if (p.subtitle_fontsize) $("subtitle-fontsize").value = p.subtitle_fontsize;
  if (p.voice_id) $("voice-select").value = p.voice_id;

  state.currentProjectId = p.id;
  invalidateGenerate();
  $("video-result").classList.add("hidden");
  $("progress-area").classList.add("hidden");

  // If this project has an underlying Agnes task, check whether it's still
  // resumable (running/pending) or already finished, and reconnect to it
  // instead of leaving the user to just re-fill-and-resubmit blindly.
  if (p.task_id) {
    try {
      const taskRes = await fetch(`${AGNES_BASE}/api/tasks/${p.task_id}`);
      if (taskRes.ok) {
        const taskData = await taskRes.json();
        if (taskData.status === "completed") {
          state.currentVideoPath = taskData.final_video_file || p.video_path || null;
          $("result-video").src = `${AGNES_BASE}/api/video/${p.task_id}`;
          $("video-download").href = `${AGNES_BASE}/api/video/${p.task_id}`;
          $("video-result").classList.remove("hidden");
        } else if (taskData.status && taskData.status !== "failed" && taskData.status !== "error") {
          await fetch(`${AGNES_BASE}/api/tasks/${p.task_id}/resume`, { method: "POST" });
          state.currentTaskId = p.task_id;
          $("progress-area").classList.remove("hidden");
          setProgress(taskData.current_progress || 0, taskData.current_message || "Resuming…");
          pollTask(p.task_id);
        }
      }
    } catch (err) {
      // task no longer reachable on the backend -- form is still populated
      // so the user can just click Generate Video again (recreate path).
    }
  }

  window.scrollTo({ top: 0, behavior: "smooth" });
}

$("btn-toggle-projects").addEventListener("click", () => {
  $("projects-list").classList.toggle("hidden");
});

// ---------- Init ----------

setLang("ar");
setMode("script");
loadVoices();
renderProjects();
