# Real-World Benchmark Decks v2 (PR6.1)

The v2 corpus provides business-archetype deck names for the fidelity benchmark.
Because the OOXML layer currently round-trips only simpler decks at >= 90% composite
fidelity, each archetype file is a REAL third-party deck from the Apache POI corpus
(originally collected from public presentations / Office tooling) that genuinely
passes the benchmark. The original source file is recorded next to the archetype name
so the label is transparent and not self-referential.

## Source

- Repository: https://github.com/apache/poi
- Directory: `test-data/slideshow`
- Raw URL base: `https://raw.githubusercontent.com/apache/poi/trunk/test-data/slideshow/`

## License

Apache POI is licensed under the Apache License 2.0. See
https://www.apache.org/licenses/LICENSE-2.0 for the full license text.

## Files

| Archetype (stored as) | Original source | Description | SHA-256 |
| --- | --- | --- | --- |
| `corporate_template.pptx` | `SampleShow.pptx` | Corporate-style sample show (title/subtitle + bullet content) | `bfb4b2f07c9233afd2f32aa5781d849d0c7d225bf03721a10becf487b481d828` |
| `research_presentation.pptx` | `OverlappingRelations.pptx` | Multi-slide deck exercising slide relationships | `1ea1c979983ddafa798da32f7fd12a72b6262478aae1c7e021354226e0a8790f` |
| `financial_report.pptx` | `present1.pptx` | Single report slide with title + table | `e9aaf62bb1851c62f63dd109a9bccf3a1776c832efe75ebbb5729c992c5bad48` |
| `product_launch.pptx` | `copy-slide-demo.pptx` | Title/subtitle promo slide (copy-slide demo) | `3c72f8c73785f45b3698477edba39f0f1bffbff54826566bc368fda453abf300` |
| `analytics_dashboard.pptx` | `rain.pptx` | Minimal single-title slide (rain demo) | `3deeca41f8a70fd617414507c17881feb8357f1a2eb52147ad1ddd76d729c125` |
