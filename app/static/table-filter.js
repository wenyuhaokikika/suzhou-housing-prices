/**
 * 表格列筛选：在 .filterable 表头下生成筛选控件
 * th[data-type=text|select|number|none]
 * td[data-v] 为可比对的原始值（可选，默认用单元格文本）
 */
(function () {
  function norm(s) {
    return (s || "").toString().trim().toLowerCase();
  }
  function parseNum(s) {
    if (s == null || s === "" || s === "-" || s === "—") return null;
    const m = String(s).replace(/,/g, "").match(/-?[\d.]+/);
    return m ? parseFloat(m[0]) : null;
  }
  function cellValue(td) {
    if (td.hasAttribute("data-v")) return td.getAttribute("data-v") || "";
    return (td.textContent || "").trim();
  }
  function uniqueValues(table, colIdx) {
    const set = new Set();
    table.querySelectorAll("tbody tr").forEach((tr) => {
      if (tr.classList.contains("empty-row")) return;
      const td = tr.children[colIdx];
      if (!td) return;
      const v = cellValue(td).trim();
      if (v && v !== "-" && v !== "—") set.add(v);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, "zh-CN"));
  }

  function applyFilters(table) {
    const filters = table._colFilters || [];
    let visible = 0;
    table.querySelectorAll("tbody tr").forEach((tr) => {
      if (tr.classList.contains("empty-row") || tr.classList.contains("filter-empty-msg")) {
        tr.style.display = "none";
        return;
      }
      let ok = true;
      filters.forEach((f) => {
        if (!ok || !f) return;
        const td = tr.children[f.idx];
        if (!td) return;
        const raw = cellValue(td);
        if (f.type === "text") {
          if (f.q && !norm(raw).includes(norm(f.q))) ok = false;
        } else if (f.type === "select") {
          if (f.q && f.q !== "__all__" && cellValue(td).trim() !== f.q) ok = false;
        } else if (f.type === "number") {
          const n = parseNum(raw);
          if (f.min != null && f.min !== "" && (n == null || n < parseFloat(f.min))) ok = false;
          if (f.max != null && f.max !== "" && (n == null || n > parseFloat(f.max))) ok = false;
        }
      });
      tr.style.display = ok ? "" : "none";
      if (ok) visible++;
    });
    let msg = table.querySelector("tbody tr.filter-empty-msg");
    if (!msg) {
      msg = document.createElement("tr");
      msg.className = "filter-empty-msg";
      const td = document.createElement("td");
      td.colSpan = table.querySelectorAll("thead tr.labels th").length || 10;
      td.className = "muted";
      td.textContent = "无匹配行，请调整筛选条件";
      msg.appendChild(td);
      table.querySelector("tbody").appendChild(msg);
    }
    msg.style.display = visible === 0 ? "" : "none";
    const counter = table.closest(".card, .section")?.querySelector(".filter-count");
    if (counter) counter.textContent = `显示 ${visible} 行`;
  }

  function buildFilterRow(table) {
    const labelRow = table.querySelector("thead tr.labels") || table.querySelector("thead tr");
    if (!labelRow) return;
    labelRow.classList.add("labels");
    if (table.querySelector("thead tr.filters")) return;

    const filterRow = document.createElement("tr");
    filterRow.className = "filters";
    const filters = [];

    Array.from(labelRow.children).forEach((th, idx) => {
      const type = th.getAttribute("data-type") || "none";
      const td = document.createElement("th");
      td.className = "filter-cell";
      if (type === "text") {
        const input = document.createElement("input");
        input.type = "search";
        input.placeholder = "包含…";
        input.className = "tf-input";
        input.addEventListener("input", () => {
          filters[idx] = { idx, type, q: input.value };
          applyFilters(table);
        });
        td.appendChild(input);
        filters[idx] = { idx, type, q: "" };
      } else if (type === "select") {
        const sel = document.createElement("select");
        sel.className = "tf-select";
        const optAll = document.createElement("option");
        optAll.value = "__all__";
        optAll.textContent = "全部";
        sel.appendChild(optAll);
        uniqueValues(table, idx).forEach((v) => {
          const o = document.createElement("option");
          o.value = v;
          o.textContent = v;
          sel.appendChild(o);
        });
        // 预填 URL 参数
        const key = th.getAttribute("data-key");
        if (key) {
          const sp = new URLSearchParams(location.search);
          if (sp.get(key)) {
            const want = sp.get(key);
            // market: ershou -> 二手房 label may differ; try exact match on data-v options
            for (const o of sel.options) {
              if (o.value === want || o.textContent === want) {
                sel.value = o.value;
                break;
              }
            }
          }
        }
        sel.addEventListener("change", () => {
          filters[idx] = { idx, type, q: sel.value };
          applyFilters(table);
        });
        td.appendChild(sel);
        filters[idx] = { idx, type, q: sel.value };
      } else if (type === "number") {
        const wrap = document.createElement("div");
        wrap.className = "tf-range";
        const min = document.createElement("input");
        min.type = "number";
        min.placeholder = "最小";
        min.className = "tf-input tf-num";
        const max = document.createElement("input");
        max.type = "number";
        max.placeholder = "最大";
        max.className = "tf-input tf-num";
        const sync = () => {
          filters[idx] = { idx, type, min: min.value, max: max.value };
          applyFilters(table);
        };
        min.addEventListener("input", sync);
        max.addEventListener("input", sync);
        wrap.appendChild(min);
        wrap.appendChild(document.createTextNode("–"));
        wrap.appendChild(max);
        td.appendChild(wrap);
        filters[idx] = { idx, type, min: "", max: "" };
      } else {
        td.innerHTML = '<span class="tf-na">—</span>';
        filters[idx] = null;
      }
      filterRow.appendChild(td);
    });

    table._colFilters = filters;
    labelRow.parentNode.appendChild(filterRow);

    // 工具条：重置 + 计数
    const host = table.closest(".card, .section") || table.parentElement;
    if (host && !host.querySelector(".filter-toolbar")) {
      const bar = document.createElement("div");
      bar.className = "filter-toolbar";
      bar.innerHTML =
        '<span class="filter-count muted"></span> <button type="button" class="btn tf-reset">重置本表筛选</button>';
      host.insertBefore(bar, host.firstChild.nextSibling);
      // put after h2 if present
      const h2 = host.querySelector("h2");
      if (h2 && h2.nextSibling) host.insertBefore(bar, h2.nextSibling);
      else host.insertBefore(bar, table);
      bar.querySelector(".tf-reset").addEventListener("click", () => {
        filterRow.querySelectorAll("input").forEach((el) => {
          el.value = "";
        });
        filterRow.querySelectorAll("select").forEach((el) => {
          el.value = "__all__";
        });
        filters.forEach((f, i) => {
          if (!f) return;
          if (f.type === "text") f.q = "";
          if (f.type === "select") f.q = "__all__";
          if (f.type === "number") {
            f.min = "";
            f.max = "";
          }
        });
        applyFilters(table);
      });
    }
    applyFilters(table);
  }

  function init() {
    document.querySelectorAll("table.filterable").forEach(buildFilterRow);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
