// Small progressive enhancements; every form also works without JavaScript.
document.addEventListener("DOMContentLoaded", () => {
  // Choosing another project reloads the form with its corpuses and contractors (GET, no mailing).
  document.querySelectorAll("[data-reload-project]").forEach((el) => {
    el.addEventListener("change", () => {
      if (el.value) window.location.assign(`/send?project_id=${encodeURIComponent(el.value)}`);
    });
  });

  const form = document.getElementById("send-form");
  if (!form) return;

  const checks = Array.from(form.querySelectorAll("input[name='contractor_ids']"));
  const button = document.getElementById("s-submit");
  const counter = document.getElementById("s-count");
  const recount = () => {
    const n = checks.filter((c) => c.checked && !c.disabled).length;
    counter.textContent = `${n} из ${checks.length} подрядчиков проекта`;
    button.textContent = n ? `Отправить уведомления: ${n}` : "Выберите хотя бы одного подрядчика";
    button.disabled = !n;
  };
  checks.forEach((c) => c.addEventListener("change", recount));

  // Live preview of the accompanying message.
  const message = document.getElementById("s-message");
  const preview = document.getElementById("prev-message");
  const previewBox = document.getElementById("prev-message-box");
  const syncMessage = () => {
    preview.textContent = message.value.trim();
    previewBox.hidden = !message.value.trim();
  };
  message?.addEventListener("input", syncMessage);

  // Contractors who already got this link for this corpus are unchecked by default.
  const link = document.getElementById("s-link");
  const project = form.querySelector("[name='project_id']");
  const corpus = form.querySelector("[name='corpus_id']");
  const markAlreadySent = async () => {
    if (!corpus?.value || !link.value.trim()) return;
    const params = new URLSearchParams({
      project_id: project.value, corpus_id: corpus.value, sarex_link: link.value.trim(),
    });
    try {
      const response = await fetch(`/send/already-sent?${params}`);
      if (!response.ok) return;
      const { already_sent: sent } = await response.json();
      checks.forEach((c) => {
        const was = sent.includes(c.value);
        c.closest(".check").querySelector(".already").hidden = !was;
        if (was) c.checked = false;
      });
      recount();
    } catch (_) { /* the server checks again on submit */ }
  };
  link?.addEventListener("change", markAlreadySent);
  corpus?.addEventListener("change", () => {
    const label = document.getElementById("prev-corpus");
    if (label && corpus.selectedIndex >= 0) label.textContent = corpus.options[corpus.selectedIndex].text;
    markAlreadySent();
  });
  markAlreadySent();
  recount();
});

// Board filters apply as soon as a value is chosen.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-autosubmit-get]").forEach((el) => {
    el.addEventListener("change", () => {
      if (el.name === "project_id") {
        window.location.assign(`/?project_id=${encodeURIComponent(el.value)}`);
      } else {
        el.form.submit();
      }
    });
  });
});
