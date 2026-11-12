"use strict";

/* PaperPulse — 三栏布局前端应用逻辑 */

(function() {
  // ─── 状态 ───
  var state = {
    dates: [],
    currentDateIndex: 0,
    data: null,
    allArticles: [],        // 扁平化所有文章
    filteredArticles: [],   // 搜索/期刊筛选后
    searchQuery: "",
    selectedJournal: "",    // 当前选中的期刊（""=全部）
    selectedArticle: null,  // 当前选中的文章
    lang: "zh",
    collapsedGroups: {},    // 左边栏折叠的出版商组
    detailPinned: false,    // 右边栏是否固定
  };

  // ─── DOM 引用 ───
  var $ = function(id) { return document.getElementById(id); };
  var elLoading = $("loading");
  var elError = $("error");
  var elErrorText = $("errorText");
  var elEmpty = $("empty");
  var elContent = $("content");
  var elToolbar = $("toolbar");
  var elArticleList = $("articleList");
  var elCurrentDate = $("currentDate");
  var elPrevDate = $("prevDate");
  var elNextDate = $("nextDate");
  var elSearchInput = $("searchInput");
  var elSearchClear = $("searchClear");
  var elLangToggle = $("langToggle");
  var elThemeToggle = $("themeToggle");
  var elSidebar = $("sidebar");
  var elSidebarBody = $("sidebarBody");
  var elSidebarToggle = $("sidebarToggle");
  var elSidebarClose = $("sidebarClose");
  var elDetailPanel = $("detailPanel");
  var elDetailBody = $("detailBody");
  var elDetailClose = $("detailClose");
  var elDetailPin = $("detailPin");
  var elDetailReopen = $("detailReopen");
  var elResizeHandleLeft = $("resizeHandleLeft");
  var elResizeHandleRight = $("resizeHandleRight");
  var elDatePicker = $("datePicker");

  // ─── i18n ───
  var i18n = {
    zh: {
      loading: "加载中",
      noData: "当日无文献",
      statsArticles: "篇文献",
      statsJournals: "个期刊",
      searchPlaceholder: "搜索标题、期刊、作者",
      fetchError: "数据加载失败",
      noDate: "无日期",
      sourceRSS: "RSS",
      sourcePubMed: "PubMed",
      clickToView: "点击文献查看详情",
      journalLabel: "期刊",
      allJournals: "全部期刊",
      typeLabel: "类型",
      authorsLabel: "作者",
      doiLabel: "DOI",
      dateLabel: "日期",
      abstractLabel: "摘要",
      openLink: "查看原文",
    },
    en: {
      loading: "Loading",
      noData: "No articles for this date",
      statsArticles: "articles",
      statsJournals: "journals",
      searchPlaceholder: "Search title, journal, author",
      fetchError: "Failed to load data",
      noDate: "No date",
      sourceRSS: "RSS",
      sourcePubMed: "PubMed",
      clickToView: "Click an article to view details",
      journalLabel: "Journal",
      allJournals: "All journals",
      typeLabel: "Type",
      authorsLabel: "Authors",
      doiLabel: "DOI",
      dateLabel: "Date",
      abstractLabel: "Abstract",
      openLink: "View original",
    }
  };

  function t(key) {
    return i18n[state.lang][key] || key;
  }

  function applyI18n() {
    document.documentElement.dataset.lang = state.lang;
    elSearchInput.placeholder = t("searchPlaceholder");
    document.querySelectorAll("[data-zh]").forEach(function(el) {
      el.textContent = state.lang === "zh" ? el.dataset.zh : el.dataset.en;
    });
    if (state.data) {
      renderSidebar();
      renderToolbar();
      renderArticleList();
      renderDetail();
    }
  }

  // ─── 日期导航 ───
  function loadDates() {
    fetch("data/index.json")
      .then(function(r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function(data) {
        state.dates = data.dates || [];
        if (state.dates.length === 0) {
          showError(t("fetchError"));
          return;
        }
        state.currentDateIndex = 0;
        loadCurrentDate();
      })
      .catch(function() {
        var today = new Date().toISOString().slice(0, 10);
        state.dates = [today];
        state.currentDateIndex = 0;
        loadCurrentDate();
      });
  }

  function loadCurrentDate() {
    if (state.currentDateIndex < 0 || state.currentDateIndex >= state.dates.length) return;
    var date = state.dates[state.currentDateIndex];
    showLoading();
    elCurrentDate.textContent = date;
    elDatePicker.value = date;

    fetch("data/" + date + ".json")
      .then(function(r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function(data) {
        state.data = data;
        state.searchQuery = "";
        state.selectedJournal = "";
        state.selectedArticle = null;
        elSearchInput.value = "";
        elSearchClear.classList.remove("visible");
        flattenArticles();
        // 只显示当天的文献
        filterToCurrentDate(date);
        renderAll();
      })
      .catch(function(e) {
        showError(t("fetchError") + ": " + e.message);
      });

    updateDateNavButtons();
  }

  // 只保留当天上线的文献（pub_date 等于选定的日期）
  function filterToCurrentDate(date) {
    state.allArticles = state.allArticles.filter(function(a) {
      return !a.pub_date || a.pub_date === date;
    });
  }

  function updateDateNavButtons() {
    elPrevDate.disabled = state.currentDateIndex >= state.dates.length - 1;
    elNextDate.disabled = state.currentDateIndex <= 0;
  }

  // ─── 数据扁平化 ───
  function flattenArticles() {
    var journals = state.data.journals || {};
    var all = [];
    for (var j in journals) {
      journals[j].forEach(function(a) {
        all.push(a);
      });
    }
    state.allArticles = all;
  }

  // ─── 渲染入口 ───
  function renderAll() {
    computeFiltered();
    renderSidebar();
    renderToolbar();
    renderArticleList();
    renderDetail();
  }

  function computeFiltered() {
    var q = state.searchQuery.toLowerCase().trim();
    var jf = state.selectedJournal;
    state.filteredArticles = state.allArticles.filter(function(a) {
      if (jf && a.journal !== jf) return false;
      if (!q) return true;
      var haystack = [
        a.title || "",
        a.journal || "",
        (a.authors || []).join(" "),
        a.doi || "",
      ].join(" ").toLowerCase();
      return haystack.indexOf(q) !== -1;
    });
  }

  // ─── 左边栏：期刊树 ───
  function getPublisherOrder() {
    return [
      "Nature Portfolio", "Cell Press", "Science / AAAS",
      "National Academy of Sciences",
      "Annual Reviews", "Wiley", "Springer", "Oxford", "Elsevier", "ASM",
      "Royal Society", "Taylor & Francis", "Microbiology Society", "PLOS",
      "eLife Sciences", "Mary Ann Liebert", "ACS", "Cold Spring Harbor",
      "EMBO Press", "Science China Press", "Copernicus Publications",
      "预印本", "其他",
    ];
  }

  // 从 sources.json 的 publisher 字段构建映射（也可从数据中推断）
  function buildPublisherMap() {
    // 从当前数据推断 journal -> publisher
    var map = {};
    var journals = state.data.journals || {};
    for (var j in journals) {
      if (journals[j].length > 0) {
        // 从文章的 source 字段推断分类
        var src = journals[j][0].source || "";
        map[j] = map[j] || "其他";
      }
    }
    return map;
  }

  // 用 sources.json 内嵌的 publisher 信息来分组（从 config 加载）
  var sourcesConfig = null;
  function loadSourcesConfig() {
    if (sourcesConfig) return;
    fetch("config/sources.json")
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) { sourcesConfig = data; if (state.data) renderSidebar(); })
      .catch(function() {});
  }

  function getJournalPublisher(journalName) {
    if (!sourcesConfig) return "其他";
    var i, e;
    var lists = [sourcesConfig.rss || [], sourcesConfig.pubmed || [], sourcesConfig.preprints || []];
    for (var li = 0; li < lists.length; li++) {
      for (i = 0; i < lists[li].length; i++) {
        e = lists[li][i];
        if (e.name === journalName) return e.publisher || "其他";
      }
    }
    return "其他";
  }

  function renderSidebar() {
    var journals = state.data.journals || {};
    var journalNames = Object.keys(journals).sort();

    // 按出版商分组
    var groups = {};
    journalNames.forEach(function(name) {
      var pub = getJournalPublisher(name);
      if (!groups[pub]) groups[pub] = [];
      groups[pub].push({ name: name, count: journals[name].length });
    });

    // 排序出版商组
    var order = getPublisherOrder();
    var orderedPubs = order.filter(function(p) { return groups[p]; });
    var extraPubs = Object.keys(groups)
      .filter(function(p) { return order.indexOf(p) === -1; })
      .sort();
    var allPubs = orderedPubs.concat(extraPubs);

    var totalArticles = state.allArticles.length;
    var totalJournals = journalNames.length;

    var html = "";

    // "全部期刊"入口
    html += '<div class="journal-item' + (state.selectedJournal === "" ? " active" : "") + '" data-journal="">';
    html += '<span class="journal-item-name">' + t("allJournals") + '</span>';
    html += '<span class="journal-item-count">' + totalArticles + '</span>';
    html += '</div>';

    // 分组
    allPubs.forEach(function(pub) {
      var items = groups[pub];
      var groupTotal = items.reduce(function(s, it) { return s + it.count; }, 0);
      var collapsed = state.collapsedGroups[pub];

      html += '<div class="journal-group' + (collapsed ? " collapsed" : "") + '" data-publisher="' + escapeAttr(pub) + '">';
      html += '<div class="journal-group-header">';
      html += '<svg class="journal-group-arrow" viewBox="0 0 24 24" fill="none"><path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      html += '<span class="journal-group-name">' + escapeHtml(pub) + '</span>';
      html += '<span class="journal-group-count">' + groupTotal + '</span>';
      html += '</div>';

      html += '<div class="journal-group-items">';
      items.sort(function(a, b) { return a.name.localeCompare(b.name); });
      items.forEach(function(item) {
        var active = state.selectedJournal === item.name;
        html += '<div class="journal-item' + (active ? " active" : "") + '" data-journal="' + escapeAttr(item.name) + '">';
        html += '<span class="journal-item-name">' + escapeHtml(item.name) + '</span>';
        html += '<span class="journal-item-count">' + item.count + '</span>';
        html += '</div>';
      });
      html += '</div>'; // items
      html += '</div>'; // group
    });

    elSidebarBody.innerHTML = html;

    // 绑定事件
    elSidebarBody.querySelectorAll(".journal-group-header").forEach(function(hdr) {
      hdr.addEventListener("click", function() {
        var group = hdr.closest(".journal-group");
        var pub = group.dataset.publisher;
        state.collapsedGroups[pub] = !state.collapsedGroups[pub];
        group.classList.toggle("collapsed");
      });
    });

    elSidebarBody.querySelectorAll(".journal-item").forEach(function(item) {
      item.addEventListener("click", function() {
        var j = item.dataset.journal;
        state.selectedJournal = j;
        state.selectedArticle = null;
        computeFiltered();
        renderSidebar();
        renderToolbar();
        renderArticleList();
        renderDetail();
      });
    });
  }

  // ─── 工具栏 ───
  function renderToolbar() {
    var html = "";
    var count = state.filteredArticles.length;
    var journalCount = countUniqueJournals(state.filteredArticles);

    html += '<div class="toolbar-item"><span class="toolbar-value">' + count + '</span> ' + t("statsArticles") + '</div>';
    html += '<div class="toolbar-item"><span class="toolbar-value">' + journalCount + '</span> ' + t("statsJournals") + '</div>';

    if (state.selectedJournal) {
      html += '<span class="toolbar-filter-tag">';
      html += escapeHtml(state.selectedJournal);
      html += '<svg class="tag-remove" width="10" height="10" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M6 18L18 6" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg>';
      html += '</span>';
    }

    elToolbar.innerHTML = html;

    // 绑定 tag 移除
    var tagRemove = elToolbar.querySelector(".tag-remove");
    if (tagRemove) {
      tagRemove.addEventListener("click", function() {
        state.selectedJournal = "";
        computeFiltered();
        renderSidebar();
        renderToolbar();
        renderArticleList();
      });
    }
  }

  function countUniqueJournals(articles) {
    var set = {};
    articles.forEach(function(a) { set[a.journal] = true; });
    return Object.keys(set).length;
  }

  // ─── 中间栏：紧凑文章列表 ───
  function renderArticleList() {
    hideStates();

    if (state.filteredArticles.length === 0) {
      elEmpty.style.display = "flex";
      return;
    }

    var html = "";
    state.filteredArticles.forEach(function(a, idx) {
      var active = state.selectedArticle === a;
      html += renderArticleRow(a, idx, active);
    });

    elArticleList.innerHTML = html;
    elContent.style.display = "block";

    // 绑定点击
    elArticleList.querySelectorAll(".article-row").forEach(function(row) {
      row.addEventListener("click", function(e) {
        // 如果点击了外链，不选中
        if (e.target.closest(".article-ext-link")) return;
        var idx = parseInt(row.dataset.idx, 10);
        var article = state.filteredArticles[idx];
        state.selectedArticle = article;

        // 如果右边栏关闭，自动打开
        if (document.documentElement.dataset.detail === "closed") {
          document.documentElement.dataset.detail = "open";
          try { localStorage.setItem("pp-detail", "open"); } catch(e) {}
        }

        renderArticleList();
        renderDetail();
      });
    });
  }

  function renderArticleRow(a, idx, active) {
    var html = '<li class="article-row' + (active ? " active" : "") + '" data-idx="' + idx + '">';

    // 内容
    html += '<div class="article-content">';

    // 标题
    html += '<div class="article-title">' + escapeHtml(a.title) + '</div>';

    // 元数据行
    html += '<div class="article-meta-row">';
    html += '<span class="article-meta-journal">' + escapeHtml(a.journal || "") + '</span>';
    if (a.authors && a.authors.length > 0) {
      var authorStr = a.authors.slice(0, 2).join(", ");
      if (a.authors.length > 2) authorStr += " et al.";
      html += '<span class="article-meta-authors">' + escapeHtml(authorStr) + '</span>';
    }
    if (a.pub_date) {
      html += '<span class="article-meta-date">' + escapeHtml(a.pub_date) + '</span>';
    }
    html += '</div>';

    html += '</div>'; // content

    // 外链图标
    if (a.link) {
      html += '<a class="article-ext-link article-ext-icon" href="' + escapeHtml(a.link) + '" target="_blank" rel="noopener noreferrer">';
      html += '<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M7 17L17 7M7 7h10v10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      html += '</a>';
    }

    html += '</li>';
    return html;
  }

  // ─── 右边栏：文献详情 ───
  function renderDetail() {
    if (!state.selectedArticle) {
      elDetailBody.innerHTML = '<div class="detail-empty">' + t("clickToView") + '</div>';
      return;
    }

    var a = state.selectedArticle;
    var html = '<div class="detail-content">';

    // 文章类型
    if (a.article_type) {
      html += '<div class="detail-article-type">' + escapeHtml(a.article_type) + '</div>';
    }

    // 标题
    html += '<div class="detail-article-title">' + escapeHtml(a.title) + '</div>';

    // 原文链接
    if (a.link) {
      html += '<a class="detail-article-link" href="' + escapeHtml(a.link) + '" target="_blank" rel="noopener noreferrer">';
      html += '<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M7 17L17 7M7 7h10v10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      html += t("openLink");
      html += '</a>';
    }

    // 期刊
    if (a.journal) {
      html += '<div class="detail-section">';
      html += '<div class="detail-section-label">' + t("journalLabel") + '</div>';
      html += '<div class="detail-journal-name">' + escapeHtml(a.journal) + '</div>';
      html += '</div>';
    }

    // 来源
    var srcLabel = getSourceLabel(a.source);
    if (srcLabel) {
      html += '<div class="detail-section">';
      html += '<div class="detail-section-label">' + t("typeLabel") + '</div>';
      html += '<div class="detail-journal-name">' + escapeHtml(srcLabel) + '</div>';
      html += '</div>';
    }

    // 作者
    if (a.authors && a.authors.length > 0) {
      html += '<div class="detail-section">';
      html += '<div class="detail-section-label">' + t("authorsLabel") + '</div>';
      html += '<div class="detail-authors">' + escapeHtml(a.authors.join(", ")) + '</div>';
      html += '</div>';
    }

    // 日期
    if (a.pub_date) {
      html += '<div class="detail-section">';
      html += '<div class="detail-section-label">' + t("dateLabel") + '</div>';
      html += '<div class="detail-pub-date">' + escapeHtml(a.pub_date) + '</div>';
      html += '</div>';
    }

    // DOI
    if (a.doi) {
      html += '<div class="detail-section">';
      html += '<div class="detail-section-label">' + t("doiLabel") + '</div>';
      html += '<a class="detail-doi" href="https://doi.org/' + escapeHtml(a.doi) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(a.doi) + '</a>';
      html += '</div>';
    }

    // PMID
    if (a.pmid) {
      html += '<div class="detail-section">';
      html += '<div class="detail-section-label">PMID</div>';
      html += '<a class="detail-doi" href="https://pubmed.ncbi.nlm.nih.gov/' + escapeHtml(a.pmid) + '/" target="_blank" rel="noopener noreferrer">' + escapeHtml(a.pmid) + '</a>';
      html += '</div>';
    }

    // 摘要
    if (a.abstract) {
      html += '<div class="detail-section">';
      html += '<div class="detail-section-label">' + t("abstractLabel") + '</div>';
      html += '<div class="detail-abstract">' + escapeHtml(a.abstract) + '</div>';
      html += '</div>';
    }

    html += '</div>';
    elDetailBody.innerHTML = html;
  }

  function getSourceLabel(source) {
    if (!source) return "";
    if (source === "pubmed") return t("sourcePubMed");
    return t("sourceRSS");
  }

  // ─── UI 状态 ───
  function showLoading() {
    hideStates();
    elLoading.style.display = "flex";
  }
  function showError(msg) {
    hideStates();
    elErrorText.textContent = msg;
    elError.style.display = "flex";
  }
  function hideStates() {
    elLoading.style.display = "none";
    elError.style.display = "none";
    elEmpty.style.display = "none";
    elContent.style.display = "none";
  }

  // ─── 工具 ───
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function escapeAttr(str) {
    return escapeHtml(str);
  }

  // ─── 边栏折叠 ───
  function toggleSidebar() {
    var root = document.documentElement;
    var isOpen = root.dataset.sidebar === "open";
    root.dataset.sidebar = isOpen ? "closed" : "open";
    try { localStorage.setItem("pp-sidebar", root.dataset.sidebar); } catch(e) {}
  }

  function toggleDetail() {
    var root = document.documentElement;
    var isOpen = root.dataset.detail === "open";
    root.dataset.detail = isOpen ? "closed" : "open";
    try { localStorage.setItem("pp-detail", root.dataset.detail); } catch(e) {}
  }

  function toggleDetailPin() {
    state.detailPinned = !state.detailPinned;
    elDetailPin.classList.toggle("active", state.detailPinned);
  }

  // ─── 日期选择器 ───
  function openDatePicker() {
    elDatePicker.classList.add("active");
    try { elDatePicker.showPicker ? elDatePicker.showPicker() : elDatePicker.focus(); } catch(e) { elDatePicker.focus(); }
  }
  function closeDatePicker() {
    elDatePicker.classList.remove("active");
  }

  elCurrentDate.addEventListener("click", openDatePicker);
  elCurrentDate.addEventListener("keydown", function(e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openDatePicker();
    }
  });

  elDatePicker.addEventListener("change", function(e) {
    var selected = e.target.value;
    closeDatePicker();
    if (!selected) return;
    // 查找该日期在 state.dates 中的位置
    var idx = state.dates.indexOf(selected);
    if (idx !== -1) {
      state.currentDateIndex = idx;
      loadCurrentDate();
    } else {
      // 该日期没有数据，直接尝试加载
      state.dates.push(selected);
      state.dates.sort(function(a, b) { return a < b ? 1 : -1; });
      state.currentDateIndex = state.dates.indexOf(selected);
      loadCurrentDate();
    }
  });

  elDatePicker.addEventListener("blur", closeDatePicker);

  // ─── 拖拽调整边栏宽度 ───
  function setupResize(handle, target, side) {
    var isDragging = false;
    var startX = 0;
    var startWidth = 0;
    var minW = 0;
    var maxW = 0;

    handle.addEventListener("mousedown", function(e) {
      e.preventDefault();
      isDragging = true;
      startX = e.clientX;
      startWidth = target.offsetWidth;
      handle.classList.add("dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      document.body.style.pointerEvents = "none";
      handle.style.pointerEvents = "auto";

      if (side === "left") {
        minW = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-min-w")) || 160;
        maxW = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-max-w")) || 480;
      } else {
        minW = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--detail-min-w")) || 240;
        maxW = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--detail-max-w")) || 600;
      }
    });

    document.addEventListener("mousemove", function(e) {
      if (!isDragging) return;
      var delta;
      var newWidth;
      if (side === "left") {
        delta = e.clientX - startX;
        newWidth = startWidth + delta;
      } else {
        delta = startX - e.clientX;
        newWidth = startWidth + delta;
      }
      newWidth = Math.max(minW, Math.min(maxW, newWidth));
      target.style.width = newWidth + "px";
      var prop = side === "left" ? "--sidebar-w" : "--detail-w";
      document.documentElement.style.setProperty(prop, newWidth + "px");
    });

    document.addEventListener("mouseup", function() {
      if (!isDragging) return;
      isDragging = false;
      handle.classList.remove("dragging");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.body.style.pointerEvents = "";
      handle.style.pointerEvents = "";
      // 持久化
      try {
        if (side === "left") {
          localStorage.setItem("pp-sidebar-w", target.style.width);
        } else {
          localStorage.setItem("pp-detail-w", target.style.width);
        }
      } catch(e) {}
    });
  }

  function restoreSidebarWidths() {
    try {
      var sw = localStorage.getItem("pp-sidebar-w");
      if (sw) {
        elSidebar.style.width = sw;
        document.documentElement.style.setProperty("--sidebar-w", sw);
      }
      var dw = localStorage.getItem("pp-detail-w");
      if (dw) {
        elDetailPanel.style.width = dw;
        document.documentElement.style.setProperty("--detail-w", dw);
      }
    } catch(e) {}
  }

  // ─── 事件绑定 ───
  elPrevDate.addEventListener("click", function() {
    if (state.currentDateIndex < state.dates.length - 1) {
      state.currentDateIndex++;
      loadCurrentDate();
    }
  });

  elNextDate.addEventListener("click", function() {
    if (state.currentDateIndex > 0) {
      state.currentDateIndex--;
      loadCurrentDate();
    }
  });

  elSearchInput.addEventListener("input", function(e) {
    state.searchQuery = e.target.value;
    if (state.searchQuery) {
      elSearchClear.classList.add("visible");
    } else {
      elSearchClear.classList.remove("visible");
    }
    if (state.data) {
      computeFiltered();
      renderToolbar();
      renderArticleList();
    }
  });

  elSearchClear.addEventListener("click", function() {
    state.searchQuery = "";
    elSearchInput.value = "";
    elSearchClear.classList.remove("visible");
    if (state.data) {
      computeFiltered();
      renderToolbar();
      renderArticleList();
    }
  });

  elLangToggle.addEventListener("click", function() {
    state.lang = state.lang === "zh" ? "en" : "zh";
    try { localStorage.setItem("pp-lang", state.lang); } catch(e) {}
    applyI18n();
  });

  elThemeToggle.addEventListener("click", function() {
    var current = document.documentElement.dataset.theme;
    var next = current === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("pp-theme", next); } catch(e) {}
  });

  elSidebarToggle.addEventListener("click", toggleSidebar);
  elSidebarClose.addEventListener("click", toggleSidebar);
  elDetailClose.addEventListener("click", toggleDetail);
  elDetailReopen.addEventListener("click", toggleDetail);
  elDetailPin.addEventListener("click", toggleDetailPin);

  // 键盘快捷键
  document.addEventListener("keydown", function(e) {
    if (e.key === "/" && document.activeElement !== elSearchInput) {
      e.preventDefault();
      elSearchInput.focus();
    }
    // Esc 关闭详情
    if (e.key === "Escape" && document.documentElement.dataset.detail === "open" && !state.detailPinned) {
      toggleDetail();
    }
    // [ 切换左边栏
    if (e.key === "[" && document.activeElement !== elSearchInput) {
      toggleSidebar();
    }
    // ] 切换右边栏
    if (e.key === "]" && document.activeElement !== elSearchInput) {
      toggleDetail();
    }
  });

  // ─── 初始化 ───
  function init() {
    try {
      state.lang = localStorage.getItem("pp-lang") || "zh";
      if (state.lang !== "zh" && state.lang !== "en") state.lang = "zh";
    } catch(e) { state.lang = "zh"; }

    applyI18n();
    loadSourcesConfig();
    restoreSidebarWidths();
    setupResize(elResizeHandleLeft, elSidebar, "left");
    setupResize(elResizeHandleRight, elDetailPanel, "right");
    loadDates();
  }

  init();
})();
