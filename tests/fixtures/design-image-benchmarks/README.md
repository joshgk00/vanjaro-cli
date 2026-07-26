# Assisted Image Evidence Benchmark

This synthetic desktop/mobile pair exercises the reference-image adapter's
deterministic, fail-closed contract. The raster bytes are independently bound to
the evidence sidecar by SHA-256, page slug, breakpoint, viewport, and pixel
dimensions.

The resulting extraction and matcher scores measure translation of supplied
evidence into the shared Design Document and Vanjaro template matches. They do
**not** measure autonomous OCR, computer vision, or source-asset recovery. Those
capabilities require a separately versioned evidence producer and benchmark.

Run the fixture with:

```powershell
vanjaro migrate benchmark `
  --manifest tests/fixtures/design-image-benchmarks/manifest.json `
  --output artifacts/benchmarks/agency-image-assisted `
  --json
```

The PNGs can be regenerated on Windows with
`scripts/generate_image_benchmark_fixture.ps1`.
