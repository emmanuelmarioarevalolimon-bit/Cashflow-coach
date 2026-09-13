/* Safe Markdown + LaTeX renderer for Gemini chat messages.
   Third-party libraries are vendored locally so the UI does not execute CDN code. */
(() => {
  "use strict";

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);

  const inlineDollarRule = /^(\${1,2})(?!\$)((?:\\.|[^\\\n])*?(?:\\.|[^\\\n$]))\1(?=[\s?!.,:;]|$)/;
  const blockDollarRule = /^(\${2})\n((?:\\[^]|[^\\])+?)\n\1(?:\n|$)/;
  const latexDelimiterRule = /^\\([([])((?:\\.|[^\\\n])*?)\\([)\]])/;

  function mathToken(token) {
    const display = token.displayMode ? " c1-math-display" : "";
    return `<span class="c1-math-source${display}">${escapeHtml(token.text)}</span>`;
  }

  function mathExtensions() {
    return {
      extensions: [
        {
          name: "c1BlockMath",
          level: "block",
          tokenizer(source) {
            const match = source.match(blockDollarRule);
            if (!match) return undefined;
            return {type: "c1BlockMath", raw: match[0], text: match[2].trim(), displayMode: true};
          },
          renderer: mathToken,
        },
        {
          name: "c1InlineMath",
          level: "inline",
          start(source) {
            const indexes = [source.indexOf("$"), source.indexOf("\\("), source.indexOf("\\[")]
              .filter((index) => index >= 0);
            return indexes.length ? Math.min(...indexes) : undefined;
          },
          tokenizer(source) {
            const latex = source.match(latexDelimiterRule);
            if (latex && ((latex[1] === "(" && latex[3] === ")") || (latex[1] === "[" && latex[3] === "]"))) {
              return {
                type: "c1InlineMath",
                raw: latex[0],
                text: latex[2].trim(),
                displayMode: latex[1] === "[",
              };
            }
            const dollar = source.match(inlineDollarRule);
            if (!dollar) return undefined;
            return {
              type: "c1InlineMath",
              raw: dollar[0],
              text: dollar[2].trim(),
              displayMode: dollar[1].length === 2,
            };
          },
          renderer: mathToken,
        },
      ],
    };
  }

  let initialized = false;

  function initialize() {
    if (initialized) return true;
    if (!window.marked?.marked || !window.DOMPurify || !window.katex) return false;
    window.marked.marked.use(mathExtensions());
    initialized = true;
    return true;
  }

  function secureLinks(container) {
    container.querySelectorAll("a[href]").forEach((link) => {
      let parsed;
      try { parsed = new URL(link.getAttribute("href"), window.location.href); }
      catch { link.removeAttribute("href"); return; }
      if (!["http:", "https:", "mailto:"].includes(parsed.protocol)) {
        link.removeAttribute("href");
        return;
      }
      if (parsed.protocol !== "mailto:") {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
    });
  }

  function renderMath(container) {
    container.querySelectorAll(".c1-math-source").forEach((node) => {
      const source = node.textContent || "";
      try {
        window.katex.render(source, node, {
          displayMode: node.classList.contains("c1-math-display"),
          throwOnError: false,
          strict: "warn",
          trust: false,
          maxExpand: 1000,
          output: "htmlAndMathml",
        });
      } catch {
        node.textContent = source;
        node.classList.add("c1-math-error");
      }
    });
  }

  function render(container, value, options = {}) {
    const source = String(value ?? "");
    if (!options.rich || !initialize()) {
      container.textContent = source;
      return;
    }
    const unsafe = window.marked.marked.parse(source, {gfm: true, breaks: true, async: false});
    container.innerHTML = window.DOMPurify.sanitize(unsafe, {
      FORBID_TAGS: ["script", "style", "template", "form", "input", "button", "textarea", "select", "option", "iframe", "object", "embed", "img", "video", "audio", "source"],
      FORBID_ATTR: ["style"],
      ALLOW_DATA_ATTR: false,
      SANITIZE_NAMED_PROPS: true,
    });
    secureLinks(container);
    renderMath(container);
  }

  window.C1RichText = {render};
})();
