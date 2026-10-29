const recordBtn = document.getElementById("recordBtn");
const phaseLabel = document.getElementById("phaseLabel");
const messageLabel = document.getElementById("messageLabel");
const devicesLabel = document.getElementById("devicesLabel");
const timerEl = document.getElementById("timer");
const modeTabs = document.getElementById("modeTabs");
const bookField = document.getElementById("bookField");
const bookInput = document.getElementById("bookInput");
const participantsField = document.getElementById("participantsField");
const participantsInput = document.getElementById("participantsInput");
const titleInput = document.getElementById("titleInput");
const titleFieldLabel = document.getElementById("titleFieldLabel");
const titleInputWrap = document.getElementById("titleInputWrap");
const micField = document.getElementById("micField");
const micCheck = document.getElementById("micCheck");
const booksList = document.getElementById("booksList");
const booksRow = document.getElementById("booksRow");
const episodesRow = document.getElementById("episodesRow");
const bookTitleEl = document.getElementById("bookTitle");
const bookSubEl = document.getElementById("bookSub");
const bookContent = document.getElementById("bookContent");
const connStatus = document.getElementById("connStatus");
const shutdownBtn = document.getElementById("shutdownBtn");

let lastPhase = "idle";
let books = [];
let meetings = [];
let mode = localStorage.getItem("mode") || "book";
let selectedSlug = localStorage.getItem("selectedBookSlug") || "";
let selectedMeeting = localStorage.getItem("selectedMeetingSlug") || "";

function fmtElapsed(seconds) {
  const s = Math.floor(seconds);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function escapeAttr(s) {
  return (s || "").replace(/"/g, "&quot;");
}

// --- Modalità ----------------------------------------------------------------

function applyMode(next, opts = {}) {
  mode = next;
  localStorage.setItem("mode", mode);
  modeTabs.querySelectorAll(".mode-tab").forEach(tab => {
    tab.classList.toggle("active", tab.dataset.mode === mode);
  });

  const meeting = mode === "meeting";
  bookField.hidden = meeting;
  participantsField.hidden = !meeting;
  micField.hidden = !meeting;
  titleFieldLabel.textContent = meeting ? "Titolo riunione" : "Titolo episodio";

  if (!opts.skipReload) reloadLists();
}

modeTabs.querySelectorAll(".mode-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    if (tab.disabled) return;
    applyMode(tab.dataset.mode);
  });
});

function reloadLists() {
  if (mode === "meeting") {
    loadMeetings().then(loadMeetingContent);
    episodesRow.innerHTML = "";
  } else {
    loadBooks().then(() => {
      loadBookContent();
      loadEpisodes();
    });
  }
}

// --- Stato -------------------------------------------------------------------

async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    render(data);
    connStatus.innerHTML = '<span class="dot"></span> connesso';
    return data;
  } catch (e) {
    connStatus.innerHTML = '<span class="dot" style="background:#e15b5b;box-shadow:0 0 8px #e15b5b"></span> disconnesso';
  }
}

function render(data) {
  recordBtn.classList.remove("idle", "recording", "processing", "error");
  recordBtn.disabled = false;
  const busy = data.phase === "recording" || data.phase === "processing";
  shutdownBtn.disabled = busy;
  modeTabs.querySelectorAll(".mode-tab").forEach(tab => { tab.disabled = busy; });

  if (data.phase === "recording") {
    recordBtn.classList.add("recording");
    phaseLabel.textContent = data.mode === "meeting" ? "Riunione in registrazione" : "Registrazione in corso";
    timerEl.style.display = "block";
    timerEl.textContent = data.elapsed != null ? fmtElapsed(data.elapsed) : "00:00";
    titleInputWrap.style.visibility = "hidden";
  } else if (data.phase === "processing") {
    recordBtn.classList.add("processing");
    recordBtn.disabled = true;
    phaseLabel.textContent = "Elaborazione";
    timerEl.style.display = "none";
    titleInputWrap.style.visibility = "hidden";
  } else if (data.phase === "error") {
    recordBtn.classList.add("idle");
    phaseLabel.textContent = "Errore";
    timerEl.style.display = "none";
    titleInputWrap.style.visibility = "visible";
  } else {
    recordBtn.classList.add("idle");
    phaseLabel.textContent = "Pronto";
    timerEl.style.display = "none";
    titleInputWrap.style.visibility = "visible";
  }

  messageLabel.textContent = data.message;
  devicesLabel.textContent = busy ? (data.devices || "") : "";

  // quando torniamo idle dopo una processing, ciò che è appena stato prodotto
  // (raccolta aggiornata o nuovo verbale) diventa la selezione corrente
  if (lastPhase === "processing" && data.phase === "idle") {
    if (data.mode === "meeting") {
      if (data.meeting_slug) selectedMeeting = data.meeting_slug;
      localStorage.setItem("selectedMeetingSlug", selectedMeeting);
      loadMeetings().then(loadMeetingContent);
    } else {
      if (data.book_slug) selectBook(data.book_slug, data.book_title, { skipReload: true });
      loadBooks();
      loadBookContent();
      loadEpisodes();
    }
  }
  lastPhase = data.phase;
}

// --- Raccolte ----------------------------------------------------------------

async function loadBooks() {
  const res = await fetch("/api/books");
  books = await res.json();

  booksList.innerHTML = books.map(b => `<option value="${escapeAttr(b.title)}">`).join("");

  if (!selectedSlug && books.length) {
    selectedSlug = books[0].slug;
  }

  booksRow.innerHTML = books.map(b => `
    <span class="book-chip ${b.slug === selectedSlug ? "active" : ""}" data-slug="${b.slug}" data-title="${escapeAttr(b.title)}">${b.title}</span>
  `).join("");

  booksRow.querySelectorAll(".book-chip").forEach(chip => {
    chip.addEventListener("click", () => selectBook(chip.dataset.slug, chip.dataset.title));
  });

  if (selectedSlug && !bookInput.value) {
    const cur = books.find(b => b.slug === selectedSlug);
    if (cur) bookInput.value = cur.title;
  }
}

