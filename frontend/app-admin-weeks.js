async function loadAdminWeeks() {
  if (!activeIsAdmin) return;
  try {
    const res = await fetch(`${API}/admin/weeks`);
    const rows = await res.json();
    if (!res.ok) return setStatus("weeksAdminStatus", rows.detail, false);
    if (!rows.length) {
      document.getElementById("adminWeeksBody").innerHTML = "<tr><td colspan='6' style='color:#444'>No weeks</td></tr>";
      return;
    }
    const tbody = document.getElementById("adminWeeksBody");
    tbody.innerHTML = "";
    rows.forEach(w => {
      const tr = document.createElement("tr");
      tr.dataset.weekId = w.id;
      if (w.is_locked) {
        const start = new Date(w.start_time * 1000).toLocaleString();
        const end   = new Date(w.end_time   * 1000).toLocaleString();
        tr.innerHTML = `
          <td></td>
          <td style="font-size:0.8rem;">${start}</td>
          <td style="font-size:0.8rem;">${end}</td>
          <td><span style='color:#888;font-size:0.75rem;'>LOCKED</span></td>
          <td>${w.roster_count}</td>
          <td>—</td>`;
        tr.cells[0].textContent = w.label;
        tbody.appendChild(tr);
        return;
      }
      tr.innerHTML = `
        <td><input type="text" class="week-edit-label" id="weekEditLabel_${w.id}" style="max-width:130px;" /></td>
        <td><input type="text" class="week-edit-start" id="weekEditStart_${w.id}" placeholder="pp.kk.vvvv" autocomplete="off" title="Start date (pp.kk.vvvv, e.g. 15.5.2026) — click to pick" style="max-width:110px;" /></td>
        <td><input type="text" class="week-edit-end"   id="weekEditEnd_${w.id}"   placeholder="pp.kk.vvvv" autocomplete="off" title="End date (pp.kk.vvvv, e.g. 15.5.2026) — click to pick. Games past midnight still count — ends 03:00 UTC the next day." style="max-width:110px;" /></td>
        <td></td>
        <td>${w.roster_count}</td>
        <td></td>`;
      const labelEl = tr.querySelector(".week-edit-label");
      const startEl = tr.querySelector(".week-edit-start");
      const endEl   = tr.querySelector(".week-edit-end");
      labelEl.value = w.label;
      setDateInputIso(startEl, _utcDateStr(w.start_time));
      // end_time is stored as (end_date + 1 day) 03:00 UTC — subtract a day to
      // show the date the admin originally picked.
      setDateInputIso(endEl, _utcDateStr(w.end_time - 24 * 3600));
      _initNordicDateInput(startEl.id);
      _initNordicDateInput(endEl.id);
      [labelEl, startEl, endEl].forEach(el => {
        el.addEventListener("input", () => _markWeekRowDirty(w.id));
        el.addEventListener("change", () => _markWeekRowDirty(w.id));
      });
      const delBtn = document.createElement("button");
      delBtn.className = "danger";
      delBtn.style.cssText = "padding:2px 7px;";
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", () => deleteAdminWeek(w.id));
      tr.cells[5].appendChild(delBtn);
      tbody.appendChild(tr);
    });
    setStatus("weeksAdminStatus", "");
  } catch (e) {
    setStatus("weeksAdminStatus", e.message, false);
  }
}

async function createAdminWeek() {
  const label = document.getElementById("weekLabel").value.trim();
  const startEl = document.getElementById("weekStart");
  const endEl   = document.getElementById("weekEnd");
  const start_date = dateInputIso(startEl);
  const end_date   = dateInputIso(endEl);
  if (!label)                 return setStatus("weeksAdminStatus", "Enter a label", false);
  if (!start_date || !end_date) return setStatus("weeksAdminStatus", "Set start and end date (pp.kk.vvvv)", false);
  try {
    const res = await fetch(`${API}/admin/weeks`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({label, start_date, end_date}),
    });
    const data = await res.json();
    if (!res.ok) return setStatus("weeksAdminStatus", data.detail, false);
    setStatus("weeksAdminStatus", `Week "${data.label}" created`);
    document.getElementById("weekLabel").value = "";
    document.getElementById("weekStart").value = "";
    document.getElementById("weekEnd").value   = "";
    loadAdminWeeks();
  } catch (e) {
    setStatus("weeksAdminStatus", e.message, false);
  }
}

