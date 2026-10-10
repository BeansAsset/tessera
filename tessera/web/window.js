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

const PHONE = '<svg class="phone" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><rect x="6.5" y="2.5" width="11" height="19" rx="2.5"/><path d="M10.5 18.5h3"/></svg>';

function when(seconds) {
  if (!seconds) return null;
  const d = new Date(seconds * 1000);
  const today = new Date();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `today ${time}`;
  return d.toLocaleDateString([], { day: "numeric", month: "short" });
}

function deviceRow(d) {
  const li = document.createElement("li");
  const icon = document.createElement("template");
  icon.innerHTML = PHONE;
  const info = document.createElement("div");
  info.className = "info";
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = d.name || "iPhone";
  const time = document.createElement("div");
  time.className = "when";
  const used = when(d.last_used);
  time.textContent = `Paired ${when(d.added)}` + (used ? ` · last unlocked ${used}` : "");
  info.append(name, time);

  const remove = document.createElement("button");
  remove.className = "btn small";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => {
    if (remove.dataset.sure) { call("remove", d.id); return; }
    remove.dataset.sure = "1";
    remove.textContent = "Remove for sure";
    remove.classList.add("danger");
    setTimeout(() => { delete remove.dataset.sure; remove.textContent = "Remove"; remove.classList.remove("danger"); }, 3000);
  });
  li.append(icon.content.firstChild, info, remove);
  return li;
}

function render(s) {
  $("error").hidden = !s.error;
  $("error").textContent = s.error || "";
  $("where").textContent = `Listening on your Wi-Fi as ${s.address}`;

  const view = s.code ? "confirm" : s.pairing ? "pairing" : "home";
  for (const id of ["home", "pairing", "confirm"]) $(id).hidden = id !== view;

  $("devices").replaceChildren(...s.devices.map(deviceRow));
  $("empty").hidden = s.devices.length > 0;
  $("pair").textContent = s.devices.length ? "Pair another iPhone" : "Pair an iPhone";

  if (!$("qr").src) $("qr").src = s.setup_qr;
  const m = Math.floor(s.pairing / 60), sec = String(s.pairing % 60).padStart(2, "0");
  $("left").textContent = `${m}:${sec}`;
  $("code").textContent = s.code || "";
}
on.state = render;

$("pair").addEventListener("click", () => call("pair"));
$("cancel").addEventListener("click", () => call("cancel"));
$("no").addEventListener("click", () => call("cancel"));
$("yes").addEventListener("click", () => call("confirm", $("code").textContent));

(async () => render(await call("ready")))();
