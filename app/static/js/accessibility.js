(function () {
    const STORAGE_KEY = "local_thrift_a11y_v1";
    const DEFAULT_STATE = {
        fontScale: 100,
        lineHeight: false,
        letterSpacing: false,
        dyslexia: false,
        highlightLinks: false,
        colorMode: "none", // none | high-contrast | dark-contrast | monochrome
        readingGuide: false,
        bigCursor: false,
        stopMotion: false,
    };

    let state = loadState();

    function loadState() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return { ...DEFAULT_STATE };
            return { ...DEFAULT_STATE, ...JSON.parse(raw) };
        } catch (_e) {
            return { ...DEFAULT_STATE };
        }
    }

    function saveState() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        } catch (_e) {}
    }

    function applyState() {
        const root = document.documentElement;
        root.style.fontSize = state.fontScale + "%";

        root.classList.toggle("a11y-line-height", !!state.lineHeight);
        root.classList.toggle("a11y-letter-spacing", !!state.letterSpacing);
        root.classList.toggle("a11y-dyslexia", !!state.dyslexia);
        root.classList.toggle("a11y-highlight-links", !!state.highlightLinks);
        root.classList.toggle("a11y-reading-guide", !!state.readingGuide);
        root.classList.toggle("a11y-big-cursor", !!state.bigCursor);
        root.classList.toggle("a11y-stop-motion", !!state.stopMotion);

        root.classList.toggle("a11y-high-contrast", state.colorMode === "high-contrast");
        root.classList.toggle("a11y-dark-contrast", state.colorMode === "dark-contrast");
        root.classList.toggle("a11y-monochrome", state.colorMode === "monochrome");

        syncUI();
    }

    function syncUI() {
        const label = document.getElementById("a11y-font-label");
        if (label) label.textContent = state.fontScale + "%";

        document.querySelectorAll("[data-a11y-toggle]").forEach((btn) => {
            const key = btn.getAttribute("data-a11y-toggle");
            btn.setAttribute("aria-pressed", state[key] ? "true" : "false");
        });

        document.querySelectorAll("[data-a11y-color]").forEach((btn) => {
            const mode = btn.getAttribute("data-a11y-color");
            btn.setAttribute("aria-pressed", state.colorMode === mode ? "true" : "false");
        });
    }

    function openPanel() {
        const panel = document.getElementById("a11y-panel");
        const fab = document.getElementById("a11y-fab");
        if (!panel) return;
        panel.classList.remove("hidden");
        if (fab) fab.setAttribute("aria-expanded", "true");
    }

    function closePanel() {
        const panel = document.getElementById("a11y-panel");
        const fab = document.getElementById("a11y-fab");
        if (!panel) return;
        panel.classList.add("hidden");
        if (fab) fab.setAttribute("aria-expanded", "false");
    }

    function togglePanel() {
        const panel = document.getElementById("a11y-panel");
        if (!panel) return;
        if (panel.classList.contains("hidden")) openPanel();
        else closePanel();
    }

    window.a11yAdjustFont = function (delta) {
        state.fontScale = Math.max(85, Math.min(130, state.fontScale + delta));
        saveState();
        applyState();
    };

    window.a11yToggle = function (key) {
        if (!(key in state)) return;
        state[key] = !state[key];
        saveState();
        applyState();
    };

    window.a11ySetColorMode = function (mode) {
        state.colorMode = state.colorMode === mode ? "none" : mode;
        saveState();
        applyState();
    };

    window.a11yReset = function () {
        state = { ...DEFAULT_STATE };
        saveState();
        applyState();
    };

    window.a11yTogglePanel = togglePanel;
    window.a11yClosePanel = closePanel;

    // Reading guide mengikuti posisi vertikal mouse
    document.addEventListener("mousemove", function (e) {
        if (!state.readingGuide) return;
        const bar = document.getElementById("a11y-reading-guide");
        if (bar) bar.style.top = e.clientY + "px";
    });

    // Shortcut Alt+A buka/tutup panel, Esc tutup panel
    document.addEventListener("keydown", function (e) {
        if (e.altKey && (e.key === "a" || e.key === "A")) {
            e.preventDefault();
            togglePanel();
        } else if (e.key === "Escape") {
            const panel = document.getElementById("a11y-panel");
            if (panel && !panel.classList.contains("hidden")) {
                closePanel();
            }
        }
    });

    // Terapkan segera saat DOM siap
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", applyState);
    } else {
        applyState();
    }
})();
