(function () {
  const state = {
    config: null,
    dirty: false,
    poller: null,
    sectionObserver: null,
  };

  function el(id) {
    return document.getElementById(id);
  }

  function markDirty(isDirty) {
    state.dirty = isDirty;
    el("settings-save").disabled = !isDirty;
    el("unsaved-indicator").classList.toggle("hidden", !isDirty);
  }

  function parseValue(input) {
    if (input.type === "checkbox") return input.checked;
    if (input.type === "number") return Number(input.value);
    return input.value;
  }

  function fillForm(cfg) {
    document.querySelectorAll("[data-cfg]").forEach((input) => {
      const key = input.dataset.cfg;
      if (!(key in cfg)) return;
      const val = cfg[key];
      if (input.type === "checkbox") input.checked = Boolean(val);
      else input.value = val ?? "";
    });
    updateSocialPreview();
  }

  function collectForm() {
    const payload = {};
    document.querySelectorAll("[data-cfg]").forEach((input) => {
      payload[input.dataset.cfg] = parseValue(input);
    });
    return payload;
  }

  function showToast(message) {
    const toast = document.createElement("div");
    toast.className = "settings-toast";
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 1800);
  }

  function updateSocialPreview() {
    const buzz = document.querySelector('[data-cfg="social_min_buzz_for_influence"]')?.value || "HIGH";
    const impact = document.querySelector('[data-cfg="social_min_impact_for_influence"]')?.value || "AMPLIFYING";
    const maxAdj = document.querySelector('[data-cfg="social_max_score_adjustment"]')?.value || "0.5";
    el("social-preview").textContent =
      `With these settings, social can influence verdict only when Buzz >= ${buzz}, Impact >= ${impact}, and Meme Risk = YES. Max score adjustment: +/-${maxAdj}.`;
  }

  function updateSidebarActive() {
    const links = [...document.querySelectorAll(".settings-sidebar a[data-scroll]")];
    const sections = links
      .map((link) => ({ link, section: document.querySelector(link.dataset.scroll) }))
      .filter((row) => row.section);

    if (state.sectionObserver) state.sectionObserver.disconnect();

    state.sectionObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const active = sections.find((row) => row.section === entry.target);
          if (!active) return;
          links.forEach((l) => l.classList.remove("active"));
          active.link.classList.add("active");
        });
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0.01 }
    );

    sections.forEach((row) => state.sectionObserver.observe(row.section));
  }

  async function refreshProviderStatus() {
    const status = await fetch("/api/provider-status").then((r) => r.json());
    const settings = await fetch("/api/settings").then((r) => r.json());
    const ro = settings._readonly || {};

    const limit = Number(settings.daily_compound_limit || 0);
    const used = Number(status.budget_today || 0);
    const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;

    el("budget-gauge-text").textContent = `Today: ${used} / ${limit} compound calls used`;
    el("budget-gauge-bar").style.width = `${pct.toFixed(1)}%`;

    const now = new Date();
    const midnight = new Date(now);
    midnight.setHours(24, 0, 0, 0);
    const ms = midnight.getTime() - now.getTime();
    const h = Math.floor(ms / 3600000);
    const m = Math.floor((ms % 3600000) / 60000);
    el("budget-reset-timer").textContent = `Resets in: ${h}h ${m}m`;

    el("cache-count").textContent = `Cache currently holds ${ro.cache_entries ?? 0} entries.`;
    el("groq-key-status").textContent = ro.groq_key_set
      ? `Loaded (${ro.groq_key_masked || "masked"})`
      : "Not found (set GROQ_API_KEY in .env)";
    el("compound-status").textContent = status.compound_available ? "✓ available" : "✗ unavailable";
    el("instant-status").textContent = status.instant_available ? "✓ available" : "✗ unavailable";
  }

  function bindEvents() {
    document.querySelectorAll("[data-cfg]").forEach((input) => {
      input.addEventListener("input", () => {
        markDirty(true);
        if (["social_min_buzz_for_influence", "social_min_impact_for_influence", "social_max_score_adjustment"].includes(input.dataset.cfg)) {
          updateSocialPreview();
        }
      });
      input.addEventListener("change", () => {
        markDirty(true);
        if (["social_min_buzz_for_influence", "social_min_impact_for_influence", "social_max_score_adjustment"].includes(input.dataset.cfg)) {
          updateSocialPreview();
        }
      });
    });

    document.querySelectorAll(".settings-sidebar a[data-scroll]").forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        const target = document.querySelector(link.dataset.scroll);
        if (!target) return;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    el("settings-save").addEventListener("click", async () => {
      const payload = collectForm();
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      markDirty(false);
      showToast("Settings saved");
      await refreshProviderStatus();
    });

    el("settings-reset").addEventListener("click", async () => {
      if (!window.confirm("Reset all settings? This cannot be undone.")) return;
      await fetch("/api/settings/reset", { method: "POST" });
      window.location.reload();
    });

    el("clear-cache").addEventListener("click", async () => {
      await fetch("/api/cache/clear", { method: "POST" });
      await refreshProviderStatus();
      showToast("Cache cleared");
    });

    el("reset-budget").addEventListener("click", async () => {
      if (!window.confirm("Reset today's budget counter?")) return;
      await fetch("/api/budget/reset", { method: "POST" });
      await refreshProviderStatus();
      showToast("Budget counter reset");
    });

    el("test-models").addEventListener("click", async () => {
      const result = await fetch("/api/ai/test").then((r) => r.json());
      const lines = [
        `Research ${result.research.ok ? "✓" : "✗"}`,
        `Cross ${result.cross_exam.ok ? "✓" : "✗"}`,
        `Synthesis ${result.synthesis.ok ? "✓" : "✗"}`,
        `Social ${result.social.ok ? "✓" : "✗"}`,
      ];
      el("test-models-result").textContent = lines.join(" | ");
    });

    el("provider-refresh").addEventListener("click", refreshProviderStatus);

    el("export-config").addEventListener("click", async () => {
      const cfgNow = await fetch("/api/settings").then((r) => r.json());
      delete cfgNow._readonly;
      const blob = new Blob([JSON.stringify(cfgNow, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "alphaswarm_config.json";
      a.click();
      URL.revokeObjectURL(url);
    });

    el("import-config-btn").addEventListener("click", () => el("import-config-input").click());
    el("import-config-input").addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const text = await file.text();
      const parsed = JSON.parse(text);
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed),
      });
      window.location.reload();
    });
  }

  async function initSettings() {
    const settings = await fetch("/api/settings").then((r) => r.json());
    const { _readonly, ...configOnly } = settings;
    state.config = configOnly;

    fillForm(configOnly);
    bindEvents();
    updateSidebarActive();
    await refreshProviderStatus();
    markDirty(false);

    if (state.poller) clearInterval(state.poller);
    state.poller = setInterval(refreshProviderStatus, 30000);
  }

  window.AlphaSettings = {
    initSettings,
  };
})();
