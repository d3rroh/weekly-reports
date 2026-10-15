/* Weekly Outcomes Review — page behaviour (no inline scripts; CSP-safe). */
(function () {
  "use strict";

  // ---------------------------------------------------------------- sidebar
  var toggle = document.querySelector("[data-nav-toggle]");
  var sidebar = document.querySelector(".sidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      var open = sidebar.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // ---------------------------------------------------------------- print
  document.querySelectorAll("[data-print]").forEach(function (btn) {
    btn.addEventListener("click", function () { window.print(); });
  });

  // ---------------------------------------------------------------- auto-submit selects
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.submit(); });
  });

  // ---------------------------------------------------------------- dialogs
  document.querySelectorAll("[data-open-dialog]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dlg = document.getElementById(btn.getAttribute("data-open-dialog"));
      if (dlg && dlg.showModal) { dlg.showModal(); }
    });
  });
  document.querySelectorAll("[data-close-dialog]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dlg = btn.closest("dialog");
      if (dlg) { dlg.close(); }
    });
  });

  // ---------------------------------------------------------------- tabs
  var tabs = Array.prototype.slice.call(document.querySelectorAll("[role=tab]"));
  function showTab(name, focus) {
    var found = false;
    tabs.forEach(function (t) {
      var on = t.getAttribute("data-tab") === name;
      if (on) { found = true; }
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      var panel = document.getElementById(t.getAttribute("aria-controls"));
      if (panel) { panel.hidden = !on; }
      if (on && focus) { t.focus(); }
    });
    return found;
  }
  function openFromHash() {
    if (!tabs.length) { return; }
    var hash = (location.hash || "").replace("#", "");
    if (hash && showTab(hash)) { return; }
    if (hash) {
      var target = document.getElementById(hash);
      var panel = target && target.closest("[role=tabpanel]");
      if (panel) {
        showTab(panel.getAttribute("data-tab-name"));
        target.scrollIntoView({ block: "start" });
        return;
      }
    }
    var preset = document.querySelector("[data-open-tab]");
    showTab(preset ? preset.getAttribute("data-open-tab") : tabs[0].getAttribute("data-tab"));
  }
  if (tabs.length) {
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () {
        showTab(t.getAttribute("data-tab"));
        history.replaceState(null, "", "#" + t.getAttribute("data-tab"));
      });
      t.addEventListener("keydown", function (e) {
        var d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!d) { return; }
        var next = tabs[(i + d + tabs.length) % tabs.length];
        showTab(next.getAttribute("data-tab"), true);
      });
    });
    openFromHash();
    window.addEventListener("hashchange", openFromHash);
    document.querySelectorAll("[data-goto-tab]").forEach(function (a) {
      a.addEventListener("click", function () { showTab(a.getAttribute("data-goto-tab")); });
    });
  }

  // ---------------------------------------------------------------- confirmations
  // Registered before the autosave flush so a cancelled confirm stops everything.
  document.addEventListener("submit", function (e) {
    var f = e.target;
    var msg = f.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);

  // ---------------------------------------------------------------- autosave
  var form = document.getElementById("details-form");
  var statusEl = document.querySelector("[data-save-status]");
  var dirty = false;
  var saving = null;
  var timer = null;

  function setStatus(text, cls) {
    if (!statusEl) { return; }
    statusEl.textContent = text;
    statusEl.className = "save-status " + (cls || "");
  }

  function csrfToken(f) {
    var input = f.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function clearErrors() {
    form.querySelectorAll(".field.has-error").forEach(function (el) {
      el.classList.remove("has-error");
      var list = el.querySelector(".errorlist.js");
      if (list) { list.remove(); }
    });
  }

  function showErrors(errors) {
    Object.keys(errors || {}).forEach(function (name) {
      var input = form.querySelector("[name='" + name + "']");
      var field = input && input.closest(".field");
      if (!field) { return; }
      field.classList.add("has-error");
      var ul = document.createElement("ul");
      ul.className = "errorlist js";
      errors[name].forEach(function (msg) {
        var li = document.createElement("li");
        li.textContent = msg;
        ul.appendChild(li);
      });
      field.appendChild(ul);
    });
  }

  function updateProgress(cl) {
    if (!cl) { return; }
    document.querySelectorAll("[data-progress-percent]").forEach(function (el) { el.textContent = cl.percent + "%"; });
    document.querySelectorAll("progress[data-progress]").forEach(function (el) { el.value = cl.percent; });
    Object.keys(cl.items || {}).forEach(function (key) {
      document.querySelectorAll("[data-check-item='" + key + "']").forEach(function (el) {
        el.classList.toggle("done", !!cl.items[key]);
        el.textContent = cl.items[key] ? "✓" : "";
      });
    });
    Object.keys(cl.questions || {}).forEach(function (n) {
      document.querySelectorAll("[data-q-status='" + n + "']").forEach(function (el) {
        el.className = cl.questions[n] ? "ok" : "todo";
        el.textContent = cl.questions[n] ? "●" : "○";
        el.setAttribute("title", cl.questions[n] ? "Answered" : "Not yet answered");
      });
    });
  }

  function save() {
    if (!form) { return Promise.resolve(true); }
    if (saving) { return saving.then(function () { return dirty ? save() : true; }); }
    if (!dirty) { return Promise.resolve(true); }
    dirty = false;
    setStatus("Saving…", "saving");
    var data = new FormData(form);
    saving = fetch(form.getAttribute("data-autosave-url"), {
      method: "POST",
      body: data,
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrfToken(form) }
    }).then(function (resp) {
      return resp.json().catch(function () { return null; }).then(function (json) {
        if (!json) { throw new Error("HTTP " + resp.status); }
        clearErrors();
        showErrors(json.errors);
        updateProgress(json.checklist);
        if (json.ok) {
          setStatus("All changes saved · " + json.saved_at, "saved");
        } else {
          setStatus("Some fields need attention — valid changes saved " + json.saved_at, "error");
        }
        return json.ok;
      });
    }).catch(function () {
      dirty = true;
      setStatus("Not saved — connection problem. Your edits are still on this page; retrying…", "error");
      clearTimeout(timer);
      timer = setTimeout(save, 8000);
      return false;
    }).then(function (ok) { saving = null; return ok; });
    return saving;
  }

  if (form && form.getAttribute("data-autosave-url")) {
    var markDirty = function (e) {
      if (e && e.target && e.target.form !== form) { return; }
      dirty = true;
      setStatus("Unsaved changes", "saving");
      clearTimeout(timer);
      timer = setTimeout(save, 1500);
    };
    form.addEventListener("input", markDirty);
    form.addEventListener("change", markDirty);
    form.addEventListener("submit", function () { dirty = false; });

    // Flush pending edits before leaving the page or submitting other forms.
    document.addEventListener("submit", function (e) {
      var f = e.target;
      if (f === form || !(dirty || saving)) { return; }
      e.preventDefault();
      save().then(function () { HTMLFormElement.prototype.submit.call(f); });
    }, true);
    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a[href]");
      if (!a || !(dirty || saving) || a.target === "_blank" || a.getAttribute("href").charAt(0) === "#") { return; }
      e.preventDefault();
      save().then(function () { window.location.href = a.href; });
    });
    window.addEventListener("beforeunload", function (e) {
      if (dirty || saving) { e.preventDefault(); e.returnValue = ""; }
    });
  }

  // Submit dialog: require explicit confirmation when incomplete.
  document.querySelectorAll("[data-require-check]").forEach(function (f) {
    var box = f.querySelector("input[type=checkbox][name=confirm_incomplete]");
    var btn = f.querySelector("button[type=submit]");
    if (!box || !btn) { return; }
    var sync = function () { btn.disabled = !box.checked; };
    box.addEventListener("change", sync);
    sync();
  });

  // Comment target → suggest a matching category.
  var target = document.getElementById("id_target");
  var category = document.getElementById("id_category");
  if (target && category && category.hasAttribute("data-suggest")) {
    var map = JSON.parse(document.getElementById("comment-category-map").textContent);
    target.addEventListener("change", function () {
      if (map[target.value]) { category.value = map[target.value]; }
    });
  }
})();