// Convert a Unix timestamp to its UTC calendar date (YYYY-MM-DD).
function _utcDateStr(ts) {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

// Marks a week row's inputs as edited (dirty) so saveWeekChanges() submits it.
function _markWeekRowDirty(weekId) {
  const tr = document.querySelector(`#adminWeeksBody tr[data-week-id="${weekId}"]`);
  if (!tr) return;
  tr.dataset.dirty = "1";
  tr.classList.add("week-row-dirty");
}

// Submits every dirty (edited) row in the weeks table, one PATCH request per
// row, so one row's rejection (e.g. an overlap) doesn't block the others.
async function saveWeekChanges() {
  const dirtyRows = Array.from(document.querySelectorAll('#adminWeeksBody tr[data-dirty="1"]'));
  if (!dirtyRows.length) return setStatus("weeksAdminStatus", "No changes to save", false);
  let updated = 0;
  const failures = [];
  for (const tr of dirtyRows) {
    const id = parseInt(tr.dataset.weekId, 10);
    const labelEl = tr.querySelector(".week-edit-label");
    const startEl = tr.querySelector(".week-edit-start");
    const endEl   = tr.querySelector(".week-edit-end");
    const label = labelEl.value.trim();
    const start_date = dateInputIso(startEl);
    const end_date   = dateInputIso(endEl);
    if (startEl.value && !start_date) { failures.push(`${label || id}: invalid start date`); continue; }
    if (endEl.value && !end_date)     { failures.push(`${label || id}: invalid end date`); continue; }
    const body = {};
    if (label)      body.label      = label;
    if (start_date) body.start_date = start_date;
    if (end_date)   body.end_date   = end_date;
    try {
      const res = await fetch(`${API}/admin/weeks/${id}`, {
        method: "PATCH", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) { failures.push(`${label || id}: ${data.detail}`); continue; }
      updated++;
    } catch (e) {
      failures.push(`${label || id}: ${e.message}`);
    }
  }
  const summary = failures.length
    ? `${updated} updated, ${failures.length} failed: ${failures.join("; ")}`
    : `${updated} updated`;
  setStatus("weeksAdminStatus", summary, failures.length === 0);
  loadAdminWeeks();
}

function deleteAdminWeek(weekId) {
  const existing = document.getElementById(`deleteWeekConfirm_${weekId}`);
  if (existing) { existing.remove(); return; }
  const row = document.querySelector(`[data-week-id="${weekId}"]`);
  if (!row) return;
  const confirm = document.createElement("tr");
  confirm.id = `deleteWeekConfirm_${weekId}`;
  confirm.className = "delete-confirm-row";
  confirm.innerHTML = `<td colspan="6" style="padding:8px 10px;">
    <span class="delete-confirm-msg">Delete this week? This also removes any roster snapshots for it.</span>
    <span style="margin-left:12px;display:inline-flex;gap:6px;">
      <button class="danger" style="padding:3px 10px;" onclick="_confirmDeleteAdminWeek(${weekId})">Delete</button>
      <button class="ghost" style="padding:3px 10px;" onclick="document.getElementById('deleteWeekConfirm_${weekId}').remove()">Cancel</button>
    </span>
  </td>`;
  row.after(confirm);
}

async function _confirmDeleteAdminWeek(weekId) {
  try {
    const res = await fetch(`${API}/admin/weeks/${weekId}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json(); return setStatus("weeksAdminStatus", d.detail, false); }
    setStatus("weeksAdminStatus", "Week deleted");
    loadAdminWeeks();
  } catch (e) {
    setStatus("weeksAdminStatus", e.message, false);
  }
}

// ---------------------------------------------------------------------------
// Nordic date inputs (d.m.yyyy, e.g. "15.5.2026") with click-to-open calendar
// picker. Backend endpoints still take/return strict ISO yyyy-mm-dd —
// dateInputIso() and setDateInputIso() are the only two functions callers need.
// ---------------------------------------------------------------------------

const _DATE_RE = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/;

function _isoToNordic(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${parseInt(d, 10)}.${parseInt(m, 10)}.${y}`;
}

function _nordicToIso(str) {
  const m = _DATE_RE.exec((str || "").trim());
  if (!m) return "";
  const dd = parseInt(m[1], 10), mm = parseInt(m[2], 10), yyyy = parseInt(m[3], 10);
  const d = new Date(Date.UTC(yyyy, mm - 1, dd));
  const valid = d.getUTCFullYear() === yyyy && d.getUTCMonth() === mm - 1 && d.getUTCDate() === dd;
  if (!valid) return "";
  return `${yyyy}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
}

// Reads the ISO (yyyy-mm-dd) value behind a Nordic date input, "" if empty/invalid.
function dateInputIso(el) {
  return _nordicToIso(el.value);
}

// Sets a Nordic date input's displayed value from an ISO (yyyy-mm-dd) string.
function setDateInputIso(el, iso) {
  el.value = _isoToNordic(iso);
  el.classList.remove("invalid");
}

let _datePickerPopup = null;
let _datePickerTarget = null;

function _closeDatePicker() {
  if (_datePickerPopup) _datePickerPopup.remove();
  _datePickerPopup = null;
  _datePickerTarget = null;
  document.removeEventListener("mousedown", _onDatePickerOutsideClick, true);
}

function _onDatePickerOutsideClick(e) {
  if (_datePickerPopup && !_datePickerPopup.contains(e.target) && e.target !== _datePickerTarget) {
    _closeDatePicker();
  }
}

const _DATE_PICKER_WEEKDAYS = ["Ma", "Ti", "Ke", "To", "Pe", "La", "Su"]; // Monday-first
const _DATE_PICKER_MONTHS = ["January", "February", "March", "April", "May", "June",
                              "July", "August", "September", "October", "November", "December"];

function _renderDatePicker(viewYear, viewMonth) {
  const popup = _datePickerPopup;
  const todayIso = _utcDateStr(Math.floor(Date.now() / 1000));
  const selectedIso = dateInputIso(_datePickerTarget);
  const firstWeekday = (new Date(Date.UTC(viewYear, viewMonth, 1)).getUTCDay() + 6) % 7; // Monday=0
  const daysInMonth = new Date(Date.UTC(viewYear, viewMonth + 1, 0)).getUTCDate();

  let cells = "";
  for (let i = 0; i < firstWeekday; i++) cells += `<span class="date-picker-day empty"></span>`;
  for (let day = 1; day <= daysInMonth; day++) {
    const iso = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const cls = ["date-picker-day"];
    if (iso === todayIso) cls.push("today");
    if (iso === selectedIso) cls.push("selected");
    cells += `<button type="button" class="${cls.join(" ")}" data-iso="${iso}">${day}</button>`;
  }

  popup.innerHTML = `
    <div class="date-picker-header">
      <button type="button" class="date-picker-nav" data-nav="-1" aria-label="Previous month">‹</button>
      <span class="date-picker-title">${_DATE_PICKER_MONTHS[viewMonth]} ${viewYear}</span>
      <button type="button" class="date-picker-nav" data-nav="1" aria-label="Next month">›</button>
    </div>
    <div class="date-picker-weekdays">${_DATE_PICKER_WEEKDAYS.map(w => `<span>${w}</span>`).join("")}</div>
    <div class="date-picker-grid">${cells}</div>
  `;

  popup.querySelector('[data-nav="-1"]').addEventListener("click", () => {
    viewMonth === 0 ? _renderDatePicker(viewYear - 1, 11) : _renderDatePicker(viewYear, viewMonth - 1);
  });
  popup.querySelector('[data-nav="1"]').addEventListener("click", () => {
    viewMonth === 11 ? _renderDatePicker(viewYear + 1, 0) : _renderDatePicker(viewYear, viewMonth + 1);
  });
  popup.querySelectorAll(".date-picker-day[data-iso]").forEach(btn => {
    btn.addEventListener("click", () => {
      setDateInputIso(_datePickerTarget, btn.dataset.iso);
      _datePickerTarget.dispatchEvent(new Event("change"));
      _closeDatePicker();
    });
  });
}

function _openDatePicker(inputEl) {
  if (_datePickerTarget === inputEl) return;
  _closeDatePicker();
  _datePickerTarget = inputEl;
  _datePickerPopup = document.createElement("div");
  _datePickerPopup.className = "date-picker-popup";
  document.body.appendChild(_datePickerPopup);

  const iso = dateInputIso(inputEl);
  const base = iso ? new Date(`${iso}T00:00:00Z`) : new Date();
  _renderDatePicker(base.getUTCFullYear(), base.getUTCMonth());

  const rect = inputEl.getBoundingClientRect();
  _datePickerPopup.style.left = `${rect.left + window.scrollX}px`;
  _datePickerPopup.style.top  = `${rect.bottom + window.scrollY + 4}px`;

  setTimeout(() => document.addEventListener("mousedown", _onDatePickerOutsideClick, true), 0);
}

// Strips anything that isn't a digit or "." as the admin types — day/month
// aren't fixed-width in this format (5.5.2026 is as valid as 15.05.2026), so
// separators aren't auto-inserted; the admin types the dots themselves.
function _restrictDateChars(e) {
  e.target.value = e.target.value.replace(/[^\d.]/g, "");
}

// Wires a d.m.yyyy text input to open the calendar picker on click/focus and
// to flag itself invalid on blur if it holds unparseable text. Idempotent.
function _initNordicDateInput(id) {
  const el = document.getElementById(id);
  if (!el || el.dataset.datePickerInit) return;
  el.dataset.datePickerInit = "1";
  el.addEventListener("focus", () => _openDatePicker(el));
  el.addEventListener("click", () => _openDatePicker(el));
  el.addEventListener("input", _restrictDateChars);
  el.addEventListener("blur", () => {
    el.classList.toggle("invalid", !!el.value && !dateInputIso(el));
  });
}

function initWeekDateInputs() {
  // Inline per-row edit date inputs (weekEditStart_<id>/weekEditEnd_<id>) are
  // initialized individually in loadAdminWeeks() as each row is rendered.
  ["weekStart", "weekEnd"].forEach(_initNordicDateInput);
}
