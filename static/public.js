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

  const storySearch = document.querySelector("[data-story-search]");
  if (!storySearch) return;
  const storyCards = [...document.querySelectorAll(".home-journal-card")];
  const emptyMessage = document.querySelector("[data-story-search-empty]");
  storySearch.addEventListener("input", () => {
    const query = storySearch.value.trim().toLocaleLowerCase();
    let visibleCount = 0;
    storyCards.forEach((card) => {
      const matches = card.textContent.toLocaleLowerCase().includes(query);
      card.hidden = !matches;
      if (matches) visibleCount += 1;
    });
    emptyMessage.hidden = visibleCount > 0;
  });
})();
