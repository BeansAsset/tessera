"use strict";

/* Tessera window. Python keeps the state; this page draws it. */

const pending = new Map();
let nextId = 1;
function call(cmd, ...args) {
  const id = nextId++;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    window.webkit.messageHandlers.app.postMessage({ id, cmd, args });
  });
}
const on = {};
window.App = {
  resolve(id, result) { const r = pending.get(id); pending.delete(id); if (r) r(result); },
  emit(name, data) { if (on[name]) on[name](data); },
};

const $ = (id) => document.getElementById(id);

const PHONE = '<svg class="icon" viewBox="0 0 16 16" fill="currentColor"><path d="M5 1a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V3a2 2 0 0 0-2-2H5zm0 1.5h6a.5.5 0 0 1 .5.5v10a.5.5 0 0 1-.5.5H5a.5.5 0 0 1-.5-.5V3a.5.5 0 0 1 .5-.5zM6.5 11a.5.5 0 0 0 0 1h3a.5.5 0 0 0 0-1h-3z"/></svg>';

function when(seconds) {
  if (!seconds) return null;
  const d = new Date(seconds * 1000);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (d.toDateString() === new Date().toDateString()) return `today at ${time}`;
  return d.toLocaleDateString([], { day: "numeric", month: "long" });
}

function deviceRow(d) {
  const li = document.createElement("li");
  li.className = "row";
  const icon = document.createElement("template");
  icon.innerHTML = PHONE;

  const text = document.createElement("div");
  text.className = "text";
  const title = document.createElement("div");
  title.className = "title";
  title.textContent = d.name || "iPhone";
  const sub = document.createElement("div");
  sub.className = "subtitle";
  const used = when(d.last_used);
  sub.textContent = used ? `Last unlocked ${used}` : `Paired ${when(d.added)}`;
  text.append(title, sub);

  // Removing asks once more, in place, before it happens.
  const remove = document.createElement("button");
  remove.className = "button flat";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => {
    if (remove.dataset.sure) { call("remove", d.id); return; }
    remove.dataset.sure = "1";
    remove.textContent = "Remove iPhone?";
    remove.classList.add("destructive");
    setTimeout(() => {
      delete remove.dataset.sure;
      remove.textContent = "Remove";
      remove.classList.remove("destructive");
    }, 3000);
  });

  li.append(icon.content.firstChild, text, remove);
  return li;
}

function render(s) {
  $("error").hidden = !s.error;
  $("error").textContent = s.error || "";
  $("where").textContent = `Reachable on this network as ${s.address}`;

  const view = s.code ? "confirm" : s.pairing ? "pairing" : s.devices.length ? "home" : "empty";
  for (const id of ["empty", "home", "pairing", "confirm"]) $(id).hidden = id !== view;

  $("devices").replaceChildren(...s.devices.map(deviceRow));
  if (!$("qr").src) $("qr").src = s.setup_qr;
  const m = Math.floor(s.pairing / 60), sec = String(s.pairing % 60).padStart(2, "0");
  $("left").textContent = `${m}:${sec}`;
  $("code").textContent = s.code || "";
}
on.state = render;

for (const b of document.querySelectorAll('[data-action="pair"]')) b.addEventListener("click", () => call("pair"));
$("cancel").addEventListener("click", () => call("cancel"));
$("no").addEventListener("click", () => call("cancel"));
$("yes").addEventListener("click", () => call("confirm", $("code").textContent));

(async () => render(await call("ready")))();