function selectBook(slug, title, opts = {}) {
  selectedSlug = slug;
  localStorage.setItem("selectedBookSlug", slug);
  bookInput.value = title || "";
  booksRow.querySelectorAll(".book-chip").forEach(chip => {
    chip.classList.toggle("active", chip.dataset.slug === slug);
  });
  if (!opts.skipReload) {
    loadBookContent();
    loadEpisodes();
  }
}

async function loadBookContent() {
  if (!selectedSlug) {
    bookTitleEl.textContent = "Nessuna raccolta";
    bookSubEl.textContent = "Scegli o crea una raccolta per iniziare.";
    bookContent.innerHTML = "<p class='empty'>Nessuna raccolta selezionata.</p>";
    return;
  }
  const res = await fetch(`/api/book?slug=${encodeURIComponent(selectedSlug)}`);
  const data = await res.json();
  bookTitleEl.textContent = data.title || "Nuova raccolta";
  bookSubEl.textContent = "Estratto automaticamente dagli episodi ascoltati.";
  bookContent.innerHTML = data.html;
}

async function loadEpisodes() {
  if (!selectedSlug) {
    episodesRow.innerHTML = "";
    return;
  }
  const res = await fetch(`/api/episodes?book=${encodeURIComponent(selectedSlug)}`);
  const episodes = await res.json();
  episodesRow.innerHTML = episodes.map(ep => `
    <span class="episode-chip"><span class="d">${ep.date}</span>${ep.title}</span>
  `).join("");
}

// --- Riunioni ----------------------------------------------------------------

async function loadMeetings() {
  const res = await fetch("/api/meetings");
  meetings = await res.json();

  if ((!selectedMeeting || !meetings.some(m => m.slug === selectedMeeting)) && meetings.length) {
    selectedMeeting = meetings[0].slug;
    localStorage.setItem("selectedMeetingSlug", selectedMeeting);
  }

  booksRow.innerHTML = meetings.map(m => `
    <span class="book-chip ${m.slug === selectedMeeting ? "active" : ""}" data-slug="${escapeAttr(m.slug)}"><span class="d">${m.date}</span> ${m.title}</span>
  `).join("");

  booksRow.querySelectorAll(".book-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      selectedMeeting = chip.dataset.slug;
      localStorage.setItem("selectedMeetingSlug", selectedMeeting);
      booksRow.querySelectorAll(".book-chip").forEach(c => {
        c.classList.toggle("active", c.dataset.slug === selectedMeeting);
      });
      loadMeetingContent();
    });
  });
}

async function loadMeetingContent() {
  if (!selectedMeeting || !meetings.length) {
    bookTitleEl.textContent = "Nessuna riunione";
    bookSubEl.textContent = "Registra una riunione per averne il verbale.";
    bookContent.innerHTML = "<p class='empty'>Nessun verbale ancora prodotto.</p>";
    return;
  }
  const res = await fetch(`/api/meeting?slug=${encodeURIComponent(selectedMeeting)}`);
  const data = await res.json();
  bookTitleEl.textContent = data.title || "Verbale";
  bookSubEl.textContent = "Verbale generato dalla registrazione della riunione.";
  bookContent.innerHTML = data.html;
}

// --- Azioni ------------------------------------------------------------------

recordBtn.addEventListener("click", async () => {
  const status = await fetchStatus();
  if (!status) return;

  if (status.phase === "idle" || status.phase === "error") {
    const bookName = bookInput.value.trim();
    if (mode === "book" && !bookName) {
      bookInput.classList.add("missing");
      bookInput.focus();
      return;
    }
    bookInput.classList.remove("missing");

    if (status.phase === "error") {
      await fetch("/api/reset", { method: "POST" });
    }
    const res = await fetch("/api/record/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode,
        book: bookName,
        title: titleInput.value.trim(),
        participants: participantsInput.value.trim(),
        capture_mic: micCheck.checked,
      }),
    });
    if (res.ok) {
      titleInput.value = "";
    } else {
      const err = await res.json().catch(() => ({}));
      messageLabel.textContent = err.detail || "Errore nell'avvio della registrazione.";
    }
  } else if (status.phase === "recording") {
    await fetch("/api/record/stop", { method: "POST" });
  }
  fetchStatus();
});

bookInput.addEventListener("input", () => bookInput.classList.remove("missing"));

shutdownBtn.addEventListener("click", async () => {
  if (shutdownBtn.disabled) return;
  if (!confirm("Chiudere l'app e fermare il server? Potrai riaprirla in qualsiasi momento dall'icona.")) return;

  shutdownBtn.disabled = true;
  shutdownBtn.textContent = "Chiusura...";
  try {
    await fetch("/api/shutdown", { method: "POST" });
  } catch (e) { /* la connessione cade non appena il server si ferma: previsto */ }

  clearInterval(pollTimer);
  phaseLabel.textContent = "App chiusa";
  messageLabel.textContent = "Server fermato. Puoi chiudere questa finestra.";
  connStatus.innerHTML = '<span class="dot" style="background:#5c6270"></span> disconnesso';
  setTimeout(() => window.close(), 600);
});

let pollTimer = null;

function startPolling() {
  fetchStatus();
  pollTimer = setInterval(fetchStatus, 1200);
}

applyMode(mode, { skipReload: true });
startPolling();
reloadLists();
