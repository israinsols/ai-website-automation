(() => {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduceMotion && "IntersectionObserver" in window) {
    const elements = document.querySelectorAll(
      ".section-heading, .cards > *, .pricing > *, .topic-list > *, .cta-box, .newsletter-box, " +
      ".blog-feature-card, .blog-card, .public-article, .editorial-review, .related-posts, .info-sections > section, " +
      ".showcase-heading, .visual-card, .home-journal-card"
    );

    const observer = new IntersectionObserver((entries, currentObserver) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        currentObserver.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -36px 0px" });

    elements.forEach((element, index) => {
      element.classList.add("js-reveal");
      element.style.setProperty("--reveal-delay", `${Math.min(index % 4, 3) * 70}ms`);
      observer.observe(element);
    });
  }

  document.querySelectorAll("[data-menu-toggle]").forEach((toggle) => {
    const menu = document.getElementById(toggle.getAttribute("aria-controls"));
    if (!menu) return;

    const setMenuOpen = (open) => {
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Close navigation menu" : "Open navigation menu");
      menu.classList.toggle("is-open", open);
    };

    toggle.addEventListener("click", () => {
      setMenuOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    menu.addEventListener("click", (event) => {
      if (event.target instanceof Element && event.target.closest("a")) setMenuOpen(false);
    });
    document.addEventListener("click", (event) => {
      if (event.target instanceof Node && !toggle.contains(event.target) && !menu.contains(event.target)) {
        setMenuOpen(false);
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setMenuOpen(false);
        toggle.focus();
      }
    });

    window.matchMedia("(min-width: 821px)").addEventListener("change", (event) => {
      if (event.matches) setMenuOpen(false);
    });
  });

  const storySearch = document.querySelector("[data-story-search]");
  if (storySearch) {
    const storyCards = [...document.querySelectorAll("[data-story-card]")];
    const moreCards = storyCards.filter((card) => card.hasAttribute("data-load-more-card"));
    const emptyMessage = document.querySelector("[data-story-search-empty]");
    const moreStories = document.querySelector("[data-home-more-section]");
    const categoryFilters = [...document.querySelectorAll("[data-category-filter]")];
    const topicFilters = [...document.querySelectorAll("[data-topic-filter]")];
    const loadMoreButton = document.querySelector("[data-load-more]");
    const loadMoreStatus = document.querySelector("[data-load-more-status]");
    let activeCategory = "all";
    let visibleMoreLimit = 3;

    const updateStories = () => {
      const query = storySearch.value.trim().toLocaleLowerCase();
      const matches = storyCards.filter((card) => {
        const categoryMatches = activeCategory === "all" || card.dataset.category === activeCategory;
        const searchText = (card.dataset.search || card.textContent).toLocaleLowerCase();
        return categoryMatches && searchText.includes(query);
      });
      const matchingMoreCards = matches.filter((card) => card.hasAttribute("data-load-more-card"));
      const visibleCards = new Set(matches.filter(
        (card) => !card.hasAttribute("data-load-more-card")
      ).concat(matchingMoreCards.slice(0, visibleMoreLimit)));

      storyCards.forEach((card) => {
        card.hidden = !visibleCards.has(card);
      });
      emptyMessage.hidden = matches.length > 0;
      if (moreStories) moreStories.hidden = !moreCards.some((card) => visibleCards.has(card));
      if (loadMoreButton) loadMoreButton.hidden = matchingMoreCards.length <= visibleMoreLimit;
      if (loadMoreStatus) loadMoreStatus.textContent = `Showing ${visibleCards.size} of ${matches.length} stories`;
      categoryFilters.forEach((button) => {
        const isActive = button.dataset.categoryFilter === activeCategory;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
      });
    };

    storySearch.addEventListener("input", updateStories);
    categoryFilters.forEach((button) => {
      button.addEventListener("click", () => {
        activeCategory = button.dataset.categoryFilter || "all";
        visibleMoreLimit = 3;
        storySearch.value = "";
        updateStories();
      });
    });
    topicFilters.forEach((button) => {
      button.addEventListener("click", () => {
        activeCategory = "all";
        visibleMoreLimit = 3;
        storySearch.value = button.dataset.topicFilter || "";
        updateStories();
        document.querySelector("#home-journal-title")?.scrollIntoView({ behavior: "smooth" });
      });
    });
    loadMoreButton?.addEventListener("click", () => {
      visibleMoreLimit += 3;
      updateStories();
    });
    updateStories();
  }

  const journalSearch = document.querySelector("[data-journal-search]");
  if (journalSearch) {
    const journalCards = [...document.querySelectorAll("[data-journal-card]")];
    const featuredCards = journalCards.filter((card) => card.classList.contains("blog-feature-card"));
    const recentCards = journalCards.filter((card) => card.classList.contains("blog-card"));
    const featuredSection = document.querySelector("[data-journal-featured]");
    const recentSection = document.querySelector("[data-journal-recent]");
    const popularSection = document.querySelector("[data-journal-popular]");
    const results = document.querySelector("[data-journal-results]");
    const emptyMessage = document.querySelector("[data-journal-empty]");
    const clearButton = document.querySelector("[data-journal-clear]");

    const updateJournalResults = () => {
      const query = journalSearch.value.trim().toLocaleLowerCase();
      let visibleCount = 0;
      journalCards.forEach((card) => {
        const searchableText = card.getAttribute("data-search") || card.textContent;
        const matches = searchableText.toLocaleLowerCase().includes(query);
        card.hidden = !matches;
        if (matches) visibleCount += 1;
      });
      if (featuredSection) featuredSection.hidden = !featuredCards.some((card) => !card.hidden);
      if (recentSection) recentSection.hidden = !recentCards.some((card) => !card.hidden);
      if (popularSection) popularSection.hidden = query.length > 0;
      emptyMessage.hidden = visibleCount > 0;
      clearButton.hidden = query.length === 0;
      results.textContent = query
        ? `${visibleCount} ${visibleCount === 1 ? "story" : "stories"} found`
        : `Showing all ${journalCards.length} stories`;
      document.querySelector(".blog-feature-grid")?.classList.toggle("is-filtered", query.length > 0);
    };

    journalSearch.addEventListener("input", updateJournalResults);
    clearButton.addEventListener("click", () => {
      journalSearch.value = "";
      updateJournalResults();
      journalSearch.focus();
    });
  }

  const savedArticleButtons = [...document.querySelectorAll("[data-save-article]")];
  const savedStoriesPage = document.querySelector("[data-saved-page]");
  if (savedArticleButtons.length || savedStoriesPage) {
    const storageKey = "ai-website-automation:saved-articles:v1";
    const status = document.querySelector("[data-save-status], [data-saved-status]");
    const savedCards = [...document.querySelectorAll("[data-saved-card]")];
    const emptyState = document.querySelector("[data-saved-empty]");
    let savedSlugs;

    const showStorageError = (error, message) => {
      console.error("Could not access saved stories in this browser.", error);
      if (status) {
        status.textContent = message;
        status.setAttribute("role", "alert");
      }
      savedArticleButtons.forEach((button) => {
        button.disabled = true;
      });
    };

    try {
      const stored = window.localStorage.getItem(storageKey);
      const parsed = stored === null ? [] : JSON.parse(stored);
      if (!Array.isArray(parsed)) throw new TypeError("Saved article data must be a list.");
      savedSlugs = [...new Set(parsed.filter(
        (slug) => typeof slug === "string" && /^[a-z0-9][a-z0-9-]*$/.test(slug)
      ))];
    } catch (error) {
      showStorageError(error, "Saved stories are unavailable in this browser.");
    }

    if (savedSlugs) {
      const refreshSavedStories = () => {
        savedArticleButtons.forEach((button) => {
          const isSaved = savedSlugs.includes(button.dataset.saveSlug || "");
          const label = button.querySelector("[data-save-label]");
          const icon = button.querySelector("[data-save-icon]");
          button.setAttribute("aria-pressed", String(isSaved));
          button.classList.toggle("is-saved", isSaved);
          if (label) {
            label.textContent = button.hasAttribute("data-saved-page-remove")
              ? "Remove saved story"
              : isSaved ? "Saved" : "Save story";
          }
          if (icon) icon.textContent = isSaved ? "★" : "☆";
        });

        if (savedStoriesPage) {
          let visibleCount = 0;
          savedCards.forEach((card) => {
            const isSaved = savedSlugs.includes(card.dataset.savedSlug || "");
            card.hidden = !isSaved;
            if (isSaved) visibleCount += 1;
          });
          if (emptyState) emptyState.hidden = visibleCount > 0;
          if (status) {
            status.textContent = `${visibleCount} ${visibleCount === 1 ? "story" : "stories"} saved in this browser.`;
          }
        }
      };

      savedArticleButtons.forEach((button) => {
        button.addEventListener("click", () => {
          const slug = button.dataset.saveSlug || "";
          if (!/^[a-z0-9][a-z0-9-]*$/.test(slug)) {
            showStorageError(new TypeError("Article slug is invalid."), "Could not update this saved story.");
            return;
          }

          const isSaved = savedSlugs.includes(slug);
          const nextSlugs = isSaved
            ? savedSlugs.filter((savedSlug) => savedSlug !== slug)
            : [...savedSlugs, slug];
          try {
            window.localStorage.setItem(storageKey, JSON.stringify(nextSlugs));
          } catch (error) {
            showStorageError(error, "Could not save this change in your browser.");
            return;
          }

          savedSlugs = nextSlugs;
          refreshSavedStories();
          if (status && !savedStoriesPage) {
            status.textContent = isSaved
              ? "Removed from your saved stories."
              : "Saved in this browser. Find it in Saved stories.";
          }
        });
      });
      refreshSavedStories();
    }
  }

  const shareButton = document.querySelector("[data-share-article]");
  if (shareButton) {
    const shareStatus = document.querySelector("[data-share-status]");
    shareButton.addEventListener("click", async () => {
      const shareData = {
        title: shareButton.getAttribute("data-share-title") || document.title,
        url: window.location.href,
      };

      try {
        if (navigator.share) {
          await navigator.share(shareData);
          shareStatus.textContent = "Thanks for sharing this story.";
        } else if (navigator.clipboard) {
          await navigator.clipboard.writeText(shareData.url);
          shareStatus.textContent = "Story link copied.";
        } else {
          shareStatus.textContent = "Sharing is unavailable here. Copy the page address to share this story.";
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        shareStatus.textContent = "Could not share automatically. Copy the page address to share this story.";
      }
    });
  }
})();
